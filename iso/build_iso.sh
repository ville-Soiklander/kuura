#!/usr/bin/env bash
# build_iso.sh - build the live ISO (docs/ISO_CONTRACT.md) from iso/profile/, entirely
# with rootless Podman by default: no loop mounts, no root on the engine side. The
# profile's own @DISTRO_NAME@ template tokens (pacman.conf has no shell variable
# expansion of its own, unlike profiledef.sh) are substituted in a staged copy; the
# git-tracked iso/profile/ is never modified.
#
# Steps:
#   1. Stage a build context (Containerfile, run_mkarchiso.sh, the profile with its
#      template tokens substituted, a copy of the signed repository produced by
#      `make repo`) - see stage_context().
#   2. `podman build` installs mkarchiso and its dependencies into an image pinned to
#      the same Arch Linux Archive snapshot as every other build here (layer cache:
#      see iso/Containerfile).
#   3. A container from that image runs iso/run_mkarchiso.sh, which trusts kuura's
#      repository key on the container's own system keyring and then invokes
#      mkarchiso against the staged profile.
#   4. The finished .iso (and mkarchiso's own checksum/signature siblings) are copied
#      out of the container into $ISO_BUILD_DIR.
#
# Configuration comes from .env.example / .env exactly like harness/vm/build_rootfs.sh
# (DISTRO_NAME, CONTAINER_ENGINE, ARCH_ARCHIVE_DATE, REPO_DIR). Optional overrides:
#   ISO_BUILD_DIR     output directory (must not contain ':'; default <project>/.build/iso)
#   SOURCE_DATE_EPOCH fixed build timestamp; derived from ARCH_ARCHIVE_DATE if unset,
#                     exactly like build/build_repo.sh's set_source_date_epoch
#   MKARCHISO_MODE    "rootless" (default, see docs/ISO_CONTRACT.md's "Rootless
#                     build" section) or "root" - an explicit, logged fallback for
#                     when rootless is empirically proven not to work; never chosen
#                     silently by this script itself
#   ISO_PRIVILEGED    "1" adds --privileged to the container the mkarchiso run uses;
#                     a second, stronger fallback if MKARCHISO_MODE=root alone is
#                     still not enough, again never the default
#
# Usage: iso/build_iso.sh        (run `make repo` first, or use `make iso`)

set -euo pipefail
shopt -s inherit_errexit

# All paths are derived from the location of this script.
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd -P)"
readonly SCRIPT_DIR PROJECT_DIR

TMP_DIR="" # scratch directory holding the staged build context
CID=""     # id of the container that runs mkarchiso; removed on exit

log() { printf 'build_iso.sh: %s\n' "$*" >&2; }
die() { log "error: $*"; exit 1; }

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
# validates every value the same way harness/vm/build_rootfs.sh does (the values end
# up in image names, URLs and paths).
load_config() {
    set -a
    # shellcheck disable=SC1090
    . <(tr -d '\r' <"$PROJECT_DIR/.env.example")
    if [ -f "$PROJECT_DIR/.env" ]; then
        # shellcheck disable=SC1090
        . <(tr -d '\r' <"$PROJECT_DIR/.env")
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

    # Same derivation as build/build_repo.sh's set_source_date_epoch: an explicit
    # value wins, otherwise midnight UTC of the archive date, so the ISO's own
    # timestamp is fixed by configuration, not by when the build happens to run.
    if [ -z "${SOURCE_DATE_EPOCH:-}" ]; then
        SOURCE_DATE_EPOCH="$(date -u -d "${ARCH_ARCHIVE_DATE//\//-} 00:00:00" +%s)"
    fi
    [[ "$SOURCE_DATE_EPOCH" =~ ^[0-9]+$ ]] || die "SOURCE_DATE_EPOCH must be an integer"
    # Without this, the variable is only a local shell value: `podman create -e
    # SOURCE_DATE_EPOCH` (no value given) passes through whatever is in THIS
    # process's exported environment, and a derived-but-unexported value would
    # silently reach the container as empty (confirmed by a real run:
    # run_mkarchiso.sh failed with "error: SOURCE_DATE_EPOCH is not set" until
    # this export was added).
    export SOURCE_DATE_EPOCH

    MKARCHISO_MODE="${MKARCHISO_MODE:-rootless}"
    case "$MKARCHISO_MODE" in
        rootless | root) ;;
        *) die "MKARCHISO_MODE must be 'rootless' or 'root'" ;;
    esac
    ISO_PRIVILEGED="${ISO_PRIVILEGED:-0}"

    ISO_BUILD_DIR="${ISO_BUILD_DIR:-$PROJECT_DIR/.build/iso}"
    case "$ISO_BUILD_DIR" in
        *:*) die "ISO_BUILD_DIR must not contain ':' (it is bind-mounted)" ;;
    esac
}

