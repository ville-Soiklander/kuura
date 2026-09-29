#!/usr/bin/env bash
# build_rootfs.sh - build the guest disk image, kernel and initramfs of the screenshot
# harness (docs/HARNESS_CONTRACT.md), entirely with rootless Podman: no loop mounts, no root.
#
# Steps:
#   1. Stage a build context (Containerfile, guest/, a copy of the signed repository
#      produced by `make repo`) and read the dependency list of the metapackage.
#   2. `podman build` installs the system into a container image (layer cache: see the
#      Containerfile).
#   3. `podman export` writes that container's file system to a tar file.
#   4. A helper container extracts the tar and runs `mke2fs -d` INSIDE the container.
#      Files therefore stay owned by root of the guest, and nothing is ever mounted.
#      The kernel and the initramfs are copied out of /boot at the same time.
#   5. The three results are renamed into place one by one. They are first written under
#      the names *.new, so a program that reads the image while a build is running never
#      sees a half-written file (a rename within one directory is atomic).
#
# Outputs (in $VM_BUILD_DIR, default <project>/.build/vm - never inside the source tree):
#   root.img         sparse ext4 image of the guest
#   vmlinuz          kernel taken from the image (direct kernel boot, no bootloader)
#   initramfs.img    initramfs taken from the image
#
# Configuration comes from .env.example / .env exactly like the Makefile does it
# (DISTRO_NAME, CONTAINER_ENGINE, ARCH_ARCHIVE_DATE, REPO_DIR). Optional overrides:
#   VM_BUILD_DIR   output directory (must not contain ':')
#   VM_IMAGE_SIZE  size of the sparse image, e.g. 12G (default 12G)
#
# Usage: harness/vm/build_rootfs.sh        (run `make repo` first, or use `make vm-image`)

set -euo pipefail
shopt -s inherit_errexit

# Fully qualified so that no registry search list can change the helper image.
readonly HELPER_IMAGE="docker.io/library/archlinux:base"

# Fixed values that make the image reproducible. The UUID names the file system (and seeds
# its directory hash), the machine id is written into /etc/machine-id (see helper script).
readonly FS_UUID="6b1f3c52-0d0e-4d1a-9a55-5f0c2a1e7b01"
readonly MACHINE_ID="0f1e2d3c4b5a69788796a5b4c3d2e1f0"

# All paths derive from the location of this script.
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_DIR="$(cd -- "$SCRIPT_DIR/../.." && pwd -P)"
readonly SCRIPT_DIR PROJECT_DIR

TMP_DIR=""      # scratch directory holding the staged build context
CID=""          # id of the container that is exported; removed on exit
DESKTOP_DEPS="" # space separated dependencies of the metapackage (see read_metapackage_deps)

# log MESSAGE...  Progress line on stderr.
log() { printf 'build_rootfs.sh: %s\n' "$*" >&2; }

# die MESSAGE...  Error message and non-zero exit.
die() { log "error: $*"; exit 1; }

# cleanup  EXIT trap: remove the export container, the scratch directory and every
# unfinished output. The scratch directory only holds files written by this user (the
# helper container writes into the bind mount as the calling user), so a plain rm works;
# the guest file system itself lives only inside the helper container.
cleanup() {
    if [ -n "$CID" ]; then
        "$CONTAINER_ENGINE" rm --force "$CID" >/dev/null 2>&1 || true
    fi
    if [ -n "$TMP_DIR" ]; then
        rm -rf -- "$TMP_DIR"
    fi
    if [ -n "${VM_BUILD_DIR:-}" ] && [ -d "$VM_BUILD_DIR" ]; then
        rm -f -- "$VM_BUILD_DIR/rootfs.tar" "$VM_BUILD_DIR/root.img.new" \
            "$VM_BUILD_DIR/vmlinuz.new" "$VM_BUILD_DIR/initramfs.img.new"
    fi
}

