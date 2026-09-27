#!/usr/bin/env bash
# determinism_check.sh - boot the same image N times and compare the screenshots.
#
# Each boot is an independent QEMU run from the same (unmodified) disk image, taken
# at the same trigger (see vm_capture.py). The first screenshot is then compared
# pixel by pixel with every later one.
#
# Usage: harness/spike/determinism_check.sh [RUNS]      (RUNS: 2..9, default 2)
# Environment: VM_BUILD_DIR as for boot_capture.sh. Results: $VM_BUILD_DIR/runs/det1..detN
# Exit status: 0 if all screenshots are pixel-identical, 1 if any differ.

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_DIR="$(cd -- "$SCRIPT_DIR/../.." && pwd -P)"
VM_BUILD_DIR="${VM_BUILD_DIR:-$PROJECT_DIR/.build/vm}"

RUNS="${1:-2}"
[[ "$RUNS" =~ ^[2-9]$ ]] || { echo "determinism_check.sh: RUNS must be 2..9" >&2; exit 2; }

for i in $(seq 1 "$RUNS"); do
    echo "=== boot $i of $RUNS ==="
    VM_BUILD_DIR="$VM_BUILD_DIR" "$SCRIPT_DIR/boot_capture.sh" "det$i"
done

status=0
for i in $(seq 2 "$RUNS"); do
    echo "=== det1.png vs det$i.png ==="
    python3 "$SCRIPT_DIR/compare_png.py" \
        "$VM_BUILD_DIR/runs/det1/det1.png" "$VM_BUILD_DIR/runs/det$i/det$i.png" || status=1
done
exit "$status"
