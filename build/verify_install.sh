#!/usr/bin/env bash
# verify_install.sh - prove that the metapackage installs from the signed repository.
#
# Runs on the HOST after `make repo` (see the verify-install target and
# docs/BUILD_CONTRACT.md). Throwaway containers are started, one after the other,
# from the pristine Arch base image, each with a repository bind-mounted READ-ONLY:
#
#   1. Positive test: trust the repository key, enable the repository with
#      SigLevel = Required DatabaseRequired, run a full upgrade, install
#      <DISTRO_NAME>-desktop and assert that the installed system is complete.
#   2. Negative tests: repeat the setup against a COPY of the repository in which the
#      package file was damaged after it was signed. The install must be refused.
#      This proves that verification is really enforced, so the positive test can
#      not be passing merely because signature checking is switched off. Two copies
#      are used: one byte APPENDED to the package (caught by pacman's size limit
#      while downloading) and a DAMAGED SIGNATURE next to an intact package (size
#      and checksum match, so only the signature check can reject it).
#
# Environment (exported by the Makefile, see .env.example):
#   DISTRO_NAME         Codename; the package under test is <DISTRO_NAME>-desktop.
#   CONTAINER_ENGINE    podman or docker.
#   ARCH_ARCHIVE_DATE   Arch Linux Archive snapshot, YYYY/MM/DD (same as the build).
#   REPO_DIR            Repository directory relative to the project root; the
#                       packages are in REPO_DIR/x86_64, the key in
#                       REPO_DIR/<DISTRO_NAME>.pub.
#   GPG_KEY_ID          Optional. If set, the repository key must match it.
#
# Exit status: 0 only if every step and assertion succeeded; the last line on stdout
# is then "verify-install: OK". The script writes nothing outside a temporary
# directory (removed on every exit path) and the containers, which are removed too.

set -euo pipefail
# Without this, bash silently disables `set -e` inside $(...) command substitutions.
shopt -s inherit_errexit

# Fully qualified so that no unqualified-search registry list can change the image.
BASE_IMAGE="docker.io/library/archlinux:base"

# Where the repository directory appears inside the containers.
REPO_MOUNT="/repo"

# All paths are derived from the location of this script, so nothing is hard coded.
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd -P)"

# Filled in by locate_repository / prepare_tampered_repo.
REPO_ABS=""     # resolved repository directory (contains x86_64/ and the .pub file)
PKG_FILE=""     # file name of the metapackage inside x86_64/
TMP_DIR=""      # scratch directory holding the tampered copy; removed by cleanup

# log MESSAGE...
# Prints a progress line to stderr so that it stays visible next to the container log.
log() {
    printf 'verify_install.sh: %s\n' "$*" >&2
}

# die MESSAGE...
# Prints an error and aborts with a non-zero status.
die() {
    log "error: $*"
    exit 1
}

# cleanup
# EXIT trap: removes the scratch directory. It runs on success, on the first failure
# (set -e) and on interruption, so the tampered package never outlives the script.
# The containers need no cleanup here: they are started with --rm.
cleanup() {
    if [ -n "$TMP_DIR" ]; then
        rm -rf -- "$TMP_DIR"
    fi
}