# acquire_lock
# Only one ISO build may write the output directory at a time, same idea as
# harness/vm/build_rootfs.sh's lock.
acquire_lock() {
    command -v flock >/dev/null 2>&1 || { log "flock not found, running without a build lock"; return 0; }
    exec 9>"$ISO_BUILD_DIR/.build.lock"
    flock --nonblock 9 || die "another build_iso.sh is already running for '$ISO_BUILD_DIR'"
}

# Boot menu files (BIOS syslinux, UEFI systemd-boot, GRUB) whose titles use the
# @DISTRO_DISPLAY_NAME@ template token; tests/test_boot_menu_branding.py keeps this
# list in sync with the profile.
BOOT_MENU_FILES=(
    syslinux/archiso_head.cfg syslinux/archiso_sys-linux.cfg syslinux/archiso_pxe-linux.cfg
    efiboot/loader/entries/01-archiso-linux.conf efiboot/loader/entries/02-archiso-speech-linux.conf
    grub/grub.cfg grub/loopback.cfg
)

# stage_context
# Copies everything the image build and the mkarchiso run need into a scratch
# directory, substitutes the @DISTRO_NAME@ template token, and stages the shipped
# repository copy. The git-tracked iso/profile/ is only ever read, never written.
stage_context() {
    local repo="$PROJECT_DIR/$REPO_DIR"
    [ -s "$repo/$DISTRO_NAME.pub" ] || die "'$REPO_DIR/$DISTRO_NAME.pub' is missing; run 'make repo' first"
    [ -f "$repo/x86_64/$DISTRO_NAME.db.tar.zst" ] || die "repository database is missing; run 'make repo' first"

    TMP_DIR="$(mktemp -d)"
    mkdir -p -- "$TMP_DIR/ctx"
    cp -a -- "$SCRIPT_DIR/Containerfile" "$SCRIPT_DIR/run_mkarchiso.sh" "$SCRIPT_DIR/profile" "$TMP_DIR/ctx/"
    cp -a -- "$repo" "$TMP_DIR/ctx/repo-src"

    # pacman.conf and packages.x86_64 have no shell variable expansion of their own
    # (unlike profiledef.sh, which is sourced as real bash) - the @DISTRO_NAME@
    # template token in both, and in the shipped airootfs/etc/pacman.conf, is
    # substituted here, in the staged copy only.
    local f
    for f in pacman.conf packages.x86_64 airootfs/etc/pacman.conf; do
        [ -f "$TMP_DIR/ctx/profile/$f" ] || die "expected template file missing: profile/$f"
        sed -i "s/@DISTRO_NAME@/$DISTRO_NAME/g" "$TMP_DIR/ctx/profile/$f"
    done

    # Boot menu titles carry the capitalised display name (${DISTRO_NAME^} is the same
    # rule as name.capitalize() in design/generators/calamares_branding.py; the name is
    # validated lowercase above). These files are templates only in the staged copy.
    for f in "${BOOT_MENU_FILES[@]}"; do
        [ -f "$TMP_DIR/ctx/profile/$f" ] || die "expected boot menu file missing: profile/$f"
        sed -i "s/@DISTRO_DISPLAY_NAME@/${DISTRO_NAME^}/g" "$TMP_DIR/ctx/profile/$f"
    done

    # Ship a second copy of the repository inside the airootfs overlay itself (see
    # airootfs/etc/pacman.conf's own comment for why this path, /srv/repo, is
    # different from repo-src/ above): this is what the LIVE system's pacman and
    # Calamares see at /srv/repo once mkarchiso copies airootfs/. into the image.
    mkdir -p -- "$TMP_DIR/ctx/profile/airootfs/srv/repo"
    cp -a -- "$repo/." "$TMP_DIR/ctx/profile/airootfs/srv/repo/"

    # WHY normalise modes: a checkout on a Windows drive (or an unusual umask) can
    # report odd file modes, and mkarchiso's airootfs overlay copies them onto the
    # live root largely as found (see profile/profiledef.sh's file_permissions array
    # for the handful of exceptions upstream already fixes up). Directories and files
    # get fixed modes; only the two scripts that must run as programs are executable.
    find "$TMP_DIR/ctx/profile" -type d -exec chmod 0755 {} +
    find "$TMP_DIR/ctx/profile" -type f -exec chmod 0644 {} +
    chmod 0755 -- "$TMP_DIR/ctx/profile/airootfs/root/customize_airootfs.sh" "$TMP_DIR/ctx/run_mkarchiso.sh"
    # /etc/shadow leaving the staging step world-unreadable is deliberate (upstream's
    # own file_permissions array fixes its final mode to 0:0:400 again later anyway;
    # this just avoids a harmless-but-wrong 0644 round-trip through the build context).
    [ -f "$TMP_DIR/ctx/profile/airootfs/etc/shadow" ] && chmod 0600 -- "$TMP_DIR/ctx/profile/airootfs/etc/shadow"
}

