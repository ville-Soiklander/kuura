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

# pkgbuild_field PKGBUILD_PATH FIELD
# Prints one field of a PKGBUILD: FIELD "pkgname" prints the single package
# name, FIELD "depends" prints one dependency per line (empty if none).
# Reads the file by sourcing it in a clean subshell with DISTRO_NAME already
# exported (pkgname needs it) -- safe because a PKGBUILD's top level is only
# variable assignments and function definitions; build() and package() are
# never invoked just by sourcing. This is the same technique makepkg itself
# uses to introspect a PKGBUILD (e.g. --printsrcinfo).
pkgbuild_field() {
    local pkgbuild="$1" field="$2"
    (
        # shellcheck disable=SC1090
        source "$pkgbuild"
        case "$field" in
            pkgname) printf '%s\n' "$pkgname" ;;
            depends) printf '%s\n' "${depends[@]-}" ;;
            *) die "pkgbuild_field: unknown field '$field'" ;;
        esac
    )
}

# order_packages
# Prints packages/*/PKGBUILD paths in dependency order: if package A's
# `depends` names package B's pkgname and B is one of this monorepo's own
# packages too, B is printed before A. This matters because
# `makepkg --syncdeps` can only resolve a dependency that is already
# installed or sits in a configured repository -- a sibling package this
# same run has not built and installed yet (see build_package's `pacman -U`
# step below) is neither, so building in the wrong order fails outright, as
# plain alphabetical order first did once kuura-desktop started depending on
# kuura-shell (both built from this monorepo). A cycle between local
# packages is a configuration error and aborts the build rather than being
# silently ignored.
order_packages() {
    local -a pkgbuilds=("$PACKAGES_DIR"/*/PKGBUILD)
    local -A name_of=() deps_of=()
    local pkgbuild pkgbuild2 name dep

    for pkgbuild in "${pkgbuilds[@]}"; do
        name_of["$pkgbuild"]="$(pkgbuild_field "$pkgbuild" pkgname)"
    done

    for pkgbuild in "${pkgbuilds[@]}"; do
        name="${name_of[$pkgbuild]}"
        deps_of["$name"]=""
        while IFS= read -r dep; do
            [ -n "$dep" ] || continue
            for pkgbuild2 in "${pkgbuilds[@]}"; do
                [ "${name_of[$pkgbuild2]}" = "$dep" ] && deps_of["$name"]+="$dep "
            done
        done < <(pkgbuild_field "$pkgbuild" depends)
    done

    # Kahn's algorithm: repeatedly emit any not-yet-emitted package whose
    # local dependencies have all been emitted already; no progress in a
    # full pass over what remains means a cycle.
    local -a ordered_names=() remaining=("${pkgbuilds[@]}") still_remaining
    local progress dep_ok d
    while [ "${#remaining[@]}" -gt 0 ]; do
        progress=0
        still_remaining=()
        for pkgbuild in "${remaining[@]}"; do
            name="${name_of[$pkgbuild]}"
            dep_ok=1
            for d in ${deps_of[$name]}; do
                printf '%s\n' "${ordered_names[@]-}" | grep -qxF "$d" || dep_ok=0
            done
            if [ "$dep_ok" -eq 1 ]; then
                ordered_names+=("$name")
                printf '%s\n' "$pkgbuild"
                progress=1
            else
                still_remaining+=("$pkgbuild")
            fi
        done
        remaining=("${still_remaining[@]}")
        [ "$progress" -eq 1 ] || die "circular local package dependency among: ${remaining[*]}"
    done
}

# build_package PKGBUILD_PATH FINGERPRINT
# Builds and signs one package. --syncdeps installs the build and runtime
# dependencies from the pinned archive, --noconfirm keeps it non-interactive.
# PKGDEST makes makepkg drop the finished package next to the repository database
# instead of into the source directory. Then installs the just-built package
# into this build container with `pacman -U` -- not just leaving it as a file
# in $ARCH_DIR -- so that a LATER package this same run whose `depends` names
# this one (order_packages guarantees such a package is built after this one)
# finds it already satisfied: `--syncdeps` only ever consults a configured
# repository or the currently installed set, and a sibling's file sitting in
# $ARCH_DIR is neither until create_repository assembles the signed repository
# at the very end, for the OUTSIDE consumer, not this container. Installing
# here is a build-time-only convenience; the container is discarded after the
# build, so it never reaches a real machine.
build_package() {
    local pkgbuild="$1" fpr="$2" pkgdir
    pkgdir="$(dirname -- "$pkgbuild")"
    log "building $(basename -- "$pkgdir")"

    lint_pkgbuild "$pkgbuild" || die "namcap reported errors for $pkgbuild"
    (
        cd -- "$pkgdir"
        PKGDEST="$ARCH_DIR" makepkg --syncdeps --noconfirm --sign --key "$fpr"
    )

    # --packagelist prints every file makepkg COULD produce for this PKGBUILD,
    # including a "-debug" package name even when arch='any'/no ELF binaries mean
    # none is ever actually written -- filter to files that really exist. Signature
    # verification is switched off for this one call (see main()'s SigLevel
    # override): the package was just signed with a throwaway per-build key that
    # was never published anywhere, so pacman cannot look it up to trust it, and
    # there is nothing to verify anyway -- this container built the file itself,
    # moments ago, in the same process tree.
    local -a pkgfiles=() existing_pkgfiles=()
    local f
    mapfile -t pkgfiles < <(cd -- "$pkgdir" && PKGDEST="$ARCH_DIR" makepkg --packagelist)
    for f in "${pkgfiles[@]}"; do
        [ -f "$f" ] && existing_pkgfiles+=("$f")
    done
    sudo pacman -U --config "$LOCAL_INSTALL_PACMAN_CONF" --noconfirm "${existing_pkgfiles[@]}"
}

# build_all_packages FINGERPRINT
# Builds every packages/*/PKGBUILD in dependency order (order_packages), then
# lints each result. Fails if there is nothing to build, because an empty
# repository is never intended.
build_all_packages() {
    local fpr="$1" pkgbuild pkgfile
    local -a pkgbuilds=()

    shopt -s nullglob
    pkgbuilds=("$PACKAGES_DIR"/*/PKGBUILD)
    [ "${#pkgbuilds[@]}" -gt 0 ] || die "no packages/*/PKGBUILD found"

    while IFS= read -r pkgbuild; do
        build_package "$pkgbuild" "$fpr"
    done < <(order_packages)

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

    # build_package installs each package into THIS container as it is built (see
    # its own comment for why), by file with `pacman -U`, not from a repository.
    # The default SigLevel would make that fail: the file was just signed with the
    # throwaway key above, which was never published anywhere, so pacman cannot
    # look it up to trust it even though this container built the file itself,
    # moments ago. A SEPARATE pacman.conf with signature checking turned off is
    # used only for that one `pacman -U` call (see build_package) -- /etc/pacman.conf
    # itself is left untouched, so `--syncdeps` still verifies every OFFICIAL
    # package it pulls from the pinned Arch archive with the real keyring; loosening
    # that too, even for this disposable container, would be a much bigger and
    # unrelated drop in the supply-chain guarantee this project otherwise keeps.
    # `pacman -U`'s signature check turned out (confirmed by inspecting the built
    # image's own /etc/pacman.conf) to be governed by the separate
    # LocalFileSigLevel directive, already uncommented at "Optional": verify a
    # signature IF one is present, and makepkg --sign always writes one -- not by
    # the generic SigLevel line above it, which only applies when that more
    # specific line is absent. Both already-uncommented lines are targeted by
    # their exact directive name so nothing else in the file (such as a
    # commented-out example repository further down that happens to contain the
    # substring "SigLevel" too) is touched.
    LOCAL_INSTALL_PACMAN_CONF="$(mktemp)"
    sed -e 's/^SigLevel[[:space:]]*=.*/SigLevel = Never/' \
        -e 's/^LocalFileSigLevel[[:space:]]*=.*/LocalFileSigLevel = Never/' \
        /etc/pacman.conf > "$LOCAL_INSTALL_PACMAN_CONF"
    export LOCAL_INSTALL_PACMAN_CONF

    build_all_packages "$fpr"
    create_repository "$fpr"

    install -m 0644 -- "$pubkey_tmp/$DISTRO_NAME.pub" "$OUT_DIR/$DISTRO_NAME.pub"
    rm -rf -- "$pubkey_tmp"

    log "repository ready:"
    ls -l -- "$ARCH_DIR" "$OUT_DIR/$DISTRO_NAME.pub" >&2
}

main "$@"
