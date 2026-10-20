#!/usr/bin/env bash
# build_iso_host.sh - build the live ISO directly on an Arch Linux build host with
# mkarchiso, as root (no container). This is the path the verified ISOs were built
# with; iso/build_iso.sh is the rootless-Podman alternative. Both stage the same
# profile; the staging steps below mirror iso/build_iso.sh's stage_context() (that
# script cannot be sourced without running its main, so the duplication is
# deliberate and listed in docs/BUILD_CONTRACT.md "Release").
#
# Steps:
#   1. Stage iso/profile/ + the signed repository (`make repo` output) into a work dir,
#      substitute @DISTRO_NAME@ and point the build-time [<distro>] Server line at the
#      staged repository copy.
#   2. Import and locally sign the repository key in the HOST pacman keyring.
#   3. Purge stale /var/cache/pacman/pkg/<distro>-*.pkg.tar.zst*: pacman's cache is
#      keyed by file name, and a rebuilt package with an unchanged name/version was
#      served stale from it five times in this project.
#      The same staged pacman.conf is PINNED to the Arch Linux Archive snapshot
#      ARCH_ARCHIVE_DATE (every uncommented `Include = /etc/pacman.d/mirrorlist` becomes
#      an archive Server line) and given a dedicated CacheDir inside the scratch dir,
#      so neither the host's rolling mirrorlist nor its package cache can supply a
#      newer package (see pin_pacman_conf).
#   4. Fresh work/ and out/, `mkarchiso -v`, with SOURCE_DATE_EPOCH.
#   5. Replace the ISO in .build/iso/ and verify the copy's checksum.
#
# Configuration: .env.example / .env (DISTRO_NAME, ARCH_ARCHIVE_DATE, REPO_DIR) like the
# other scripts. Optional overrides:
#   HOST_BUILD_DIR    absolute scratch dir, must live on a native Linux filesystem
#                     (not a /mnt/<drive> mount); default $HOME/<distro>_iso_build
#   ISO_BUILD_DIR     destination of the finished ISO (default <project>/.build/iso)
#   SOURCE_DATE_EPOCH derived from ARCH_ARCHIVE_DATE if unset
#
# Usage (as root, on the build host):  bash release/build_iso_host.sh   (or `make iso-host`)
# Run `make repo` first; this script only consumes $REPO_DIR.

set -euo pipefail
shopt -s inherit_errexit

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd -P)"
readonly SCRIPT_DIR PROJECT_DIR
readonly MARKER=".kuura-host-build"

log() { printf 'build_iso_host.sh: %s\n' "$*" >&2; }
die() { log "error: $*"; exit 1; }

