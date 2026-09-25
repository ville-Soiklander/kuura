#!/usr/bin/env bash
# build_repo.sh - build every package and assemble a signed pacman repository.
#
# Runs INSIDE the build container as the unprivileged user "builder" (makepkg
# refuses to run as root). The Makefile creates the container, runs this script
# and copies the finished repository out of the container.
#
# Environment (passed in by the Makefile, see .env.example):
#   DISTRO_NAME         Codename used in package and repository names (required).
#   ARCH_ARCHIVE_DATE   Arch Linux Archive snapshot, YYYY/MM/DD (required).
#   GPG_KEY_ID          Existing signing key; empty means "generate a throwaway key".
#   SOURCE_DATE_EPOCH   Optional fixed build timestamp for reproducible packages.
#
# Result (inside the container, relative to the home directory of the user):
#   repo/x86_64/<package>.pkg.tar.zst (+ .sig)
#   repo/x86_64/<DISTRO_NAME>.db.tar.zst (+ .sig, .files.tar.zst, plain .db links)
#   repo/<DISTRO_NAME>.pub            public signing key

set -euo pipefail
# Without this, bash silently disables `set -e` inside $(...) command substitutions.
shopt -s inherit_errexit

# All paths are derived from the location of this script, so nothing is hard coded.
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
PACKAGES_DIR="$PROJECT_DIR/packages"
OUT_DIR="$PROJECT_DIR/repo"
ARCH_DIR="$OUT_DIR/x86_64"

# log MESSAGE...
# Prints a progress line to stderr so that it is visible in the container log.
log() {
    printf 'build_repo.sh: %s\n' "$*" >&2
}

# die MESSAGE...
# Prints an error and aborts the build with a non-zero status.
die() {
    log "error: $*"
    exit 1
}

# validate_config
# Checks the required environment variables. Both values end up in package names,
# file names or URLs, so they are validated strictly instead of being trusted.
validate_config() {
    [ -n "${DISTRO_NAME:-}" ] || die "DISTRO_NAME is not set"
    [ -n "${ARCH_ARCHIVE_DATE:-}" ] || die "ARCH_ARCHIVE_DATE is not set"

    # Lowercase letters, digits, "_" and "-" are valid in pacman package names.
    [[ "$DISTRO_NAME" =~ ^[a-z0-9][a-z0-9_-]*$ ]] \
        || die "DISTRO_NAME may only contain lowercase letters, digits, '_' and '-'"
    [[ "$ARCH_ARCHIVE_DATE" =~ ^[0-9]{4}/[0-9]{2}/[0-9]{2}$ ]] \
        || die "ARCH_ARCHIVE_DATE must have the form YYYY/MM/DD"

    # PKGBUILDs read the distribution name from the environment.
    export DISTRO_NAME
}

