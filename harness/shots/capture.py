"""
Command line tool: boot the guest once and photograph every selected state.

    python3 -m harness.shots.capture --out DIR [--states a,b] [--modes light,dark]
                                     [--name NAME] [--generated DIR] [--image-dir DIR]

One boot, then for every selected mode: apply the colour scheme, and for every selected
state: reset, steps, settle, ``screendump`` to ``DIR/<mode>/<state>.png``. Also writes
``DIR/manifest.json`` (per state: mode, status, settle seconds, frames; boot timings;
host CPU/RAM summary). A failed state does not stop the run: later states still run.

Exit codes (docs/HARNESS_CONTRACT.md):
    0  every state was captured
    1  a state failed (did not settle, a step failed) or the VM died mid-run
    2  environment or usage problem (no KVM, image missing, bad states.toml, bad options)

Defaults come from the environment: ``DISTRO_NAME`` (theme name of the generated colour
schemes, else ``theme``), image directory ``.build/vm``, generated directory
``.build/generated`` (both relative to the project root). The output directory must lie
inside the project tree. Messages never print absolute paths.

Standard library only.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import shutil
import signal
import sys
import tempfile
import time
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from harness.shots import states as states_module
from harness.shots.runner import Runner, StateResult, StepError
from harness.shots.vm import Vm, VmBootError, VmConfig, VmEnvironmentError, host_summary

# The project root is two levels above this file (harness/shots/capture.py).
PROJECT_ROOT = Path(__file__).resolve().parents[2]
STATES_FILE = PROJECT_ROOT / "harness" / "states.toml"

NAME_PATTERN = re.compile(r"^[a-z0-9_-]+$")

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_ENVIRONMENT = 2


class EnvironmentProblem(Exception):
    """Something outside the states themselves prevents the run (exit code 2)."""


@dataclass(frozen=True)
class CaptureOptions:
    """
    Everything ``run_capture`` needs, already validated.

    Attributes:
        out_dir: Output directory (inside the project tree).
        states: State names to capture, or None for all.
        modes: Mode names to capture, or None for all.
        name: Theme name of the generated colour schemes.
        generated_dir: Directory produced by ``python -m design.generate``.
        image_dir: Directory with ``root.img``, ``vmlinuz``, ``initramfs.img``.
        states_file: The ``states.toml`` to use.
    """

    out_dir: Path
    states: list[str] | None
    modes: list[str] | None
    name: str
    generated_dir: Path
    image_dir: Path
    states_file: Path = STATES_FILE


def display_path(path: Path, root: Path = PROJECT_ROOT) -> str:
    """
    Describe a path for a message without leaking an absolute location.

    Args:
        path: Any path.
        root: The project root.

    Returns:
        The path relative to the project root when it is inside it, otherwise just its
        final component.
    """
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.name


def guard_output_dir(path: Path, root: Path = PROJECT_ROOT) -> Path:
    """
    Make sure the output directory is inside the project tree.

    Symbolic links and ``..`` are resolved first, so neither can lead out of the tree.

    Args:
        path: The requested output directory (relative paths are relative to the
            current directory).
        root: The project root.

    Returns:
        The resolved directory.

    Raises:
        ValueError: if it is the project root itself or outside it.
    """
    resolved = path.resolve()
    if root.resolve() not in resolved.parents:
        raise ValueError("--out must be a directory inside the project tree")
    return resolved


def split_names(text: str | None, option: str) -> list[str] | None:
    """
    Split a comma-separated command line value.

    Args:
        text: The raw value or None.
        option: Option name for error messages.

    Returns:
        The names, or None when the option was not given.

    Raises:
        ValueError: if an entry is empty.
    """
    if text is None:
        return None
    names = [part.strip() for part in text.split(",")]
    if not names or any(not part for part in names):
        raise ValueError(f"{option} must be a comma separated list of names")
    return names


def add_selection_arguments(parser: argparse.ArgumentParser) -> None:
    """
    Add the options shared by ``capture`` and ``determinism``.

    Args:
        parser: The parser to extend.
    """
    parser.add_argument("--states", help="comma separated state names (default: all)")
    parser.add_argument("--modes", help="comma separated mode names (default: all)")
    parser.add_argument("--name", default=os.environ.get("DISTRO_NAME", "theme"), help="theme name (default: $DISTRO_NAME or theme)")
    parser.add_argument("--generated", type=Path, default=PROJECT_ROOT / ".build" / "generated", help="directory made by `python -m design.generate`")
    parser.add_argument("--image-dir", type=Path, default=PROJECT_ROOT / ".build" / "vm", help="directory with root.img, vmlinuz, initramfs.img")


def build_options(args: argparse.Namespace, out_dir: Path) -> CaptureOptions:
    """
    Validate parsed arguments.

    Args:
        args: Result of parsing with ``add_selection_arguments``.
        out_dir: The output directory chosen by the caller.

    Returns:
        The options.

    Raises:
        ValueError: on a bad name, list or output directory.
    """
    if not NAME_PATTERN.match(args.name):
        raise ValueError("--name may only contain lowercase letters, digits, '_' and '-'")
    return CaptureOptions(
        out_dir=guard_output_dir(out_dir),
        states=split_names(args.states, "--states"),
        modes=split_names(args.modes, "--modes"),
        name=args.name,
        generated_dir=args.generated,
        image_dir=args.image_dir,
    )


def _load_masks(states_file: Path) -> dict[str, list[Any]]:
    """
    Read the comparison masks of every state through the comparison side's rule loader.

    Args:
        states_file: Path of ``states.toml``.

    Returns:
        State name to list of mask rectangles.

    Raises:
        EnvironmentProblem: the rule loader is missing or rejects the file.
    """
    try:
        from harness.shots.compare import load_rules
    except ImportError:
        raise EnvironmentProblem("the comparison module harness.shots.compare is not available") from None
    try:
        rules = load_rules(states_file)
    except (ValueError, TypeError, KeyError) as exc:
        raise EnvironmentProblem(f"comparison rules: {exc}") from None
    return {name: list(rule.masks) for name, rule in rules.items()}


def _default_runner(vm: Any, settings: states_module.Settings, work_dir: Path, log: Callable[[str], None]) -> Runner:
    """
    Build the real runner for a booted VM.

    Args:
        vm: The running ``Vm``.
        settings: The ``[settings]`` table.
        work_dir: Scratch directory.
        log: Progress callback.

    Returns:
        The runner.
    """
    return Runner(vm.qmp, vm.agent, settings, work_dir, log=log, cpu_probe=vm.agent.cpu_sample)


def _default_vm(config: VmConfig) -> Vm:
    """
    Build the real VM.

    Args:
        config: The VM configuration.

    Returns:
        A ``Vm`` (not yet started).
    """
    return Vm(config)


def run_capture(
    options: CaptureOptions,
    vm_factory: Callable[[VmConfig], Any] = _default_vm,
    runner_factory: Callable[[Any, states_module.Settings, Path, Callable[[str], None]], Runner] = _default_runner,
    log: Callable[[str], None] = lambda line: print(line, flush=True),
) -> tuple[int, dict[str, Any]]:
    """
    Boot once and capture every selected state in every selected mode.

    Args:
        options: The validated options.
        vm_factory: Creates the (not yet started) VM from a ``VmConfig``; replaced in tests.
        runner_factory: Creates the runner for a started VM; replaced in tests.
        log: Progress callback (one line of text).

    Returns:
        ``(exit code, manifest)``. The manifest is also written to
        ``<out_dir>/manifest.json`` once the run has started.

    Raises:
        EnvironmentProblem: states.toml is invalid, a colour scheme file, the image,
            KVM or the comparison module is missing, or the guest did not boot. The
            caller turns it into exit code 2.
    """
    started = time.monotonic()
    try:
        parsed = states_module.load_states(options.states_file)
        modes, chosen_states = states_module.select(parsed, options.states, options.modes)
    except ValueError as exc:
        raise EnvironmentProblem(str(exc)) from None
    plan = [(mode, state) for mode in modes for state in chosen_states if mode.name in state.modes]
    if not plan:
        raise EnvironmentProblem("nothing to capture: the selection matches no state in any mode")
    masks = _load_masks(options.states_file)

    # Fail before the (slow) boot if a colour scheme file is missing.
    for mode in modes:
        scheme_file = options.generated_dir / "plasma" / f"{options.name}-{mode.scheme}.colors"
        if not scheme_file.is_file():
            raise EnvironmentProblem(
                f"generated colour scheme {scheme_file.name} is missing; run `python -m design.generate`"
            )

    out_dir = options.out_dir
    for mode, state in plan:
        target = out_dir / mode.name
        target.mkdir(parents=True, exist_ok=True)
        # Results of an earlier run must never be mistaken for this run's.
        (target / f"{state.name}.png").unlink(missing_ok=True)
        (target / f"{state.name}.FAILED.png").unlink(missing_ok=True)

    settings = parsed.settings
    config = VmConfig(image_dir=options.image_dir, resolution=settings.resolution, rtc_base=settings.rtc_base)
    manifest: dict[str, Any] = {
        "schema": 1,
        "name": options.name,
        "resolution": list(settings.resolution),
        "modes": [mode.name for mode in modes],
        "outcome": "incomplete",
        "results": [],
    }
    results: list[StateResult] = []
    work_dir = Path(tempfile.mkdtemp(prefix="shots-work-"))
    vm_ref: Any = None
    vm_error = ""
    problem: EnvironmentProblem | None = None
    try:
        with vm_factory(config) as vm:
            vm_ref = vm
            manifest["boot"] = dict(vm.timings)
            runner = runner_factory(vm, settings, work_dir, log)
            log("waiting for the desktop")
            ready = runner.wait_for_desktop(masks[plan[0][1].name])
            manifest["boot"]["desktop_ready_s"] = round(time.monotonic() - vm.t0, 1)
            manifest["boot"]["desktop_settle_frames"] = ready.frames
            vm_error = _capture_all(runner, plan, masks, options, parsed, results, log)
            manifest["resources"] = vm.resources()
    except (VmEnvironmentError, VmBootError) as exc:
        problem = EnvironmentProblem(str(exc))
    except StepError as exc:
        # The desktop never came up: no state could be evaluated.
        problem = EnvironmentProblem(f"boot: {exc}")
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

    failed = [r for r in results if r.status != "ok"]
    ok = problem is None and not vm_error and not failed and len(results) == len(plan)
    manifest["results"] = [asdict(r) for r in results]
    manifest["host"] = host_summary()
    manifest["total_seconds"] = round(time.monotonic() - started, 1)
    manifest["summary"] = {
        "total": len(plan),
        "ok": len(results) - len(failed),
        "failed": len(plan) - (len(results) - len(failed)),
    }
    manifest["outcome"] = "ok" if ok else ("environment-error" if problem else "failed")
    if problem is not None:
        manifest["error"] = str(problem)
    if vm_error:
        manifest["vm_error"] = vm_error
    if (problem is not None or vm_error) and vm_ref is not None:
        manifest["vm_serial_tail"] = list(vm_ref.final_serial_tail)
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    if problem is not None:
        raise problem
    return (EXIT_OK if ok else EXIT_FAILED), manifest


def _capture_all(
    runner: Runner,
    plan: list[tuple[states_module.Mode, states_module.State]],
    masks: dict[str, list[Any]],
    options: CaptureOptions,
    parsed: states_module.StatesFile,
    results: list[StateResult],
    log: Callable[[str], None],
) -> str:
    """
    Run the plan: apply each mode once, then capture its states.

    Args:
        runner: The runner bound to the booted VM.
        plan: ``(mode, state)`` pairs in run order.
        masks: Comparison masks per state name.
        options: The options (output directory, colour scheme location).
        parsed: The validated states file.
        results: Output list that receives one ``StateResult`` per planned pair as it
            completes.
        log: Progress callback.

    Returns:
        The empty string, or a description if the VM connection was lost (remaining
        states are then recorded as failed and not run).
    """
    current_mode = None
    mode_error = ""
    lost = ""
    for mode, state in plan:
        rel = f"{mode.name}/{state.name}.png"
        if lost:
            results.append(StateResult(state.name, mode.name, "failed", error=f"not run: {lost}"))
            continue
        try:
            if mode is not current_mode:
                current_mode = mode
                mode_error = ""
                log(f"applying mode {mode.name}")
                try:
                    runner.apply_mode(mode, options.generated_dir, options.name, masks[state.name])
                except StepError as exc:
                    mode_error = f"mode {mode.name} could not be applied: {exc}"
            if mode_error:
                results.append(StateResult(state.name, mode.name, "failed", error=mode_error))
                continue
            results.append(runner.run_state(state, mode, masks[state.name], options.out_dir / rel, rel))
        except ConnectionError as exc:
            lost = f"the VM connection was lost ({exc})"
            results.append(StateResult(state.name, mode.name, "failed", error=lost))
    return lost


def print_summary(manifest: dict[str, Any]) -> None:
    """
    Print a compact table of the run.

    Args:
        manifest: The manifest returned by ``run_capture``.
    """
    print()
    print(f"{'mode':<6} {'state':<18} {'status':<7} {'settle_s':>8} {'frames':>6} {'total_s':>8}")
    for r in manifest["results"]:
        print(f"{r['mode']:<6} {r['state']:<18} {r['status']:<7} {r['settle_s']:>8} {r['frames']:>6} {r['duration_s']:>8}")
        if r["error"]:
            print(f"       {r['error']}")
    summary = manifest["summary"]
    print(f"\n{summary['ok']}/{summary['total']} states captured in {manifest['total_seconds']} s")


def _raise_exit(signum: int, frame: object) -> None:
    """
    Signal handler: turn a termination request into ``SystemExit``.

    Args:
        signum: The signal number.
        frame: The interrupted frame (unused).

    Raises:
        SystemExit: always, with the conventional status ``128 + signum``.
    """
    raise SystemExit(128 + signum)


@contextlib.contextmanager
def sigterm_as_exit() -> Iterator[None]:
    """
    Make SIGTERM unwind the stack like Ctrl-C does.

    WHY: QEMU runs in its own process group, so a plain SIGTERM that kills Python
    outright would leave the VM running. As ``SystemExit`` it passes through the
    ``Vm`` context manager, which stops QEMU and removes its runtime directory.

    Yields:
        Nothing; the previous handler is restored on exit.
    """
    previous = signal.signal(signal.SIGTERM, _raise_exit)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)


def main(argv: list[str] | None = None) -> int:
    """
    Command line entry point.

    Args:
        argv: Arguments (default ``sys.argv[1:]``).

    Returns:
        The exit code (0, 1 or 2; see the module docstring).
    """
    parser = argparse.ArgumentParser(prog="python3 -m harness.shots.capture", description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, required=True, help="output directory (inside the project tree)")
    add_selection_arguments(parser)
    args = parser.parse_args(argv)
    try:
        options = build_options(args, args.out)
        with sigterm_as_exit():
            code, manifest = run_capture(options)
    except (ValueError, EnvironmentProblem) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ENVIRONMENT
    print_summary(manifest)
    return code


if __name__ == "__main__":
    sys.exit(main())