# load_config
# Same sources and validation as iso/build_iso.sh's load_config (later files win).
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
    [ -n "${ARCH_ARCHIVE_DATE:-}" ] || die "ARCH_ARCHIVE_DATE is not set"
    [ -n "${REPO_DIR:-}" ] || die "REPO_DIR is not set"
    [[ "$DISTRO_NAME" =~ ^[a-z0-9][a-z0-9_-]*$ ]] || die "invalid DISTRO_NAME"
    [[ "$ARCH_ARCHIVE_DATE" =~ ^[0-9]{4}/[0-9]{2}/[0-9]{2}$ ]] || die "invalid ARCH_ARCHIVE_DATE"
    case "$REPO_DIR" in
        . | .. | /* | ../* | */.. | */../*) die "REPO_DIR must be a relative path inside the project" ;;
    esac

    if [ -z "${SOURCE_DATE_EPOCH:-}" ]; then
        SOURCE_DATE_EPOCH="$(date -u -d "${ARCH_ARCHIVE_DATE//\//-} 00:00:00" +%s)"
    fi
    [[ "$SOURCE_DATE_EPOCH" =~ ^[0-9]+$ ]] || die "SOURCE_DATE_EPOCH must be an integer"
    export DISTRO_NAME SOURCE_DATE_EPOCH

    HOST_BUILD_DIR="${HOST_BUILD_DIR:-$HOME/${DISTRO_NAME}_iso_build}"
    ISO_BUILD_DIR="${ISO_BUILD_DIR:-$PROJECT_DIR/.build/iso}"
}

# check_host
# Fails early, with the reason, if this is not a usable build host.
check_host() {
    [ "$(id -u)" -eq 0 ] || die "must run as root (mkarchiso and pacman-key need it); this is the build-host path"
    local tool
    for tool in mkarchiso pacman-key gpg sha256sum awk; do
        command -v "$tool" >/dev/null 2>&1 || die "'$tool' not found; run this on an Arch build host with archiso installed"
    done
    case "$HOST_BUILD_DIR" in
        /*) ;;
        *) die "HOST_BUILD_DIR must be an absolute path" ;;
    esac
    case "$HOST_BUILD_DIR" in
        /mnt/* | *:*) die "HOST_BUILD_DIR must be on a native Linux filesystem (file modes and ownership break on drive mounts)" ;;
    esac
    # WHY these refusals: the directory is deleted with rm -rf below.
    case "$HOST_BUILD_DIR" in
        / | /root | /home | "$HOME" | "$PROJECT_DIR" | "$PROJECT_DIR"/*) die "HOST_BUILD_DIR '$HOST_BUILD_DIR' is not a safe scratch location" ;;
    esac
    if [ -e "$HOST_BUILD_DIR" ] && [ ! -f "$HOST_BUILD_DIR/$MARKER" ]; then
        die "'$HOST_BUILD_DIR' exists but was not created by this script (no $MARKER); refusing to delete it"
    fi
}

# fresh_dir
# Recreates the scratch dir and marks it, so a later run may delete it again.
fresh_dir() {
    rm -rf -- "$HOST_BUILD_DIR"
    mkdir -p -- "$HOST_BUILD_DIR/ctx"
    : >"$HOST_BUILD_DIR/$MARKER"
}

# stage_profile
# Mirrors iso/build_iso.sh stage_context(), minus the container files, plus the
# host-specific Server rewrite.
stage_profile() {
    local repo="$PROJECT_DIR/$REPO_DIR" ctx="$HOST_BUILD_DIR/ctx" f
    [ -s "$repo/$DISTRO_NAME.pub" ] || die "'$REPO_DIR/$DISTRO_NAME.pub' is missing; run 'make repo' first"
    [ -f "$repo/x86_64/$DISTRO_NAME.db.tar.zst" ] || die "repository database is missing; run 'make repo' first"

    cp -a -- "$PROJECT_DIR/iso/profile" "$ctx/profile"
    cp -a -- "$repo" "$ctx/repo-src"

    for f in pacman.conf packages.x86_64 airootfs/etc/pacman.conf; do
        [ -f "$ctx/profile/$f" ] || die "expected template file missing: profile/$f"
        sed -i "s/@DISTRO_NAME@/$DISTRO_NAME/g" "$ctx/profile/$f"
    done

    # Boot menu titles: capitalised display name (same rule as iso/build_iso.sh).
    for f in syslinux/archiso_head.cfg syslinux/archiso_sys-linux.cfg syslinux/archiso_pxe-linux.cfg         efiboot/loader/entries/01-archiso-linux.conf efiboot/loader/entries/02-archiso-speech-linux.conf         grub/grub.cfg grub/loopback.cfg airootfs/etc/motd airootfs/etc/issue; do
        [ -f "$ctx/profile/$f" ] || die "expected boot menu file missing: profile/$f"
        sed -i "s/@DISTRO_DISPLAY_NAME@/${DISTRO_NAME^}/g" "$ctx/profile/$f"
    done

    # The profile's build-time Server points at the container's /home/builder; on the host
    # it must name the staged copy. Fail if the line is not there, instead of silently
    # building against whatever repository the host happens to have.
    grep -q 'file:///home/builder/repo-src' "$ctx/profile/pacman.conf" ||
        die "profile/pacman.conf has no container repo-src Server line to rewrite"
    sed -i "s#file:///home/builder/repo-src#file://$ctx/repo-src#" "$ctx/profile/pacman.conf"
    pin_pacman_conf

    mkdir -p -- "$ctx/profile/airootfs/srv/repo"
    cp -a -- "$repo/." "$ctx/profile/airootfs/srv/repo/"

    find "$ctx/profile" -type d -exec chmod 0755 {} +
    find "$ctx/profile" -type f -exec chmod 0644 {} +
    chmod 0755 -- "$ctx/profile/airootfs/root/customize_airootfs.sh"
    if [ -f "$ctx/profile/airootfs/etc/shadow" ]; then chmod 0600 -- "$ctx/profile/airootfs/etc/shadow"; fi
}

# pin_pacman_conf
# Pins the STAGED profile pacman.conf (never any file under /etc) to the archive snapshot.
#
# WHY: mkarchiso runs pacstrap with the profile's pacman.conf, whose [core]/[extra]
# entries Include the HOST's /etc/pacman.d/mirrorlist - on a rolling build host that
# resolves to current mirrors, so the ISO got newer packages than the snapshot that
# docs/VERSIONS.md and install-verify's snapshot check promise (linux-api-headers 7.3-1
# instead of 7.2-1). Every uncommented mirrorlist Include is therefore replaced by the
# archive Server line, which is the same URL iso/build_iso.sh's container uses.
#
# CacheDir: pacstrap is invoked with -c (use the HOST package cache), and the cache is
# keyed by file name, so a leftover file on the host with the same name could be taken
# instead of the snapshot's package. A dedicated, freshly created cache inside the
# scratch dir removes that dependency (cost: packages are downloaded on every run).
#
# Fails loudly if the profile has no mirrorlist Include to replace, because that would
# mean the pin silently did nothing.
pin_pacman_conf() {
    local conf="$HOST_BUILD_DIR/ctx/profile/pacman.conf" cache="$HOST_BUILD_DIR/pkgcache" n
    [[ "$ARCH_ARCHIVE_DATE" =~ ^[0-9]{4}/[0-9]{2}/[0-9]{2}$ ]] || die "invalid ARCH_ARCHIVE_DATE"
    n="$(grep -c '^[[:space:]]*Include[[:space:]]*=[[:space:]]*/etc/pacman.d/mirrorlist' "$conf" || true)"
    [ "$n" -gt 0 ] || die "profile/pacman.conf has no mirrorlist Include to pin to the archive"
    # '$repo' and '$arch' are pacman's own placeholders and must stay literal.
    sed -i "s#^[[:space:]]*Include[[:space:]]*=[[:space:]]*/etc/pacman.d/mirrorlist.*#Server = https://archive.archlinux.org/repos/${ARCH_ARCHIVE_DATE}/\$repo/os/\$arch#" "$conf"
    grep -q '^\[options\]' "$conf" || die "profile/pacman.conf has no [options] section"
    mkdir -p -- "$cache"
    sed -i "/^\[options\]/a CacheDir = $cache/" "$conf"
    log "pinned staged pacman.conf to the archive snapshot $ARCH_ARCHIVE_DATE ($n repositories)"
}