# validate_config
# Checks the environment with the same rules as the Makefile and build_repo.sh.
# The values end up in package names, URLs and a bind-mount path, so they are
# validated strictly instead of being trusted. Also makes GPG_KEY_ID defined
# (possibly empty) and exports every value that is handed on to the containers.
validate_config() {
    [ -n "${DISTRO_NAME:-}" ] || die "DISTRO_NAME is not set"
    [ -n "${CONTAINER_ENGINE:-}" ] || die "CONTAINER_ENGINE is not set; use podman or docker"
    [ -n "${ARCH_ARCHIVE_DATE:-}" ] || die "ARCH_ARCHIVE_DATE is not set"
    [ -n "${REPO_DIR:-}" ] || die "REPO_DIR is not set"
    GPG_KEY_ID="${GPG_KEY_ID:-}"

    # Lowercase letters, digits, "_" and "-" are valid in pacman package names.
    [[ "$DISTRO_NAME" =~ ^[a-z0-9][a-z0-9_-]*$ ]] \
        || die "DISTRO_NAME may only contain lowercase letters, digits, '_' and '-'"
    [[ "$ARCH_ARCHIVE_DATE" =~ ^[0-9]{4}/[0-9]{2}/[0-9]{2}$ ]] \
        || die "ARCH_ARCHIVE_DATE must have the form YYYY/MM/DD"
    case "$CONTAINER_ENGINE" in
        podman | docker) ;;
        *) die "CONTAINER_ENGINE must be podman or docker" ;;
    esac
    case "$REPO_DIR" in
        . | .. | /* | ../* | */.. | */../*)
            die "REPO_DIR must be a relative path inside the project" ;;
    esac
    # Same pattern that sign.sh applies to the selector of the signing key.
    [ -z "$GPG_KEY_ID" ] || [[ "$GPG_KEY_ID" =~ ^[0-9A-Fa-f]{8,40}$ ]] \
        || die "GPG_KEY_ID must be empty or a hexadecimal key ID or fingerprint"

    command -v "$CONTAINER_ENGINE" >/dev/null 2>&1 \
        || die "container engine '$CONTAINER_ENGINE' not found in PATH"

    # Handed to the containers by name (--env NAME), never by value on a command line.
    export DISTRO_NAME ARCH_ARCHIVE_DATE GPG_KEY_ID REPO_MOUNT
}

# locate_repository
# Verifies that `make repo` left a complete repository and remembers where it is.
# Everything the containers rely on is checked here so that a missing file produces
# one clear message instead of an obscure pacman error several minutes into a run.
locate_repository() {
    local dir="$PROJECT_DIR/$REPO_DIR" arch_dir f
    local -a packages=()

    [ -d "$dir" ] || die "repository directory '$REPO_DIR' does not exist; run 'make repo' first"
    REPO_ABS="$(realpath -- "$dir")"

    # -v SRC:DST:OPTIONS uses ':' as the separator, so a path with one can not be mounted.
    case "$REPO_ABS" in
        *:*) die "the repository path contains ':' and can not be bind-mounted" ;;
    esac

    arch_dir="$REPO_ABS/x86_64"
    [ -d "$arch_dir" ] || die "'$REPO_DIR/x86_64' does not exist; run 'make repo' first"

    # SigLevel = Required DatabaseRequired needs the database and its signature.
    for f in "$DISTRO_NAME.db.tar.zst" "$DISTRO_NAME.db.tar.zst.sig"; do
        [ -f "$arch_dir/$f" ] || die "'$REPO_DIR/x86_64/$f' is missing; run 'make repo' first"
    done

    [ -s "$REPO_ABS/$DISTRO_NAME.pub" ] \
        || die "public key '$REPO_DIR/$DISTRO_NAME.pub' is missing or empty; run 'make repo' first"

    # The version number is unknown here, hence the glob. [0-9]* keeps a package
    # such as <DISTRO_NAME>-desktop-extras out of the match.
    shopt -s nullglob
    packages=("$arch_dir/$DISTRO_NAME-desktop"-[0-9]*.pkg.tar.zst)
    shopt -u nullglob
    [ "${#packages[@]}" -eq 1 ] \
        || die "expected exactly one $DISTRO_NAME-desktop package in '$REPO_DIR/x86_64', found ${#packages[@]}"
    PKG_FILE="$(basename -- "${packages[0]}")"
    [ -f "${packages[0]}.sig" ] || die "signature '$REPO_DIR/x86_64/$PKG_FILE.sig' is missing"
}

# In-container scripts. They are FIXED text: no host value is ever interpolated into
# them. The values they need (DISTRO_NAME, ARCH_ARCHIVE_DATE, GPG_KEY_ID, REPO_MOUNT)
# arrive as environment variables, so a hostile value can not become shell code.
# The heredoc delimiters are quoted, which keeps $ and backticks literal here.

# SETUP_SCRIPT: common to both tests. Points pacman at the dated archive snapshot,
# prepares the keyring, trusts the repository key and enables the repository with
# mandatory signatures.
IFS= read -r -d '' SETUP_SCRIPT <<'EOF' || true
set -euo pipefail
shopt -s inherit_errexit

# step MESSAGE / pass MESSAGE / fail MESSAGE: progress and assertion reporting.
# fail stops the container immediately, which fails the whole verification.
step() { printf '==> %s\n' "$*"; }
pass() { printf 'PASS: %s\n' "$*"; }
fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }

meta="$DISTRO_NAME-desktop"
key_file="$REPO_MOUNT/$DISTRO_NAME.pub"

# Same snapshot as the build image, so the installed versions are the frozen ones.
# $repo and $arch stay literal: pacman expands them itself for every repository.
step "pointing pacman at the archive snapshot $ARCH_ARCHIVE_DATE"
printf 'Server = https://archive.archlinux.org/repos/%s/$repo/os/$arch\n' \
    "$ARCH_ARCHIVE_DATE" > /etc/pacman.d/mirrorlist

step "initialising the pacman keyring"
pacman-key --init
pacman-key --populate archlinux

# The fingerprint is read from the key file itself (machine-readable format, because
# the human-readable listing changes between GnuPG versions). Exactly one primary key
# is required so that the key that gets locally signed is the one that was inspected.
step "reading the fingerprint of the repository key"
keyinfo="$(gpg --batch --show-keys --with-colons -- "$key_file")"
key_count="$(awk -F: '$1 == "pub" { n++ } END { print n + 0 }' <<<"$keyinfo")"
[ "$key_count" -eq 1 ] || fail "the repository key file must contain exactly one key, found $key_count"
key_fpr="$(awk -F: '$1 == "fpr" && !seen { print $10; seen = 1 }' <<<"$keyinfo")"
[[ "$key_fpr" =~ ^[0-9A-F]{40}$ ]] || fail "could not read a 40-digit fingerprint from the key file"

# If the configuration names a signing key, the repository must be signed with it;
# otherwise a repository built with a different key would be trusted blindly.
# Primary key and subkeys are accepted because GPG_KEY_ID may name either.
if [ -n "${GPG_KEY_ID:-}" ]; then
    matched=0
    while IFS= read -r candidate; do
        if [[ "${candidate^^}" == *"${GPG_KEY_ID^^}" ]]; then
            matched=1
        fi
    done < <(awk -F: '$1 == "fpr" { print $10 }' <<<"$keyinfo")
    [ "$matched" -eq 1 ] || fail "the repository key does not match GPG_KEY_ID"
fi

step "trusting the repository key $key_fpr"
pacman-key --add "$key_file"
pacman-key --lsign-key "$key_fpr"

# pacman reads a file:// repository as its unprivileged download user ("alpm"), which
# can not enter a mounted host directory that is only accessible to its owner (mode
# 0700, e.g. after a restrictive umask). Root can always read the mount, so the
# repository is copied into the container and made world-readable there. The bytes
# are unchanged, so checksums and signatures are verified exactly as they would be
# on the mount itself.
step "copying the read-only repository mount into the container"
repo_local=/srv/repo
mkdir -p -- "$repo_local"
cp -a -- "$REPO_MOUNT/." "$repo_local/"
chmod -R a+rX -- "$repo_local"

# Required = a valid signature from a trusted key is mandatory for packages and,
# with DatabaseRequired, for the repository database. Appended last: the order only
# matters for package name clashes and the metapackage name is unique.
step "enabling the repository with SigLevel = Required DatabaseRequired"
printf '\n[%s]\nSigLevel = Required DatabaseRequired\nServer = file://%s/x86_64\n' \
    "$DISTRO_NAME" "$repo_local" >> /etc/pacman.conf

# Refresh the keyring first (as the build image does): packages in the snapshot may
# be signed by keys that the base image does not know yet. This also downloads the
# repository database, so its signature is verified here already.
step "refreshing the archive keyring and the repository databases"
pacman -Sy --noconfirm --noprogressbar archlinux-keyring
EOF

# INSTALL_SCRIPT: positive test. Runs after SETUP_SCRIPT in the same container.
IFS= read -r -d '' INSTALL_SCRIPT <<'EOF' || true

# depends_of PACKAGE
# Prints the "Depends On" field of an INSTALLED package, one line per source line.
# Long lists may be wrapped over several lines that start with blanks, so the
# continuation lines are collected as well. Prints "None" for an empty list.
depends_of() {
    pacman -Qi -- "$1" | awk '
        /^[^ ].* : / { in_field = ($0 ~ /^Depends On +:/); if (in_field) { sub(/^[^:]*: */, ""); print }; next }
        in_field { print }
    '
}