# load_config
# Reads the same files as the Makefile, in the same order (later files win), then
# validates every value with the rules of build/verify_install.sh: the values end up in
# image names, URLs and paths, so they are checked instead of trusted.
load_config() {
    # tr -d '\r': a checkout synced from a Windows drive may carry CRLF line ends,
    # which would end up as a trailing carriage return inside every value.
    set -a
    # shellcheck disable=SC1090
    . <(tr -d '\r' < "$PROJECT_DIR/.env.example")
    if [ -f "$PROJECT_DIR/.env" ]; then
        # shellcheck disable=SC1090
        . <(tr -d '\r' < "$PROJECT_DIR/.env")
    fi
    set +a

    [ -n "${DISTRO_NAME:-}" ] || die "DISTRO_NAME is not set"
    [ -n "${CONTAINER_ENGINE:-}" ] || die "CONTAINER_ENGINE is not set"
    [ -n "${ARCH_ARCHIVE_DATE:-}" ] || die "ARCH_ARCHIVE_DATE is not set"
    [ -n "${REPO_DIR:-}" ] || die "REPO_DIR is not set"
    [[ "$DISTRO_NAME" =~ ^[a-z0-9][a-z0-9_-]*$ ]] || die "invalid DISTRO_NAME"
    [[ "$ARCH_ARCHIVE_DATE" =~ ^[0-9]{4}/[0-9]{2}/[0-9]{2}$ ]] || die "invalid ARCH_ARCHIVE_DATE"
    case "$CONTAINER_ENGINE" in
        podman | docker) ;;
        *) die "CONTAINER_ENGINE must be podman or docker" ;;
    esac
    case "$REPO_DIR" in
        . | .. | /* | ../* | */.. | */../*) die "REPO_DIR must be a relative path inside the project" ;;
    esac
    command -v "$CONTAINER_ENGINE" >/dev/null 2>&1 || die "'$CONTAINER_ENGINE' not found in PATH"

    VM_BUILD_DIR="${VM_BUILD_DIR:-$PROJECT_DIR/.build/vm}"
    VM_IMAGE_SIZE="${VM_IMAGE_SIZE:-12G}"
    # A size must be a plain number with a unit; it goes into mke2fs.
    [[ "$VM_IMAGE_SIZE" =~ ^[1-9][0-9]*[MG]$ ]] || die "VM_IMAGE_SIZE must look like 12G or 8192M"
    case "$VM_BUILD_DIR" in
        *:*) die "VM_BUILD_DIR must not contain ':' (it is bind-mounted)" ;;
    esac
}

# acquire_lock
# Only one build may write the output directory at a time. The lock is held by file
# descriptor 9 until the process exits, so it cannot be left behind by a crash.
acquire_lock() {
    command -v flock >/dev/null 2>&1 || { log "flock not found, running without a build lock"; return 0; }
    exec 9> "$VM_BUILD_DIR/.build.lock"
    flock --nonblock 9 || die "another build_rootfs.sh is already running for '$VM_BUILD_DIR'"
}

# read_metapackage_deps
# Sets DESKTOP_DEPS to the UPSTREAM dependency names of the metapackage (Arch's own
# mirrors), in PKGBUILD order, EXCLUDING every dependency that is itself another
# package built by this monorepo (packages/*/PKGBUILD - for example "<name>-shell",
# added to kuura-desktop's `depends` by docs/SHELL_CONTRACT.md: "installed by
# kuura-desktop (added to its depends)"). WHY exclude those: the Containerfile installs
# DESKTOP_DEPS in an early, cached layer that runs BEFORE the local signed repository is
# even added to pacman.conf (that happens in a later layer, right before the
# metapackage itself is installed - see the Containerfile's own layer-order comment). A
# locally built dependency does not exist anywhere pacman can see it yet at that point
# - confirmed live: `pacman -S ... kuura-shell` in that early layer fails with "error:
# target not found: kuura-shell" even though the package is already sitting in
# $REPO_DIR, because pacman.conf does not know about that repo yet. It needs no special
# handling here beyond leaving it out: by the time `pacman -S "$DISTRO_NAME-desktop"`
# runs (later layer, repo already configured), pacman resolves and installs it
# automatically as an unmet dependency, exactly like every other dependency of the
# metapackage. Version constraints (foo>=1) are stripped; the pinned snapshot decides
# versions.
read_metapackage_deps() {
    local pkgbuild="" candidate name
    # First pass: the pkgname of every PKGBUILD this monorepo itself builds, so the
    # second pass below can recognise and skip them regardless of `depends` order.
    local local_pkgs=""
    for candidate in "$PROJECT_DIR"/packages/*/PKGBUILD; do
        [ -f "$candidate" ] || continue
        name="$( (set +u; . "$candidate" >/dev/null 2>&1; printf '%s' "${pkgname:-}") || true)"
        [ -n "$name" ] || continue
        local_pkgs="$local_pkgs $name"
        if [ "$name" = "$DISTRO_NAME-desktop" ]; then
            pkgbuild="$candidate"
        fi
    done
    [ -n "$pkgbuild" ] || die "no PKGBUILD for '$DISTRO_NAME-desktop' found under packages/"

    local dep list=""
    while IFS= read -r dep; do
        dep="${dep%%[<>=]*}"
        [[ "$dep" =~ ^[a-z0-9@][a-z0-9@._+-]*$ ]] || die "unsupported dependency name in PKGBUILD: '$dep'"
        case " $local_pkgs " in
            *" $dep "*) continue ;; # locally built: left for the metapackage-install step
        esac
        list="$list $dep"
    done < <( (set +u; . "$pkgbuild" >/dev/null 2>&1; printf '%s\n' "${depends[@]}") )
    DESKTOP_DEPS="${list# }"
    [ -n "$DESKTOP_DEPS" ] || die "the metapackage has no dependencies"
}

# stage_context
# Copies everything the image build needs into a scratch directory. The repository is
# copied (not referenced) because the build context is the only thing a Containerfile
# can COPY from.
stage_context() {
    local repo="$PROJECT_DIR/$REPO_DIR"
    [ -s "$repo/$DISTRO_NAME.pub" ] || die "'$REPO_DIR/$DISTRO_NAME.pub' is missing; run 'make repo' first"
    [ -f "$repo/x86_64/$DISTRO_NAME.db.tar.zst" ] || die "repository database is missing; run 'make repo' first"

    TMP_DIR="$(mktemp -d)"
    mkdir -p -- "$TMP_DIR/ctx"
    cp -a -- "$SCRIPT_DIR/Containerfile" "$SCRIPT_DIR/guest" "$TMP_DIR/ctx/"
    cp -a -- "$repo" "$TMP_DIR/ctx/repo"

    # WHY normalise the modes: COPY takes file modes from the build context, and a
    # checkout on a Windows drive or with an unusual umask reports odd modes (every
    # directory world-writable, for example). COPY of guest/overlay/ onto / would carry
    # such a mode to /usr, /etc and so on. Directories and files get fixed modes; only
    # the scripts are executable.
    find "$TMP_DIR/ctx/guest" -type d -exec chmod 0755 {} +
    find "$TMP_DIR/ctx/guest" -type f -exec chmod 0644 {} +
    chmod 0755 -- "$TMP_DIR"/ctx/guest/make-sample-tree.sh \
        "$TMP_DIR"/ctx/guest/overlay/usr/local/bin/* \
        "$TMP_DIR"/ctx/guest/skel/.config/plasma-workspace/env/*.sh
}

# Helper script, run inside a container from the pristine base image. FIXED text: every
# value arrives as an environment variable, so no host value can become shell code. The
# quoted heredoc delimiter keeps $ literal here.
IFS= read -r -d '' HELPER_SCRIPT <<'EOF' || true
set -euo pipefail

# Extract the exported file system inside the container. --numeric-owner keeps the
# ids of the tar file; running as the container's root keeps root ownership for
# root's files. /dev is skipped: a rootless container may not create device nodes
# and the guest gets /dev from devtmpfs anyway.
mkdir /rootfs
tar --extract --file /work/rootfs.tar --directory /rootfs \
    --numeric-owner --same-permissions --xattrs --xattrs-include='*' \
    --exclude='./dev/*' --exclude='dev/*'
rm -f /work/rootfs.tar

# Files that the container engine owns while a container runs (hostname, hosts,
# resolv.conf) are not persisted by `RUN` steps, so they are set here.
printf '%s\n' "$GUEST_HOSTNAME" > /rootfs/etc/hostname
printf '127.0.0.1 localhost\n::1 localhost\n' > /rootfs/etc/hosts
rm -f /rootfs/etc/resolv.conf
# A fixed machine id keeps journal names and other id-derived state identical
# between builds.
printf '%s\n' "$MACHINE_ID" > /rootfs/etc/machine-id
chmod 0444 /rootfs/etc/machine-id

# Kernel and initramfs for direct kernel boot. Prefer the copies in /boot; fall
# back to the module directory, where the kernel package always installs vmlinuz.
if [ -f /rootfs/boot/vmlinuz-linux ]; then
    cp /rootfs/boot/vmlinuz-linux /work/vmlinuz.new
else
    cp /rootfs/usr/lib/modules/*/vmlinuz /work/vmlinuz.new
fi
cp /rootfs/boot/initramfs-linux.img /work/initramfs.img.new

# Build the ext4 image from the directory tree WITHOUT mounting anything.
#   -d            copy the tree into the new file system (needs no privileges)
#   -m 0          no reserved blocks: the guest has no separate root user quota
#   -E root_owner the root directory belongs to root of the guest
#   hash_seed     fixed (instead of random), part of making the image reproducible
#   -U / -L       fixed uuid and label, so root=/dev/vda works and the image is
#                 reproducible
# The size argument creates a SPARSE file: only written blocks use disk space.
rm -f /work/root.img.new
mke2fs -q -t ext4 -L "$FS_LABEL" -U "$FS_UUID" -m 0 -E "root_owner=0:0,hash_seed=$FS_UUID" \
    -d /rootfs /work/root.img.new "$IMAGE_SIZE"

# Cheap integrity check of the result (read-only, no repair).
e2fsck -fn /work/root.img.new
EOF

# publish_outputs
# Renames the finished *.new files to their final names. Order: initramfs and kernel
# first, the (large) root image last, so the pieces that belong together are swapped
# within a moment of each other.
publish_outputs() {
    mv -f -- "$VM_BUILD_DIR/initramfs.img.new" "$VM_BUILD_DIR/initramfs.img"
    mv -f -- "$VM_BUILD_DIR/vmlinuz.new" "$VM_BUILD_DIR/vmlinuz"
    mv -f -- "$VM_BUILD_DIR/root.img.new" "$VM_BUILD_DIR/root.img"
}

# main
# Orchestrates the steps described in the header.
main() {
    [ "$#" -eq 0 ] || die "usage: build_rootfs.sh (configuration comes from the environment)"
    SECONDS=0
    load_config
    trap cleanup EXIT
    trap 'exit 130' INT TERM HUP
    mkdir -p -- "$VM_BUILD_DIR"
    VM_BUILD_DIR="$(cd -- "$VM_BUILD_DIR" && pwd -P)"
    acquire_lock
    read_metapackage_deps
    stage_context

    local image="localhost/$DISTRO_NAME-vm-rootfs"

    log "building the guest image $image (archive snapshot $ARCH_ARCHIVE_DATE)"
    "$CONTAINER_ENGINE" build \
        --build-arg ARCH_ARCHIVE_DATE="$ARCH_ARCHIVE_DATE" \
        --build-arg DISTRO_NAME="$DISTRO_NAME" \
        --build-arg DESKTOP_DEPS="$DESKTOP_DEPS" \
        --tag "$image" \
        --file "$TMP_DIR/ctx/Containerfile" \
        "$TMP_DIR/ctx"

    log "exporting the container file system to a tar file"
    CID="$("$CONTAINER_ENGINE" create "$image")"
    "$CONTAINER_ENGINE" export --output "$VM_BUILD_DIR/rootfs.tar" "$CID"

    log "creating the ext4 image ($VM_IMAGE_SIZE, sparse) inside a helper container"
    # label=disable: no SELinux relabelling of the bind mount (harmless elsewhere).
    # Variables are passed by name (--env NAME), never by value on the command line.
    # The host name is derived from the configured codename.
    export GUEST_HOSTNAME="$DISTRO_NAME-vm" MACHINE_ID FS_UUID
    export FS_LABEL="$DISTRO_NAME-root"
    export IMAGE_SIZE="$VM_IMAGE_SIZE"
    "$CONTAINER_ENGINE" run --rm \
        --security-opt label=disable \
        --volume "$VM_BUILD_DIR:/work" \
        --env GUEST_HOSTNAME --env MACHINE_ID --env FS_UUID --env FS_LABEL --env IMAGE_SIZE \
        "$HELPER_IMAGE" bash -c "$HELPER_SCRIPT"

    publish_outputs
    log "done in ${SECONDS}s:"
    ls -lsh -- "$VM_BUILD_DIR/root.img" "$VM_BUILD_DIR/vmlinuz" "$VM_BUILD_DIR/initramfs.img" >&2
}

main "$@"
