#!/usr/bin/env bash
# run_mkarchiso.sh - runs INSIDE the iso/Containerfile image as the unprivileged user
# "builder" (see that file's own comment). Trusts kuura's repository key on the
# container's real system keyring (consulted by pacstrap for signature verification -
# see docs/ISO_CONTRACT.md's own research into this), then invokes mkarchiso against
# the staged profile.
#
# MKARCHISO_MODE (set by iso/build_iso.sh):
#   rootless (default) - mkarchiso runs as "builder" (EUID != 0), so its own _unshare
#                         helper wraps every privileged step in
#                         `unshare --map-auto --map-root-user` (confirmed from this
#                         exact pinned mkarchiso's own source - see
#                         docs/ISO_CONTRACT.md's "Rootless build" section). This is
#                         the path the contract expects to work and the one tried
#                         first; nothing here forces it silently to the other mode.
#   root                - mkarchiso runs as root (via sudo) INSIDE this container.
#                         EUID == 0 makes mkarchiso's own _unshare a no-op (it only
#                         wraps calls when EUID != 0), so this exercises a different
#                         code path without needing --privileged on the podman
#                         container itself. Used only as an explicit, logged fallback
#                         if "rootless" is empirically proven not to work in this
#                         podman setup (docs/ISO_CONTRACT.md: "fall back ... only if
#                         that genuinely fails, and say so plainly").
set -euo pipefail

log() { printf 'run_mkarchiso.sh: %s\n' "$*" >&2; }
die() { log "error: $*"; exit 1; }

[ -n "${DISTRO_NAME:-}" ] || die "DISTRO_NAME is not set"
[ -n "${SOURCE_DATE_EPOCH:-}" ] || die "SOURCE_DATE_EPOCH is not set"
export DISTRO_NAME SOURCE_DATE_EPOCH

MODE="${MKARCHISO_MODE:-rootless}"
case "$MODE" in
    rootless | root) ;;
    *) die "MKARCHISO_MODE must be 'rootless' or 'root', got '$MODE'" ;;
esac

# Trust kuura's repository key on THIS container's real system pacman keyring
# (/etc/pacman.d/gnupg). This is the keyring pacstrap actually consults when
# verifying the [@DISTRO_NAME@] repo's packages during the build (pacstrap is
# invoked with -G, "do not copy the host keyring into the target" - the target has
# no keyring of its own yet at that point, so verification happens against the
# CALLING environment's own keyring, exactly as harness/vm/Containerfile's
# near-identical fingerprint-and-trust step already relies on for the same signed
# repository).
#
# `pacman-key --init` is run explicitly first - a real run showed this is actually
# needed here: unlike build/Containerfile and harness/vm/Containerfile (which run
# the equivalent `pacman-key --add`/`--lsign-key` pair during `podman build`'s own
# RUN steps, as real root), this script runs during `podman run` via sudo, and
# `--lsign-key` failed with "There is no secret key available to sign with" because
# this container's /etc/pacman.d/gnupg had no local signing key yet. `--init` is
# the same, idempotent, standard first step a real Arch install's own
# pacman-init.service runs on every boot (see iso/profile's own releng heritage),
# so it is always safe to call again even if already initialised.
sudo pacman-key --init
pubkey="repo-src/${DISTRO_NAME}.pub"
[ -s "$pubkey" ] || die "'$pubkey' is missing; iso/build_iso.sh should have staged it"
fpr="$(gpg --batch --show-keys --with-colons -- "$pubkey" | awk -F: '$1 == "fpr" { print $10; exit }')"
case "$fpr" in "" | *[!0-9A-F]*) die "no usable key fingerprint in '$pubkey'" ;; esac
sudo pacman-key --add "$pubkey"
sudo pacman-key --lsign-key "$fpr"

mkdir -p work out

log "running mkarchiso (mode: $MODE) against profile/ ..."
if [ "$MODE" = root ]; then
    sudo --preserve-env=DISTRO_NAME,SOURCE_DATE_EPOCH -- \
        mkarchiso -v -w work -o out profile
else
    mkarchiso -v -w work -o out profile
fi

log "done; output:"
ls -lh -- out/*.iso >&2