# trust_repo_key
# Imports the repository key into the host keyring and locally signs it (the profile
# pacman.conf demands SigLevel = Required).
trust_repo_key() {
    local pub="$HOST_BUILD_DIR/ctx/repo-src/$DISTRO_NAME.pub" fpr
    fpr="$(gpg --batch --show-keys --with-colons "$pub" | awk -F: '$1=="fpr"{print $10; exit}')"
    [[ "$fpr" =~ ^[0-9A-Fa-f]{40}$ ]] || die "could not read a key fingerprint from $DISTRO_NAME.pub"
    log "trusting repository key $fpr"
    pacman-key --add "$pub"
    pacman-key --lsign-key "$fpr"
}

# purge_pacman_cache
# MANDATORY: see header step 3.
purge_pacman_cache() {
    log "purging stale /var/cache/pacman/pkg/${DISTRO_NAME}-* packages"
    rm -f -- /var/cache/pacman/pkg/"${DISTRO_NAME}"-*.pkg.tar.zst*
}

main() {
    [ "$#" -eq 0 ] || die "usage: build_iso_host.sh (configuration comes from the environment)"
    SECONDS=0
    load_config
    check_host
    fresh_dir
    stage_profile
    trust_repo_key
    purge_pacman_cache

    (
        cd -- "$HOST_BUILD_DIR/ctx"
        mkdir -p work out
        log "running mkarchiso (SOURCE_DATE_EPOCH=$SOURCE_DATE_EPOCH); this takes a long time"
        mkarchiso -v -w work -o out profile
    )

    local -a built=()
    mapfile -t built < <(find "$HOST_BUILD_DIR/ctx/out" -maxdepth 1 -name '*.iso' -type f)
    [ "${#built[@]}" -eq 1 ] || die "expected exactly one ISO in out/, found ${#built[@]}"

    mkdir -p -- "$ISO_BUILD_DIR"
    rm -f -- "$ISO_BUILD_DIR"/*.iso
    cp -- "${built[0]}" "$ISO_BUILD_DIR/"
    local copy a b
    copy="$ISO_BUILD_DIR/$(basename -- "${built[0]}")"
    a="$(sha256sum <"${built[0]}")"
    b="$(sha256sum <"$copy")"
    [ "$a" = "$b" ] || die "checksum of the copied ISO differs from mkarchiso's output"

    log "done in ${SECONDS}s: $copy (sha256 ${a%% *})"
}

# Run main only when executed, so the pure parts can be sourced by tests.
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
    main "$@"
fi