# -Syuu: the second -u also permits downgrades, so the result matches the snapshot
# exactly even when the base image is newer than the snapshot.
step "full system upgrade"
pacman -Syuu --noconfirm --noprogressbar

step "installing $meta"
pacman -S --noconfirm --noprogressbar -- "$meta"

# Informational: the cache of a fresh container holds exactly what was downloaded.
cache_size="$(du -sh /var/cache/pacman/pkg | cut -f1)"
cache_files="$(find /var/cache/pacman/pkg -maxdepth 1 -name '*.pkg.tar.*' -not -name '*.sig' | wc -l)"
step "downloaded during this run: $cache_size in $cache_files package files"

step "assertions"

if pacman -Q -- "$meta" >/dev/null; then
    pass "$meta is installed"
else
    fail "$meta is not installed"
fi

# "Validated By: Signature" is recorded by pacman for a package whose signature was
# checked against the trusted keyring while it was installed.
validated_by="$(pacman -Qi -- "$meta" | awk -F' *: ' '$1 ~ /^Validated By/ { print $2 }')"
if [[ "$validated_by" == *Signature* ]]; then
    pass "$meta was validated by signature"
else
    fail "$meta was not validated by signature"
fi

# Every entry of the dependency list must be satisfied. A plain package name is
# checked with -Q; anything else (a provider, a versioned dependency) with -T, which
# applies pacman's own dependency resolution. Version constraints are stripped for -Q.
raw_depends="$(depends_of "$meta")"
mapfile -t depends < <(printf '%s\n' "$raw_depends" | tr -s '[:space:]' '\n')
checked=0
missing=""
for dep in "${depends[@]}"; do
    if [ -z "$dep" ] || [ "$dep" = "None" ]; then
        continue
    fi
    checked=$((checked + 1))
    if ! pacman -Q -- "${dep%%[<>=]*}" >/dev/null 2>&1 && ! pacman -T -- "$dep" >/dev/null 2>&1; then
        missing="$missing $dep"
    fi