# set_source_date_epoch
# Exports SOURCE_DATE_EPOCH, which makepkg uses for file timestamps and the build
# date inside the package. An explicit value from the environment wins; otherwise
# midnight UTC of the archive date is used, so the timestamp is fixed by the
# configuration and does not depend on when the build happens to run.
set_source_date_epoch() {
    if [ -z "${SOURCE_DATE_EPOCH:-}" ]; then
        SOURCE_DATE_EPOCH="$(date -u -d "${ARCH_ARCHIVE_DATE//\//-} 00:00:00" +%s)"
    fi
    [[ "$SOURCE_DATE_EPOCH" =~ ^[0-9]+$ ]] || die "SOURCE_DATE_EPOCH must be an integer"
    export SOURCE_DATE_EPOCH
    log "SOURCE_DATE_EPOCH=$SOURCE_DATE_EPOCH"
}

# stop_gpg_agent
# Stops the gpg-agent that gpg started in the background. It holds the (possibly
# throwaway) private key in memory and would otherwise outlive the build.
stop_gpg_agent() {
    gpgconf --kill gpg-agent >/dev/null 2>&1 || true
}

# lint_with_namcap TARGET
# Runs namcap on a PKGBUILD or a built package and returns non-zero if it reports
# an error. Warnings are shown but tolerated: the contract only forbids errors.
# Two forms count as errors: rule findings ("E:") and problems that prevent the
# analysis itself ("Error: ..."). namcap exits with 0 in both cases, so the exit
# status is useless here and the output has to be inspected; without the second
# form an unparsable PKGBUILD would silently pass the check.
lint_with_namcap() {
    local report
    report="$(namcap "$1" 2>&1)" || true
    [ -z "$report" ] || printf '%s\n' "$report" >&2
    if grep -Eq '^Error:| E: ' <<<"$report"; then
        return 1
    fi
}

# lint_pkgbuild PKGBUILD_PATH
# Lints a PKGBUILD with namcap. namcap parses the file in a restricted shell with an
# EMPTY environment (env -i), so DISTRO_NAME, which the PKGBUILD requires, would be
# missing and the file would be reported as invalid. A temporary copy that starts
# with the variable assignment is linted instead; the PKGBUILD itself stays as is.
# Line numbers in namcap messages are therefore shifted down by one.
lint_pkgbuild() {
    local pkgbuild="$1" tmp rc=0
    tmp="$(mktemp -d)"
    { printf 'DISTRO_NAME=%q\n' "$DISTRO_NAME"; cat -- "$pkgbuild"; } > "$tmp/PKGBUILD"
    lint_with_namcap "$tmp/PKGBUILD" || rc=$?
    rm -rf -- "$tmp"
    return "$rc"
}

# build_package PKGBUILD_PATH FINGERPRINT
# Builds and signs one package. --syncdeps installs the build and runtime
# dependencies from the pinned archive, --noconfirm keeps it non-interactive.
# PKGDEST makes makepkg drop the finished package next to the repository database
# instead of into the source directory.
build_package() {
    local pkgbuild="$1" fpr="$2" pkgdir
    pkgdir="$(dirname -- "$pkgbuild")"
    log "building $(basename -- "$pkgdir")"

    lint_pkgbuild "$pkgbuild" || die "namcap reported errors for $pkgbuild"
    (
        cd -- "$pkgdir"
        PKGDEST="$ARCH_DIR" makepkg --syncdeps --noconfirm --sign --key "$fpr"
    )
}

# build_all_packages FINGERPRINT
# Builds every packages/*/PKGBUILD in alphabetical order, then lints each result.
# Fails if there is nothing to build, because an empty repository is never intended.
build_all_packages() {
    local fpr="$1" pkgbuild pkgfile
    local -a pkgbuilds=()

    shopt -s nullglob
    pkgbuilds=("$PACKAGES_DIR"/*/PKGBUILD)
    [ "${#pkgbuilds[@]}" -gt 0 ] || die "no packages/*/PKGBUILD found"

    for pkgbuild in "${pkgbuilds[@]}"; do
        build_package "$pkgbuild" "$fpr"
    done

    for pkgfile in "$ARCH_DIR"/*.pkg.tar.zst; do
        lint_with_namcap "$pkgfile" || die "namcap reported errors for $pkgfile"
    done
}

# create_repository FINGERPRINT
# Creates the signed repository database from the built packages. repo-add --sign
# signs the database files, so pacman can enforce SigLevel = Required for them.
# The glob does not match the .sig files because they do not end in .pkg.tar.zst.
create_repository() {
    local fpr="$1"
    local -a packages=("$ARCH_DIR"/*.pkg.tar.zst)
    [ "${#packages[@]}" -gt 0 ] || die "no built packages found in $ARCH_DIR"

    log "creating repository database $DISTRO_NAME.db.tar.zst"
    repo-add --sign --key "$fpr" "$ARCH_DIR/$DISTRO_NAME.db.tar.zst" "${packages[@]}"
}

# main
# Orchestrates the build: validate, sign setup, build, repository, public key.
main() {
    validate_config
    set_source_date_epoch

    # sign.sh and makepkg/repo-add must use the same GnuPG home, so it is exported
    # here once instead of being decided separately by each of them.
    export GNUPGHOME="${GNUPGHOME:-$HOME/.gnupg}"
    trap stop_gpg_agent EXIT

    # Start from an empty output directory so nothing stale ends up in the result.
    rm -rf -- "$OUT_DIR"
    mkdir -p -- "$ARCH_DIR"

    # sign.sh prints the fingerprint on stdout and writes the public key to a file
    # outside the output tree; it is copied to the repository root at the end.
    local pubkey_tmp fpr
    pubkey_tmp="$(mktemp -d)"
    fpr="$("$SCRIPT_DIR/sign.sh" "$pubkey_tmp/$DISTRO_NAME.pub")"
    log "using signing key $fpr"

    build_all_packages "$fpr"
    create_repository "$fpr"

    install -m 0644 -- "$pubkey_tmp/$DISTRO_NAME.pub" "$OUT_DIR/$DISTRO_NAME.pub"
    rm -rf -- "$pubkey_tmp"

    log "repository ready:"
    ls -l -- "$ARCH_DIR" "$OUT_DIR/$DISTRO_NAME.pub" >&2
}

main "$@"
