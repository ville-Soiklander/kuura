"""Compare screenshots with goldens and generate reports."""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .diff import Rect, compare_images, write_diff_image
from .review import render_report, render_review_html


@dataclass(frozen=True)
class StateRules:
    """Comparison rules for a state (tolerance, ratio, masks, modes)."""

    tolerance: int
    max_diff_ratio: float
    masks: list[Rect]
    modes: list[str]


def load_rules(states_file: Path) -> dict[str, StateRules]:
    """
    Load comparison rules from states.toml.

    Reads defaults from [defaults], then applies per-state overrides.
    Keys: tolerance, max_diff_ratio, mask, modes.

    Args:
        states_file: Path to states.toml.

    Returns:
        Dict mapping state name to StateRules.

    Raises:
        ValueError: on missing file, parse error, or invalid values.
    """
    if not states_file.exists():
        raise ValueError(f"states file not found: {states_file}")

    with open(states_file, "rb") as f:
        data = tomllib.load(f)

    defaults = data.get("defaults", {})
    default_tolerance = defaults.get("tolerance", 3)
    default_max_diff_ratio = defaults.get("max_diff_ratio", 0.0005)
    default_masks = [Rect(*mask) for mask in defaults.get("mask", [])]
    default_modes = list(data.get("modes", {}).keys())

    # Validate defaults
    if not (0 <= default_tolerance <= 255):
        raise ValueError(f"invalid tolerance: {default_tolerance}")
    if not (0.0 <= default_max_diff_ratio <= 1.0):
        raise ValueError(f"invalid max_diff_ratio: {default_max_diff_ratio}")
    for mask in default_masks:
        if not (0 <= mask.x0 < mask.x1 and 0 <= mask.y0 < mask.y1):
            raise ValueError(f"invalid mask: {mask}")

    rules = {}
    for state_data in data.get("state", []):
        state_name = state_data.get("name")
        if not state_name:
            raise ValueError("state missing 'name'")

        # Start with defaults, apply overrides
        tolerance = state_data.get("tolerance", default_tolerance)
        max_diff_ratio = state_data.get("max_diff_ratio", default_max_diff_ratio)
        mask_list = state_data.get("mask", default_masks)
        modes = state_data.get("modes", default_modes)

        # Validate overrides
        if not (0 <= tolerance <= 255):
            raise ValueError(f"invalid tolerance for state {state_name}: {tolerance}")
        if not (0.0 <= max_diff_ratio <= 1.0):
            raise ValueError(f"invalid max_diff_ratio for state {state_name}: {max_diff_ratio}")
        if isinstance(mask_list, list):
            mask_list = [Rect(*mask) if isinstance(mask, (list, tuple)) else mask for mask in mask_list]
        for mask in mask_list:
            if not (0 <= mask.x0 < mask.x1 and 0 <= mask.y0 < mask.y1):
                raise ValueError(f"invalid mask in state {state_name}: {mask}")

        rules[state_name] = StateRules(
            tolerance=tolerance,
            max_diff_ratio=max_diff_ratio,
            masks=mask_list,
            modes=modes,
        )

    return rules


def _sanitize_path(name: str) -> str:
    """Reject path traversal attempts in state/mode names."""
    if ".." in name or name.startswith("/"):
        raise ValueError(f"unsafe path component: {name}")
    return name