done
# An empty list would mean the parsing above broke; the metapackage always has some.
[ "$checked" -gt 0 ] || fail "no dependencies found for $meta"
if [ -z "$missing" ]; then
    pass "all $checked dependencies of $meta are installed"
else
    fail "dependencies of $meta not installed:$missing"
fi

for pkg in sddm kwin plasma-desktop; do
    if pacman -Q -- "$pkg" >/dev/null 2>&1; then
        pass "$pkg is installed"
    else
        fail "$pkg is not installed"
    fi
done

# -Dk checks the local database for missing dependencies and conflicts; it exits
# non-zero and lists the problems if there are any.
if problems="$(pacman -Dk 2>&1)"; then
    pass "pacman -Dk reports no problems"
else
    printf '%s\n' "$problems" >&2
    fail "pacman -Dk reports problems"
fi
EOF

# TAMPER_SCRIPT: negative test. Runs after SETUP_SCRIPT in a fresh container that
# mounts a tampered repository copy. EXPECT_ERROR (an extended regular expression
# chosen by the caller) says which pacman error is the right reason for the refusal.
IFS= read -r -d '' TAMPER_SCRIPT <<'EOF' || true

# -dd skips dependency resolution, so a refusal can only come from the package
# itself and nothing large is downloaded. The output is captured to check the reason.
step "installing the tampered package (must be refused)"
status=0
output="$(pacman -S --noconfirm --noprogressbar -dd -- "$meta" 2>&1)" || status=$?
printf '%s\n' "$output"

[ "$status" -ne 0 ] || fail "the tampered package was installed"
if pacman -Q -- "$meta" >/dev/null 2>&1; then
    fail "$meta is installed although pacman reported an error"
fi

# The failure must be the integrity/signature check. "target not found", a network
# error or an untrusted key would also fail the install, but prove nothing.
reason="$(grep -Ei -- "$EXPECT_ERROR" <<<"$output" | head -n 1 || true)"
[ -n "$reason" ] || fail "the install failed, but not for the expected reason (/$EXPECT_ERROR/)"
pass "tampered package refused: $reason"
EOF

