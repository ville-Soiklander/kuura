#!/usr/bin/env bash
# sign.sh - prepare the signing key for the package build and export its public half.
#
# Usage:
#   sign.sh <public-key-output-file>
#
# Environment:
#   GPG_KEY_ID   Fingerprint (or key ID) of an existing secret key in GNUPGHOME.
#                Empty or unset: a passphrase-less throwaway key is generated.
#   GNUPGHOME    GnuPG home directory. Default: $HOME/.gnupg
#   DISTRO_NAME  Only used to label a generated throwaway key.
#
# Output:
#   stdout       The full fingerprint of the signing key and nothing else, so that
#                the caller can capture it with $(...). All messages go to stderr.
#
# The private key stays inside GNUPGHOME. This script never exports it and refuses
# to create a throwaway key outside the caller's home directory, so a key can not
# end up in a repository checkout or a bind-mounted path by accident.

set -euo pipefail
# Without this, bash silently disables `set -e` inside $(...) command substitutions.
shopt -s inherit_errexit

# log MESSAGE...
# Prints a diagnostic line to stderr. stdout is reserved for the fingerprint.
log() {
    printf 'sign.sh: %s\n' "$*" >&2
}

# die MESSAGE...
# Prints an error to stderr and aborts with a non-zero status.
die() {
    log "error: $*"
    exit 1
}

# prepare_gnupg_home
# Makes sure GNUPGHOME exists with mode 700 (GnuPG warns about and may ignore a
# home that other users can read) and exports it for every gpg call below.
prepare_gnupg_home() {
    export GNUPGHOME="${GNUPGHOME:-$HOME/.gnupg}"
    mkdir -p -- "$GNUPGHOME"
    chmod 700 -- "$GNUPGHOME"
}

# assert_home_is_private
# Guard for throwaway keys: the key directory must live under $HOME. A path outside
# of it could point into a mounted project directory, which would leak the private
# key into the repository.
assert_home_is_private() {
    local resolved home
    resolved="$(realpath -m -- "$GNUPGHOME")"
    home="$(realpath -m -- "$HOME")"
    case "$resolved" in
        "$home"/*) ;;
        *) die "refusing to create a throwaway key outside of the home directory" ;;
    esac
}

# fingerprint_of SELECTOR
# Prints the full fingerprint of the primary secret key matching SELECTOR (key ID,
# fingerprint or exact user ID). Prints nothing if there is no such secret key.
# The machine-readable --with-colons format is used because the human-readable
# listing changes between GnuPG versions. `|| true` keeps `set -e` from aborting
# when gpg reports "no such key"; callers check for an empty result themselves.
fingerprint_of() {
    gpg --batch --with-colons --fingerprint --list-secret-keys -- "$1" 2>/dev/null \
        | awk -F: '$1 == "fpr" { print $10; exit }' || true
}

# generate_throwaway_key
# Creates a passphrase-less Ed25519 signing key that is valid for one year and prints
# its fingerprint. Passphrase-less because it must work unattended in a container;
# it is safe because the key only lives as long as the build container and is
# regenerated for every build. The user ID contains no personal data.
generate_throwaway_key() {
    local uid fpr
    uid="${DISTRO_NAME:-dev} throwaway development key"

    assert_home_is_private
    log "generating a throwaway signing key"
    gpg --batch --quiet --pinentry-mode loopback --passphrase '' \
        --quick-generate-key "$uid" ed25519 sign 1y >&2

    # "=" makes the user ID match exact, so no other key can be picked up.
    fpr="$(fingerprint_of "=$uid")"
    [ -n "$fpr" ] || die "could not read back the generated key"
    printf '%s\n' "$fpr"
}

# use_existing_key SELECTOR
# Verifies that SELECTOR names a secret key in GNUPGHOME and prints its full
# fingerprint. The selector is checked against a hex pattern first so that a value
# like "--foo" can never be interpreted as a gpg option.
use_existing_key() {
    local selector="$1" fpr
    [[ "$selector" =~ ^[0-9A-Fa-f]{8,40}$ ]] \
        || die "GPG_KEY_ID must be a hexadecimal key ID or fingerprint"

    fpr="$(fingerprint_of "$selector")"
    [ -n "$fpr" ] || die "no secret key for GPG_KEY_ID found in GNUPGHOME"
    printf '%s\n' "$fpr"
}

# export_public_key FINGERPRINT OUTPUT_FILE
# Writes the ASCII-armored PUBLIC key to OUTPUT_FILE (parent directories are created).
# Only --export is used, never --export-secret-keys. An empty result is treated as
# an error because an empty key file would silently break trust setup later on.
export_public_key() {
    local fpr="$1" out="$2"
    mkdir -p -- "$(dirname -- "$out")"
    gpg --batch --yes --armor --export "$fpr" > "$out"
    [ -s "$out" ] || die "public key export produced an empty file"
}

# main OUTPUT_FILE
# Entry point: sets up GNUPGHOME, picks or creates the key, exports the public key
# and prints the fingerprint on stdout.
main() {
    [ "$#" -eq 1 ] && [ -n "$1" ] || die "usage: sign.sh <public-key-output-file>"
    local out="$1" fpr

    prepare_gnupg_home

    if [ -z "${GPG_KEY_ID:-}" ]; then
        fpr="$(generate_throwaway_key)"
    else
        fpr="$(use_existing_key "$GPG_KEY_ID")"
    fi

    export_public_key "$fpr" "$out"
    log "signing key fingerprint: $fpr"
    printf '%s\n' "$fpr"
}

main "$@"
