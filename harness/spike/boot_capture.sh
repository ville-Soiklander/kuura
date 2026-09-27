#!/usr/bin/env bash
# boot_capture.sh - boot the guest image once and capture a host-side screenshot.
#
# Thin wrapper around vm_capture.py: it finds the build directory (the same
# default as build_rootfs.sh), checks the inputs and passes everything else on.
#
# Usage: harness/spike/boot_capture.sh TAG [vm_capture.py options...]
#   TAG   name of the run, [A-Za-z0-9_-]{1,32}; results go to
#         $VM_BUILD_DIR/runs/TAG/ (TAG.png, TAG-summary.json, TAG-serial.log, ...)
# Environment:
#   VM_BUILD_DIR  directory produced by build_rootfs.sh
#                 (default <project>/.build/vm)
# Example:  harness/spike/boot_capture.sh run1 --diag

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_DIR="$(cd -- "$SCRIPT_DIR/../.." && pwd -P)"

die() { printf 'boot_capture.sh: error: %s\n' "$*" >&2; exit 1; }

[ "$#" -ge 1 ] || die "usage: boot_capture.sh TAG [vm_capture.py options...]"
TAG="$1"
shift
[[ "$TAG" =~ ^[A-Za-z0-9_-]{1,32}$ ]] || die "TAG must match [A-Za-z0-9_-]{1,32}"

VM_BUILD_DIR="${VM_BUILD_DIR:-$PROJECT_DIR/.build/vm}"
[ -d "$VM_BUILD_DIR" ] || die "'$VM_BUILD_DIR' does not exist; run build_rootfs.sh first"

# KVM is required: without it a Plasma boot in software emulation takes far too long.
[ -r /dev/kvm ] && [ -w /dev/kvm ] || die "/dev/kvm is not accessible (is the user in the kvm group?)"
command -v qemu-system-x86_64 >/dev/null 2>&1 || die "qemu-system-x86_64 not found in PATH"

exec python3 "$SCRIPT_DIR/vm_capture.py" --build-dir "$VM_BUILD_DIR" --tag "$TAG" "$@"