# run_container REPO_DIRECTORY SCRIPT
# Starts a fresh, throwaway container that mounts REPO_DIRECTORY read-only at
# REPO_MOUNT and runs SCRIPT in it (as root inside; with rootless Podman that is the
# calling user on the host). Returns the exit status of the script.
#   --rm                          the container is deleted when it exits.
#   :ro (on the volume)           the repository can not be modified from the inside.
#   --security-opt label=disable  lets the mount be read on SELinux hosts without
#                                 relabelling (and thereby modifying) the host
#                                 directory; it has no effect elsewhere.
#   --env NAME                    copies the value from this script's environment.
run_container() {
    local repo_directory="$1" script="$2"
    "$CONTAINER_ENGINE" run --rm \
        --security-opt label=disable \
        --volume "$repo_directory:$REPO_MOUNT:ro" \
        --env DISTRO_NAME --env ARCH_ARCHIVE_DATE --env GPG_KEY_ID --env REPO_MOUNT \
        --env EXPECT_ERROR \
        --env LC_ALL=C \
        "$BASE_IMAGE" \
        bash -c "$script" verify-install
}

# invert_last_byte FILE
# Inverts the last byte of FILE in place; the size does not change. `%b` with a
# \0NNN escape writes the byte, so nothing from the file is ever used as a format
# string.
invert_last_byte() {
    local file="$1" size last
    size="$(stat -c %s -- "$file")"
    last="$(tail -c 1 -- "$file" | od -An -tu1)"
    printf '%b' "\\0$(printf '%o' "$(( last ^ 255 ))")" \
        | dd of="$file" bs=1 seek="$(( size - 1 ))" conv=notrunc status=none
}

# prepare_tampered_repo MODE
# Copies the repository to $TMP_DIR/MODE and damages the copy after the package was
# signed. The original is never modified. cp -a keeps the mode bits and the database
# symlinks, so the copy is as readable inside the container as the original.
#   append  one byte is added to the end of the package and its signature is kept.
#           pacman refuses this while downloading, because the size no longer
#           matches the database entry; this happens before any signature check.
#   badsig  the package is intact but the last byte of its signature is inverted.
#           Size and checksum still match the (signed) database, so only the
#           signature check can reject the package. This is the case that proves
#           that signatures are enforced.
prepare_tampered_repo() {
    local mode="$1" copy pkg changed
    copy="$TMP_DIR/$mode"
    mkdir -m 0755 -- "$copy"
    cp -a -- "$REPO_ABS/." "$copy/"

    pkg="$copy/x86_64/$PKG_FILE"
    case "$mode" in
        append)
            changed="$pkg"
            printf 'X' >> "$changed"
            ;;
        badsig)
            changed="$pkg.sig"
            invert_last_byte "$changed"
            ;;
        *)
            die "unknown tamper mode '$mode'"
            ;;
    esac

    # Guard against a silent no-op: the damaged file must really differ from the
    # original.
    if cmp -s -- "$changed" "$REPO_ABS/x86_64/${changed##*/}"; then
        die "failed to tamper with the copy of ${changed##*/}"
    fi
}

# run_tamper_test MODE EXPECTED_ERROR DESCRIPTION
# Negative test in a fresh container: installing the package tampered with in MODE
# must be refused with an error that matches the regular expression EXPECTED_ERROR.
run_tamper_test() {
    local mode="$1" description="$3"
    export EXPECT_ERROR="$2"
    log "negative test ($mode): $description"
    prepare_tampered_repo "$mode"
    run_container "$TMP_DIR/$mode" "$SETUP_SCRIPT"$'\n'"$TAMPER_SCRIPT" \
        || die "the tampered-package test ($mode) failed"
}

# main
# Orchestrates the verification: validate, positive test, negative test.
main() {
    [ "$#" -eq 0 ] || die "usage: verify_install.sh (configuration comes from the environment)"

    validate_config
    locate_repository
    trap cleanup EXIT
    # Turn interruption into a normal exit so that the EXIT trap always runs.
    trap 'exit 130' INT TERM HUP

    log "positive test: install $DISTRO_NAME-desktop from '$REPO_DIR' in a fresh container"
    run_container "$REPO_ABS" "$SETUP_SCRIPT"$'\n'"$INSTALL_SCRIPT" \
        || die "the installation test failed"

    TMP_DIR="$(mktemp -d)"
    run_tamper_test append 'exceeded the maximum allowed file size|invalid or corrupted package' \
        "one byte appended to the package must be refused"
    run_tamper_test badsig 'signature from .* is invalid|invalid or corrupted package \(PGP signature\)' \
        "a damaged package signature must be refused by the signature check"

    printf 'verify-install: OK\n'
}

main "$@"
