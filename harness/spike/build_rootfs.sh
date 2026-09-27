#!/usr/bin/env bash
# build_rootfs.sh - build the guest disk image, kernel and initramfs for the
# screenshot-harness spike, entirely with rootless Podman (no loop mounts, no root).
#
# Steps:
#   1. Stage a build context (Containerfile, guest/ and a copy of the signed
#      repository produced by `make repo`).
#   2. `podman build` installs the system into a container image.
#   3. `podman export` writes that container's file system to a tar file.
#   4. A helper container extracts the tar and runs `mke2fs -d` INSIDE the container.
#      Files therefore stay owned by root of the guest, and nothing is ever mounted.
#      The kernel and the initramfs are copied out of /boot at the same time.
#
# Outputs (in $VM_BUILD_DIR, default <project>/.build/vm - never inside the source tree):
#   root.img         sparse ext4 image of the guest
#   vmlinuz          kernel taken from the image (direct kernel boot, no bootloader)
#   initramfs.img    initramfs taken from the image
#
# Configuration comes from .env.example / .env exactly like the Makefile does it
# (DISTRO_NAME, CONTAINER_ENGINE, ARCH_ARCHIVE_DATE, REPO_DIR). Optional overrides:
#   VM_BUILD_DIR  output directory (must not contain ':')
#   VM_IMAGE_SIZE size of the sparse image, e.g. 12G (default 12G)
#
# Usage: harness/spike/build_rootfs.sh        (run `make repo` first)

set -euo pipefail
shopt -s inherit_errexit

# Fully qualified so that no registry search list can change the helper image.
HELPER_IMAGE="docker.io/library/archlinux:base"

# Fixed values that make the image reproducible. The UUID names the file system,
# the machine id is written into /etc/machine-id (see helper script below).
FS_UUID="6b1f3c52-0d0e-4d1a-9a55-5f0c2a1e7b01"
MACHINE_ID="0f1e2d3c4b5a69788796a5b4c3d2e1f0"
GUEST_HOSTNAME="kuura-vm"

# All paths derive from the location of this script.
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_DIR="$(cd -- "$SCRIPT_DIR/../.." && pwd -P)"

TMP_DIR=""      # scratch directory holding the staged build context and the tar file
CID=""          # id of the container that is exported; removed on exit

# log MESSAGE...  Progress line on stderr.
log() { printf 'build_rootfs.sh: %s\n' "$*" >&2; }

# die MESSAGE...  Error message and non-zero exit.
die() { log "error: $*"; exit 1; }

# cleanup  EXIT trap: remove the export container and the scratch directory.
# The scratch directory only holds files written by this user (the helper container
# writes root.img and friends into the bind mount as the calling user), so a plain
# rm works; the guest file system itself lives only inside the helper container.
cleanup() {
    if [ -n "$CID" ]; then
        "$CONTAINER_ENGINE" rm --force "$CID" >/dev/null 2>&1 || true
    fi
    if [ -n "$TMP_DIR" ]; then
        rm -rf -- "$TMP_DIR"
    fi
}

# load_config
# Reads the same files as the Makefile, in the same order (later files win), then
# validates every value with the rules of build/verify_install.sh: the values end
# up in image names, URLs and paths, so they are checked instead of trusted.
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
    # A size must be a plain number with a unit; it goes into mke2fs unquoted-safe.
    [[ "$VM_IMAGE_SIZE" =~ ^[1-9][0-9]*[MG]$ ]] || die "VM_IMAGE_SIZE must look like 12G or 8192M"
    case "$VM_BUILD_DIR" in
        *:*) die "VM_BUILD_DIR must not contain ':' (it is bind-mounted)" ;;
    esac
}