main() {
    [ "$#" -eq 0 ] || die "usage: build_iso.sh (configuration comes from the environment)"
    SECONDS=0
    load_config
    trap cleanup EXIT
    trap 'exit 130' INT TERM HUP
    mkdir -p -- "$ISO_BUILD_DIR"
    ISO_BUILD_DIR="$(cd -- "$ISO_BUILD_DIR" && pwd -P)"
    acquire_lock
    stage_context

    local image="localhost/$DISTRO_NAME-iso-build"

    log "building the ISO build image $image (archive snapshot $ARCH_ARCHIVE_DATE)"
    "$CONTAINER_ENGINE" build \
        --build-arg ARCH_ARCHIVE_DATE="$ARCH_ARCHIVE_DATE" \
        --tag "$image" \
        --file "$TMP_DIR/ctx/Containerfile" \
        "$TMP_DIR/ctx"

    local -a run_flags=()
    if [ "$ISO_PRIVILEGED" = 1 ]; then
        log "WARNING: ISO_PRIVILEGED=1 - running the mkarchiso container --privileged." \
            "This is the documented last-resort fallback (docs/ISO_CONTRACT.md:" \
            "\"fall back to --privileged only if that genuinely fails\"); it is never" \
            "chosen automatically by this script."
        run_flags+=(--privileged)
    fi

    log "running mkarchiso in a container from $image (mode: $MKARCHISO_MODE)"
    CID="$("$CONTAINER_ENGINE" create \
        "${run_flags[@]}" \
        -e DISTRO_NAME -e SOURCE_DATE_EPOCH -e MKARCHISO_MODE \
        "$image")"
    "$CONTAINER_ENGINE" start --attach "$CID"

    rm -rf -- "$ISO_BUILD_DIR"/*.iso
    "$CONTAINER_ENGINE" cp "$CID:/home/builder/out/." "$ISO_BUILD_DIR/"

    log "done in ${SECONDS}s:"
    ls -lsh -- "$ISO_BUILD_DIR"/*.iso >&2
}

main "$@"