def main() -> int:
    """
    CLI: python -m harness.shots.compare --shots DIR --goldens DIR --out DIR [--allow-missing] [--states-file FILE]

    Exit codes:
        0: all pass
        1: any fail or missing-golden (without --allow-missing)
        2: environment problem or bad input
    """
    p = argparse.ArgumentParser(
        description="Compare screenshots with goldens and generate reports",
    )
    p.add_argument("--shots", type=Path, required=True, help="Directory with actual screenshots")
    p.add_argument("--goldens", type=Path, required=True, help="Directory with golden images")
    p.add_argument("--out", type=Path, required=True, help="Output directory for reports")
    p.add_argument("--allow-missing", action="store_true", help="Allow missing goldens")
    p.add_argument("--states-file", type=Path, help="Path to states.toml (default: harness/states.toml)")

    args = p.parse_args()

    # Determine states file location
    if args.states_file:
        states_file = args.states_file
    else:
        # Default: relative to this package
        states_file = Path(__file__).parent.parent / "states.toml"

    # Load rules
    try:
        rules = load_rules(states_file)
    except (ValueError, FileNotFoundError, tomllib.TOMLDecodeError) as exc:
        print(f"compare: error loading rules: {exc}", file=sys.stderr)
        return 2

    # Create output directory
    try:
        args.out.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"compare: error creating output directory: {exc}", file=sys.stderr)
        return 2

    # Scan shots directory for (mode, state) pairs
    shots_by_mode_state: dict[tuple[str, str], Path] = {}
    try:
        for mode_dir in args.shots.iterdir():
            if not mode_dir.is_dir():
                continue
            mode = _sanitize_path(mode_dir.name)
            for png_file in mode_dir.glob("*.png"):
                state = _sanitize_path(png_file.stem)
                shots_by_mode_state[(mode, state)] = png_file
    except OSError as exc:
        print(f"compare: error scanning shots: {exc}", file=sys.stderr)
        return 2

    # Compare and collect results
    results = []
    goldens_without_shots = set()
    any_fail = False
    any_missing_golden = False

    # Compare each shot
    for (mode, state), shot_path in sorted(shots_by_mode_state.items()):
        golden_path = args.goldens / mode / f"{state}.png"

        # Get rules for this state (or use defaults)
        state_rules = rules.get(state)
        if state_rules is None:
            # No rules defined; skip or use empty defaults
            state_rules = StateRules(tolerance=3, max_diff_ratio=0.0005, masks=[], modes=[])

        # Check if mode is relevant
        if state_rules.modes and mode not in state_rules.modes:
            continue

        # Get relative paths for reporting
        try:
            actual_rel = shot_path.relative_to(args.out.parent) if shot_path.parent.parent == args.out.parent else shot_path.name
        except ValueError:
            actual_rel = shot_path.name

        if not golden_path.exists():
            results.append(
                {
                    "mode": mode,
                    "state": state,
                    "status": "missing-golden",
                    "actual_path": str(actual_rel),
                    "golden_path": None,
                    "diff_path": None,
                    "differing_pixels": None,
                    "ratio": None,
                    "max_delta": None,
                    "bbox": None,
                }
            )
            if not args.allow_missing:
                any_missing_golden = True
            continue

        # Compare
        try:
            diff_result = compare_images(
                shot_path,
                golden_path,
                tolerance=state_rules.tolerance,
                max_diff_ratio=state_rules.max_diff_ratio,
                masks=state_rules.masks,
            )
        except (OSError, ValueError) as exc:
            print(f"compare: error comparing {mode}/{state}: {exc}", file=sys.stderr)
            return 2

        status = "pass" if diff_result.passed else "fail"
        if not diff_result.passed:
            any_fail = True

        # Generate diff image for failures
        diff_path = None
        if not diff_result.passed:
            diff_path = args.out / mode / f"{state}-diff.png"
            try:
                diff_path.parent.mkdir(parents=True, exist_ok=True)
                write_diff_image(
                    shot_path,
                    golden_path,
                    diff_path,
                    tolerance=state_rules.tolerance,
                    masks=state_rules.masks,
                )
                # Compute relative path
                try:
                    diff_path_rel = diff_path.relative_to(args.out.parent)
                except ValueError:
                    diff_path_rel = diff_path
            except (OSError, ValueError) as exc:
                print(f"compare: error writing diff: {exc}", file=sys.stderr)
                return 2
        else:
            diff_path_rel = None

        # Get relative paths
        try:
            actual_rel = shot_path.relative_to(args.out.parent)
        except ValueError:
            actual_rel = shot_path.name
        try:
            golden_rel = golden_path.relative_to(args.out.parent)
        except ValueError:
            golden_rel = golden_path.name

        results.append(
            {
                "mode": mode,
                "state": state,
                "status": status,
                "actual_path": str(actual_rel),
                "golden_path": str(golden_rel),
                "diff_path": str(diff_path_rel) if diff_path_rel else None,
                "differing_pixels": diff_result.differing_pixels,
                "ratio": diff_result.ratio,
                "max_delta": diff_result.max_delta,
                "bbox": diff_result.bbox,
            }
        )

    # Check for goldens without shots (scan goldens directory)
    try:
        for mode_dir in args.goldens.iterdir():
            if not mode_dir.is_dir():
                continue
            mode = _sanitize_path(mode_dir.name)
            for png_file in mode_dir.glob("*.png"):
                state = _sanitize_path(png_file.stem)
                if (mode, state) not in shots_by_mode_state:
                    goldens_without_shots.add((mode, state))
                    results.append(
                        {
                            "mode": mode,
                            "state": state,
                            "status": "missing-shot",
                            "actual_path": None,
                            "golden_path": str(png_file.relative_to(args.out.parent) if png_file.parent.parent == args.out.parent else png_file.name),
                            "diff_path": None,
                            "differing_pixels": None,
                            "ratio": None,
                            "max_delta": None,
                            "bbox": None,
                        }
                    )
                    any_fail = True
    except OSError as exc:
        print(f"compare: error scanning goldens: {exc}", file=sys.stderr)
        return 2

    # Write reports
    try:
        # summary.json
        summary = {
            "pass": sum(1 for r in results if r["status"] == "pass"),
            "fail": sum(1 for r in results if r["status"] == "fail"),
            "missing_golden": sum(1 for r in results if r["status"] == "missing-golden"),
            "missing_shot": sum(1 for r in results if r["status"] == "missing-shot"),
        }
        (args.out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

        # report.md
        (args.out / "report.md").write_text(render_report(results), encoding="utf-8")

        # review.html
        (args.out / "review.html").write_text(render_review_html(results, args.out), encoding="utf-8")
    except OSError as exc:
        print(f"compare: error writing reports: {exc}", file=sys.stderr)
        return 2

    # Exit code
    if any_fail or any_missing_golden:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