# stage_context
# Copies everything the image build needs into a scratch directory. The repository
# is copied (not referenced) because the build context is the only thing a
# Containerfile can COPY from.
stage_context() {
    local repo="$PROJECT_DIR/$REPO_DIR"
    [ -s "$repo/$DISTRO_NAME.pub" ] || die "'$REPO_DIR/$DISTRO_NAME.pub' is missing; run 'make repo' first"
    [ -f "$repo/x86_64/$DISTRO_NAME.db.tar.zst" ] || die "repository database is missing; run 'make repo' first"

    TMP_DIR="$(mktemp -d)"
    mkdir -p -- "$TMP_DIR/ctx"
    cp -a -- "$SCRIPT_DIR/Containerfile" "$SCRIPT_DIR/guest" "$TMP_DIR/ctx/"
    cp -a -- "$repo" "$TMP_DIR/ctx/repo"
}

# Helper script, run inside a container from the pristine base image. FIXED text:
# every value arrives as an environment variable, so no host value can become
# shell code. The quoted heredoc delimiter keeps $ literal here.
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
    cp /rootfs/boot/vmlinuz-linux /work/vmlinuz
else
    cp /rootfs/usr/lib/modules/*/vmlinuz /work/vmlinuz
fi
cp /rootfs/boot/initramfs-linux.img /work/initramfs.img

# Build the ext4 image from the directory tree WITHOUT mounting anything.
#   -d            copy the tree into the new file system (needs no privileges)
#   -m 0          no reserved blocks: the guest has no separate root user quota
#   -E root_owner the root directory belongs to root of the guest
#   -U / -L       fixed uuid and label, so root=/dev/vda works and the image is
#                 reproducible
# The size argument creates a SPARSE file: only written blocks use disk space.
rm -f /work/root.img
mke2fs -q -t ext4 -L "$FS_LABEL" -U "$FS_UUID" -m 0 -E root_owner=0:0 \
    -d /rootfs /work/root.img "$IMAGE_SIZE"

# Cheap integrity check of the result (read-only, no repair).
e2fsck -fn /work/root.img
EOF

# main
# Orchestrates the four steps described in the header.
main() {
    [ "$#" -eq 0 ] || die "usage: build_rootfs.sh (configuration comes from the environment)"
    load_config
    trap cleanup EXIT
    trap 'exit 130' INT TERM HUP
    stage_context

    local image="localhost/$DISTRO_NAME-vm-rootfs"
    mkdir -p -- "$VM_BUILD_DIR"

    log "building the guest image $image (archive snapshot $ARCH_ARCHIVE_DATE)"
    "$CONTAINER_ENGINE" build \
        --build-arg ARCH_ARCHIVE_DATE="$ARCH_ARCHIVE_DATE" \
        --build-arg DISTRO_NAME="$DISTRO_NAME" \
        --tag "$image" \
        --file "$TMP_DIR/ctx/Containerfile" \
        "$TMP_DIR/ctx"

    log "exporting the container file system to a tar file"
    CID="$("$CONTAINER_ENGINE" create "$image")"
    "$CONTAINER_ENGINE" export --output "$VM_BUILD_DIR/rootfs.tar" "$CID"

    log "creating the ext4 image ($VM_IMAGE_SIZE, sparse) inside a helper container"
    # label=disable: no SELinux relabelling of the bind mount (harmless elsewhere).
    # Variables are passed by name (--env NAME), never by value on the command line.
    export GUEST_HOSTNAME MACHINE_ID FS_UUID
    export FS_LABEL="$DISTRO_NAME-root"
    export IMAGE_SIZE="$VM_IMAGE_SIZE"
    "$CONTAINER_ENGINE" run --rm \
        --security-opt label=disable \
        --volume "$VM_BUILD_DIR:/work" \
        --env GUEST_HOSTNAME --env MACHINE_ID --env FS_UUID --env FS_LABEL --env IMAGE_SIZE \
        "$HELPER_IMAGE" bash -c "$HELPER_SCRIPT"

    log "done:"
    ls -lsh -- "$VM_BUILD_DIR/root.img" "$VM_BUILD_DIR/vmlinuz" "$VM_BUILD_DIR/initramfs.img" >&2
}

main "$@"
