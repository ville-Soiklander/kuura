"""
Command line tool: check that the harness produces the same pictures on every boot.

    python3 -m harness.shots.determinism --runs N [--states a,b] [--modes light,dark]
                                         [--name NAME] [--generated DIR] [--image-dir DIR]
                                         [--out DIR]

Runs ``capture`` N times (a FRESH boot each time; the shots of run k go to
``<out>/run<k>/``), then compares run 1 with every other run, state by state and mode
by mode, with the tolerance, ratio and masks of that state
(``harness.shots.compare.load_rules``) and ``harness.shots.diff.compare_images``. Prints a
table of the differences.

Exit codes: 0 all runs agree, 1 some state differs or is missing (a capture failed),
2 environment or usage problem.

Standard library only.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from harness.shots import capture
from harness.shots import states as states_module

# Default output directory, relative to the project root.
DEFAULT_OUT = capture.PROJECT_ROOT / ".build" / "shots-determinism"


def compare_runs(
    out_dir: Path,
    runs: int,
    plan: list[tuple[str, str]],
    states_file: Path,
) -> list[dict[str, object]]:
    """
    Compare run 1 with every later run.

    Args:
        out_dir: Directory holding ``run1`` ... ``run<runs>``.
        runs: Number of runs.
        plan: ``(mode, state)`` pairs that were captured.
        states_file: The ``states.toml`` whose rules apply.

    Returns:
        One row per (mode, state, later run) with keys ``mode``, ``state``, ``run``,
        ``verdict`` (``same``, ``DIFFERENT`` or ``missing``), ``differing``, ``ratio``,
        ``max_delta`` and ``limit`` (allowed ratio).

    Raises:
        capture.EnvironmentProblem: the comparison module or the rules are unavailable.
    """
    try:
        from harness.shots.compare import load_rules
        from harness.shots.diff import compare_images
    except ImportError:
        raise capture.EnvironmentProblem("the comparison modules harness.shots.compare/diff are not available") from None
    try:
        rules = load_rules(states_file)
    except (ValueError, TypeError, KeyError) as exc:
        raise capture.EnvironmentProblem(f"comparison rules: {exc}") from None

    rows: list[dict[str, object]] = []
    for mode, state in plan:
        rule = rules[state]
        first = out_dir / "run1" / mode / f"{state}.png"
        for run in range(2, runs + 1):
            other = out_dir / f"run{run}" / mode / f"{state}.png"
            row: dict[str, object] = {"mode": mode, "state": state, "run": run, "limit": rule.max_diff_ratio}
            if not first.is_file() or not other.is_file():
                row.update(verdict="missing", differing=0, ratio=0.0, max_delta=0)
            else:
                result = compare_images(other, first, rule.tolerance, rule.max_diff_ratio, list(rule.masks))
                row.update(
                    verdict="same" if result.passed else "DIFFERENT",
                    differing=result.differing_pixels,
                    ratio=result.ratio,
                    max_delta=result.max_delta,
                )
            rows.append(row)
    return rows


def print_table(rows: list[dict[str, object]]) -> None:
    """
    Print the comparison rows.

    Args:
        rows: Output of ``compare_runs``.
    """
    print()
    print(f"{'mode':<6} {'state':<18} {'run':>3} {'verdict':<10} {'differing px':>12} {'ratio':>10} {'max delta':>9}")
    for row in rows:
        print(
            f"{row['mode']:<6} {row['state']:<18} {row['run']:>3} {row['verdict']:<10} "
            f"{row['differing']:>12} {float(row['ratio']):>10.6f} {row['max_delta']:>9}"
        )


def main(argv: list[str] | None = None) -> int:
    """
    Command line entry point.

    Args:
        argv: Arguments (default ``sys.argv[1:]``).

    Returns:
        The exit code (0, 1 or 2; see the module docstring).
    """
    parser = argparse.ArgumentParser(prog="python3 -m harness.shots.determinism", description=__doc__.split("\n\n")[0])
    parser.add_argument("--runs", type=int, required=True, help="number of boots to compare (2 to 10)")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="output directory (inside the project tree)")
    capture.add_selection_arguments(parser)
    args = parser.parse_args(argv)
    if not 2 <= args.runs <= 10:
        print("error: --runs must be between 2 and 10", file=sys.stderr)
        return capture.EXIT_ENVIRONMENT

    started = time.monotonic()
    worst = capture.EXIT_OK
    try:
        base = capture.build_options(args, args.out)
        parsed = states_module.load_states(base.states_file)
        modes, chosen = states_module.select(parsed, base.states, base.modes)
        plan = [(m.name, s.name) for m in modes for s in chosen if m.name in s.modes]
        for run in range(1, args.runs + 1):
            print(f"=== run {run} of {args.runs}", flush=True)
            options = capture.CaptureOptions(
                out_dir=capture.guard_output_dir(base.out_dir / f"run{run}"),
                states=base.states,
                modes=base.modes,
                name=base.name,
                generated_dir=base.generated_dir,
                image_dir=base.image_dir,
                states_file=base.states_file,
            )
            with capture.sigterm_as_exit():
                code, manifest = capture.run_capture(options)
            capture.print_summary(manifest)
            worst = max(worst, code)
        rows = compare_runs(base.out_dir, args.runs, plan, base.states_file)
    except (ValueError, capture.EnvironmentProblem) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return capture.EXIT_ENVIRONMENT

    print_table(rows)
    differing = [r for r in rows if r["verdict"] != "same"]
    print(f"\n{len(rows) - len(differing)}/{len(rows)} comparisons agree; total {round(time.monotonic() - started)} s")
    if differing or worst != capture.EXIT_OK:
        return capture.EXIT_FAILED
    return capture.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
