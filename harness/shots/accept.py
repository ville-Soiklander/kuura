"""Accept and copy screenshots as golden images."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from pathlib import Path

from .pngio import read_png


def _validate_name(name: str) -> bool:
    """Check if a name is a valid state/mode name: ^[a-z0-9-]+$"""
    return bool(re.match(r"^[a-z0-9-]+$", name))


def main() -> int:
    """
    CLI: python -m harness.shots.accept --shots DIR --goldens DIR [--states a,b]

    Copies PNG files from shots/<mode>/<state>.png to goldens/<mode>/<state>.png.
    Refuses when CI environment variable is set (non-empty).

    Exit codes:
        0: success
        1: no files copied (but not an error)
        2: refused (CI set) or bad input/path traversal
    """
    p = argparse.ArgumentParser(
        description="Accept screenshots as golden images",
    )
    p.add_argument("--shots", type=Path, required=True, help="Directory with actual screenshots")
    p.add_argument("--goldens", type=Path, required=True, help="Directory for golden images")
    p.add_argument("--states", help="Comma-separated list of states to accept (default: all)")

    args = p.parse_args()

    # WHY: Refuse in CI environment to prevent accidental golden updates
    if os.getenv("CI"):
        print("accept: refused: cannot update goldens in CI environment", file=sys.stderr)
        return 2

    # Parse states filter
    states_filter = set()
    if args.states:
        states_filter = set(args.states.split(","))

    # Validate input directories
    if not args.shots.is_dir():
        print(f"accept: shots directory not found: {args.shots}", file=sys.stderr)
        return 2
    if not args.goldens.is_dir():
        try:
            args.goldens.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            print(f"accept: error creating goldens directory: {exc}", file=sys.stderr)
            return 2

    copied = 0

    # Scan shots directory
    try:
        for mode_dir in args.shots.iterdir():
            if not mode_dir.is_dir():
                continue

            mode = mode_dir.name
            if not _validate_name(mode):
                print(f"accept: unsafe mode name: {mode}", file=sys.stderr)
                return 2

            for png_file in mode_dir.glob("*.png"):
                state = png_file.stem

                if not _validate_name(state):
                    print(f"accept: unsafe state name: {state}", file=sys.stderr)
                    return 2

                # Filter by states if specified
                if states_filter and state not in states_filter:
                    continue

                # Validate PNG signature
                try:
                    width, height, rgb = read_png(png_file)
                except (OSError, ValueError) as exc:
                    print(f"accept: error reading {mode}/{state}.png: {exc}", file=sys.stderr)
                    return 2

                # Copy to goldens
                golden_dir = args.goldens / mode
                try:
                    golden_dir.mkdir(parents=True, exist_ok=True)
                    golden_path = golden_dir / f"{state}.png"

                    # Guard against path traversal (verify golden_path is inside goldens)
                    golden_path.resolve()
                    if not str(golden_path.resolve()).startswith(str(args.goldens.resolve())):
                        print(f"accept: path traversal attempt: {state}", file=sys.stderr)
                        return 2

                    shutil.copy2(png_file, golden_path)
                    print(f"copied {mode}/{state}.png")
                    copied += 1
                except OSError as exc:
                    print(f"accept: error copying {mode}/{state}.png: {exc}", file=sys.stderr)
                    return 2

    except OSError as exc:
        print(f"accept: error scanning shots: {exc}", file=sys.stderr)
        return 2

    if copied == 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
