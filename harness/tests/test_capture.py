"""
Tests for harness.shots.capture (orchestration, exit codes, manifest, path guard) and the
pure parts of harness.shots.vm.

No VM is booted: the capture run uses a fake VM and a fake runner; the process-control
tests of ``Vm`` use a shell script that stands in for QEMU (Linux only).
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from harness.shots import capture, vm
from harness.shots.capture import CaptureOptions, EnvironmentProblem, run_capture
from harness.shots.runner import SettleResult, StateResult, StepError
from harness.shots.vm import Vm, VmBootError, VmConfig, VmEnvironmentError

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ON_WINDOWS = os.name == "nt"

SMALL_TOML = """
[settings]
resolution = [2560, 1440]
settle_frames = 2
settle_interval_s = 1.0
settle_timeout_s = 30
rtc_base = "2026-09-25T12:00:00"
reset = [ { key = "escape" } ]

[defaults]
tolerance = 3
max_diff_ratio = 0.0005
mask = [[2300, 1340, 2560, 1440]]

[modes.light]
scheme = "light"
[modes.dark]
scheme = "dark"

[[state]]
name = "a"
description = "First."
steps = []

[[state]]
name = "b"
description = "Second."
steps = [ { key = "meta+w" }, { settle = true } ]

[[state]]
name = "c"
description = "Third, light only."
steps = []
modes = ["light"]
"""


class FakeVm:
    """
    A VM that never boots: a context manager with the attributes ``run_capture`` reads.

    Args:
        config: The configuration the factory received.
        enter_error: Exception raised when entering (a failed boot), or None.
    """

    def __init__(self, config: VmConfig, enter_error: Exception | None = None) -> None:
        self.config = config
        self.enter_error = enter_error
        self.timings = {"qmp_connected_s": 0.1, "agent_up_s": 5.0}
        self.t0 = time.monotonic()
        self.qmp = object()
        self.agent = object()
        self.final_serial_tail = ["kernel: last line"]
        self.exited = False

    def __enter__(self) -> FakeVm:
        """
        Enter the context.

        Returns:
            This object.

        Raises:
            Exception: the configured boot error.
        """
        if self.enter_error is not None:
            raise self.enter_error
        return self

    def __exit__(self, *exc: object) -> None:
        """Record that the VM was stopped."""
        self.exited = True

    def resources(self) -> dict[str, float]:
        """
        Return fixed resource numbers.

        Returns:
            A small summary.
        """
        return {"qemu_avg_cores": 1.5, "qemu_peak_rss_mb": 2000}


class FakeRunner:
    """
    A runner that only records what it is asked to do.

    Args:
        fail: ``(mode, state)`` pairs whose state fails.
        lose: The ``(mode, state)`` pair at which the connection is lost, or None.
        bad_modes: Names of modes that cannot be applied.
        boot_error: Raised by ``wait_for_desktop`` when set.
    """

    def __init__(
        self,
        fail: set[tuple[str, str]] | None = None,
        lose: tuple[str, str] | None = None,
        bad_modes: set[str] | None = None,
        boot_error: StepError | None = None,
    ) -> None:
        self.fail = fail or set()
        self.lose = lose
        self.bad_modes = bad_modes or set()
        self.boot_error = boot_error
        self.calls: list[tuple[str, str]] = []
        self.masks_seen: list[Any] = []

    def wait_for_desktop(self, masks: Any) -> SettleResult:
        """
        Pretend the desktop came up.

        Args:
            masks: The masks used for the boot settle.

        Returns:
            A stable result.

        Raises:
            StepError: the configured boot error.
        """
        if self.boot_error is not None:
            raise self.boot_error
        self.masks_seen.append(masks)
        return SettleResult(True, 4.0, 3)

    def apply_mode(self, mode: Any, generated_dir: Path, name: str, masks: Any) -> SettleResult:
        """
        Pretend to apply a mode.

        Args:
            mode: The mode.
            generated_dir: Directory of colour schemes.
            name: Theme name.
            masks: Masks.

        Returns:
            A stable result.

        Raises:
            StepError: for modes listed in ``bad_modes``.
        """
        if mode.name in self.bad_modes:
            raise StepError("the screen did not change")
        self.calls.append(("mode", mode.name))
        return SettleResult(True, 1.0, 2)

    def run_state(self, state: Any, mode: Any, masks: Any, shot: Path, rel: str) -> StateResult:
        """
        Pretend to capture a state.

        Args:
            state: The state.
            mode: The mode.
            masks: Masks.
            shot: Where the screenshot would go.
            rel: The same, relative.

        Returns:
            A result; a failed state writes no shot.

        Raises:
            ConnectionError: at the configured ``lose`` pair.
        """
        key = (mode.name, state.name)
        self.calls.append(key)
        self.masks_seen.append(masks)
        if key == self.lose:
            raise ConnectionError("peer closed the connection")
        if key in self.fail:
            return StateResult(state.name, mode.name, "failed", error="step 1 (settle): timeout", duration_s=3.0)
        shot.write_bytes(b"\x89PNG fake")
        return StateResult(state.name, mode.name, settle_s=2.0, frames=3, duration_s=5.0, shot=rel)


@pytest.fixture
def options(tmp_path: Path) -> CaptureOptions:
    """
    Build capture options on a small states file and a generated directory.

    Args:
        tmp_path: Pytest temporary directory.

    Returns:
        Options whose output directory is ``tmp_path/out`` (the path guard belongs to
        ``build_options``, not to ``run_capture``).
    """
    states_file = tmp_path / "states.toml"
    states_file.write_text(SMALL_TOML, encoding="utf-8")
    generated = tmp_path / "generated"
    (generated / "plasma").mkdir(parents=True)
    for scheme in ("light", "dark"):
        (generated / "plasma" / f"kuura-{scheme}.colors").write_text("[General]\n", encoding="utf-8")
    return CaptureOptions(
        out_dir=tmp_path / "out",
        states=None,
        modes=None,
        name="kuura",
        generated_dir=generated,
        image_dir=tmp_path / "image",
        states_file=states_file,
    )


def capture_with(options: CaptureOptions, runner: FakeRunner, vm_error: Exception | None = None) -> tuple[int, dict[str, Any], list[FakeVm]]:
    """
    Run ``run_capture`` with the fakes.

    Args:
        options: The options.
        runner: The fake runner.
        vm_error: Boot error for the fake VM, or None.

    Returns:
        Exit code, manifest and the list of VMs the factory created.
    """
    created: list[FakeVm] = []

    def vm_factory(config: VmConfig) -> FakeVm:
        machine = FakeVm(config, vm_error)
        created.append(machine)
        return machine

    code, manifest = run_capture(options, vm_factory=vm_factory, runner_factory=lambda *args: runner, log=lambda line: None)
    return code, manifest, created


# --- run_capture: success ------------------------------------------------------------------


def test_a_clean_run_captures_every_state_in_every_mode_and_writes_the_manifest(options: CaptureOptions) -> None:
    """
    Exit 0; one PNG per (mode, state) under ``<out>/<mode>/<state>.png``; each mode is
    applied once; the manifest carries per-state entries, boot timings, resources and the
    host summary, and equals the file on disk.

    Args:
        options: Options fixture.

    Returns:
        None.
    """
    runner = FakeRunner()
    code, manifest, created = capture_with(options, runner)
    assert code == 0
    # State "c" only runs in light: 3 + 2 + ... = light a,b,c and dark a,b.
    assert [c for c in runner.calls if c[0] != "mode"] == [
        ("light", "a"), ("light", "b"), ("light", "c"), ("dark", "a"), ("dark", "b"),
    ]
    assert runner.calls.count(("mode", "light")) == 1 and runner.calls.count(("mode", "dark")) == 1
    for mode, state in [("light", "a"), ("light", "b"), ("light", "c"), ("dark", "a"), ("dark", "b")]:
        assert (options.out_dir / mode / f"{state}.png").is_file()
    assert not (options.out_dir / "dark" / "c.png").exists()

    assert manifest["schema"] == 1 and manifest["name"] == "kuura" and manifest["outcome"] == "ok"
    assert manifest["resolution"] == [2560, 1440] and manifest["modes"] == ["light", "dark"]
    assert manifest["summary"] == {"total": 5, "ok": 5, "failed": 0}
    first = manifest["results"][0]
    assert first == {
        "state": "a", "mode": "light", "status": "ok", "settle_s": 2.0, "frames": 3,
        "duration_s": 5.0, "shot": "light/a.png", "error": "", "diagnostic": "",
    }
    assert manifest["boot"]["qmp_connected_s"] == 0.1 and manifest["boot"]["agent_up_s"] == 5.0
    assert "desktop_ready_s" in manifest["boot"] and manifest["boot"]["desktop_settle_frames"] == 3
    assert manifest["resources"]["qemu_avg_cores"] == 1.5
    assert "cpu_count" in manifest["host"] and manifest["total_seconds"] >= 0
    assert json.loads((options.out_dir / "manifest.json").read_text(encoding="utf-8")) == manifest
    assert created[0].exited and created[0].config.resolution == (2560, 1440)
    assert created[0].config.rtc_base == "2026-09-25T12:00:00"
    # Every state got the panel clock mask from the comparison rules.
    assert all(masks and masks[0].x0 == 2300 for masks in runner.masks_seen)


def test_selection_limits_states_and_modes(options: CaptureOptions) -> None:
    """
    ``--states`` and ``--modes`` restrict the run; a state that does not list a mode is
    skipped in it.

    Args:
        options: Options fixture.

    Returns:
        None.
    """
    runner = FakeRunner()
    limited = CaptureOptions(**{**options.__dict__, "states": ["b", "c"], "modes": ["dark"]})
    code, manifest, _ = capture_with(limited, runner)
    assert code == 0
    assert [c for c in runner.calls if c[0] != "mode"] == [("dark", "b")]
    assert manifest["summary"]["total"] == 1


def test_old_results_are_removed_before_the_run(options: CaptureOptions) -> None:
    """
    A shot or diagnostic left by an earlier run is deleted first, so a failed state can
    never be mistaken for the old, passing picture.

    Args:
        options: Options fixture.

    Returns:
        None.
    """
    stale = options.out_dir / "light"
    stale.mkdir(parents=True)
    (stale / "a.png").write_bytes(b"old")
    (stale / "a.FAILED.png").write_bytes(b"old")
    code, _, _ = capture_with(options, FakeRunner(fail={("light", "a")}))
    assert code == 1
    assert not (stale / "a.png").exists() and not (stale / "a.FAILED.png").exists()


# --- run_capture: failures ------------------------------------------------------------------


def test_a_failed_state_does_not_stop_later_states_but_sets_exit_code_1(options: CaptureOptions) -> None:
    """
    State ``b`` fails in light; ``c`` (later in light) and the dark states still run;
    the exit code is 1 and the manifest records the failure.

    Args:
        options: Options fixture.

    Returns:
        None.
    """
    runner = FakeRunner(fail={("light", "b")})
    code, manifest, _ = capture_with(options, runner)
    assert code == 1
    ran = [c for c in runner.calls if c[0] != "mode"]
    assert ("light", "c") in ran and ("dark", "a") in ran and ("dark", "b") in ran
    assert manifest["outcome"] == "failed"
    assert manifest["summary"] == {"total": 5, "ok": 4, "failed": 1}
    failed = [r for r in manifest["results"] if r["status"] == "failed"]
    assert [(r["mode"], r["state"]) for r in failed] == [("light", "b")]
    assert "step 1" in failed[0]["error"]
    assert not (options.out_dir / "light" / "b.png").exists()


def test_a_mode_that_cannot_be_applied_fails_its_states_only(options: CaptureOptions) -> None:
    """
    If the dark scheme cannot be applied, every dark state fails with that reason and the
    light states are unaffected.

    Args:
        options: Options fixture.

    Returns:
        None.
    """
    runner = FakeRunner(bad_modes={"dark"})
    code, manifest, _ = capture_with(options, runner)
    assert code == 1
    dark = [r for r in manifest["results"] if r["mode"] == "dark"]
    assert len(dark) == 2 and all(r["status"] == "failed" and "mode dark could not be applied" in r["error"] for r in dark)
    assert all(r["status"] == "ok" for r in manifest["results"] if r["mode"] == "light")
    assert ("dark", "a") not in runner.calls


def test_a_lost_vm_fails_the_rest_of_the_run(options: CaptureOptions) -> None:
    """
    A ConnectionError from the runner ends the run: the current state fails, the remaining
    ones are recorded as not run, the serial tail is kept, and the exit code is 1.

    Args:
        options: Options fixture.

    Returns:
        None.
    """
    runner = FakeRunner(lose=("light", "b"))
    code, manifest, created = capture_with(options, runner)
    assert code == 1
    assert manifest["outcome"] == "failed"
    assert "connection was lost" in manifest["vm_error"]
    assert manifest["vm_serial_tail"] == ["kernel: last line"]
    results = {(r["mode"], r["state"]): r for r in manifest["results"]}
    assert results[("light", "b")]["status"] == "failed"
    assert results[("light", "c")]["error"].startswith("not run")
    assert results[("dark", "b")]["status"] == "failed"
    assert manifest["summary"] == {"total": 5, "ok": 1, "failed": 4}
    assert created[0].exited


# --- run_capture: environment problems (exit 2) --------------------------------------------------


def test_missing_scheme_file_is_an_environment_problem_before_boot(options: CaptureOptions) -> None:
    """
    A missing generated scheme is reported (by file name only) before any VM is created.

    Args:
        options: Options fixture.

    Returns:
        None.
    """
    (options.generated_dir / "plasma" / "kuura-dark.colors").unlink()
    created: list[Any] = []
    with pytest.raises(EnvironmentProblem, match="kuura-dark.colors is missing") as caught:
        run_capture(options, vm_factory=lambda config: created.append(config), runner_factory=lambda *a: None)
    assert created == []
    assert str(options.generated_dir) not in str(caught.value)


@pytest.mark.parametrize(
    "text, message",
    [
        ("not = = toml", "not valid TOML"),
        ("[settings]\nresolution = [1, 1]", "missing key"),
    ],
)
def test_invalid_states_file_is_an_environment_problem(options: CaptureOptions, text: str, message: str) -> None:
    """
    A broken ``states.toml`` (syntax or schema) is caught before boot.

    Args:
        options: Options fixture.
        text: Content of the states file.
        message: Text the error must contain.

    Returns:
        None.
    """
    options.states_file.write_text(text, encoding="utf-8")
    with pytest.raises(EnvironmentProblem, match=message):
        run_capture(options, vm_factory=lambda config: None, runner_factory=lambda *a: None)


def test_unknown_selection_is_an_environment_problem(options: CaptureOptions) -> None:
    """
    An unknown state or mode name, or a selection that matches nothing, is exit-code-2 material.

    Args:
        options: Options fixture.

    Returns:
        None.
    """
    for bad in (
        CaptureOptions(**{**options.__dict__, "states": ["nope"]}),
        CaptureOptions(**{**options.__dict__, "modes": ["twilight"]}),
        CaptureOptions(**{**options.__dict__, "states": ["c"], "modes": ["dark"]}),
    ):
        with pytest.raises(EnvironmentProblem):
            run_capture(bad, vm_factory=lambda config: None, runner_factory=lambda *a: None)


@pytest.mark.parametrize("error", [VmBootError("the VM did not come up: timeout"), VmEnvironmentError("/dev/kvm is not accessible")])
def test_boot_failures_are_environment_problems_with_a_manifest(options: CaptureOptions, error: Exception) -> None:
    """
    A VM that cannot start (no KVM, image missing, boot timeout) raises EnvironmentProblem
    and leaves a manifest that says so, with the serial tail.

    Args:
        options: Options fixture.
        error: The boot error.

    Returns:
        None.
    """
    with pytest.raises(EnvironmentProblem, match=str(error)[:12]):
        capture_with(options, FakeRunner(), vm_error=error)
    manifest = json.loads((options.out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["outcome"] == "environment-error" and str(error) in manifest["error"]


def test_a_desktop_that_never_settles_at_boot_is_an_environment_problem(options: CaptureOptions) -> None:
    """
    If the desktop does not come up, no state can be judged: exit-code-2 material.

    Args:
        options: Options fixture.

    Returns:
        None.
    """
    with pytest.raises(EnvironmentProblem, match="boot: the desktop shell did not start"):
        capture_with(options, FakeRunner(boot_error=StepError("the desktop shell did not start")))


# --- command line, path guard, exit codes ------------------------------------------------------------


@pytest.fixture
def project_out() -> Iterator[Path]:
    """
    Provide an output directory inside the project tree (the guard requires that).

    Yields:
        A path below ``.build`` that is removed afterwards.
    """
    path = PROJECT_ROOT / ".build" / f"pytest-capture-{uuid.uuid4().hex[:8]}"
    yield path
    shutil.rmtree(path, ignore_errors=True)


def test_guard_accepts_paths_inside_the_project_and_rejects_the_rest(tmp_path: Path) -> None:
    """
    Inside is fine; outside, the root itself, ``..`` traversal and a sibling directory
    whose name merely starts with the root's name are refused.

    Args:
        tmp_path: Pytest temporary directory.

    Returns:
        None.
    """
    assert capture.guard_output_dir(PROJECT_ROOT / ".build" / "shots") == (PROJECT_ROOT / ".build" / "shots").resolve()
    assert capture.guard_output_dir(PROJECT_ROOT / "a" / ".." / "b") == (PROJECT_ROOT / "b").resolve()
    for bad in (
        tmp_path / "out",
        PROJECT_ROOT,
        PROJECT_ROOT / ".build" / ".." / "..",
        PROJECT_ROOT / ".." / "elsewhere",
        Path(str(PROJECT_ROOT) + "_evil") / "shots",
    ):
        with pytest.raises(ValueError, match="inside the project"):
            capture.guard_output_dir(bad)


def test_guard_follows_symbolic_links_out_of_the_tree(tmp_path: Path) -> None:
    """
    A symbolic link inside the project that points outside does not smuggle the output out.

    Args:
        tmp_path: Pytest temporary directory.

    Returns:
        None.
    """
    link = PROJECT_ROOT / ".build" / f"pytest-link-{uuid.uuid4().hex[:8]}"
    link.parent.mkdir(exist_ok=True)
    try:
        link.symlink_to(tmp_path, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are not available")
    try:
        with pytest.raises(ValueError, match="inside the project"):
            capture.guard_output_dir(link / "shots")
    finally:
        link.unlink()


def test_sigterm_is_turned_into_a_clean_exit_and_restored() -> None:
    """
    Inside ``sigterm_as_exit`` the SIGTERM handler raises ``SystemExit(143)`` (so the VM
    context manager can clean up); afterwards the previous handler is back.

    Returns:
        None.
    """
    import signal

    before = signal.getsignal(signal.SIGTERM)
    with capture.sigterm_as_exit():
        handler = signal.getsignal(signal.SIGTERM)
        with pytest.raises(SystemExit) as caught:
            handler(signal.SIGTERM, None)  # type: ignore[operator]
        assert caught.value.code == 128 + int(signal.SIGTERM)
    assert signal.getsignal(signal.SIGTERM) == before


def test_display_path_never_leaks_an_absolute_location(tmp_path: Path) -> None:
    """
    Paths in the project print relative to it, all others as their bare name.

    Args:
        tmp_path: Pytest temporary directory.

    Returns:
        None.
    """
    assert capture.display_path(PROJECT_ROOT / ".build" / "vm") == ".build/vm"
    assert capture.display_path(tmp_path / "secret" / "vm") == "vm"


def test_split_names() -> None:
    """
    Comma separated lists are split and trimmed; empty entries are errors.

    Returns:
        None.
    """
    assert capture.split_names(None, "--states") is None
    assert capture.split_names("a, b", "--states") == ["a", "b"]
    for bad in ("", "a,,b", "a,"):
        with pytest.raises(ValueError, match="--states"):
            capture.split_names(bad, "--states")


def test_main_rejects_bad_options_with_exit_code_2_and_no_absolute_paths(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], project_out: Path
) -> None:
    """
    Output outside the project, an unknown state, a bad name and a missing scheme directory
    all end with exit code 2, print ``error:`` on stderr and never show an absolute path.

    Args:
        tmp_path: Pytest temporary directory.
        capsys: Output capture.
        project_out: Output directory inside the project.

    Returns:
        None.
    """
    generated = tmp_path / "gen-not-there"
    cases = [
        ["--out", str(tmp_path / "out")],
        ["--out", str(PROJECT_ROOT)],
        ["--out", str(project_out), "--states", "no-such-state"],
        ["--out", str(project_out), "--name", "Bad Name"],
        ["--out", str(project_out), "--generated", str(generated), "--states", "desktop-empty"],
        ["--out", str(project_out), "--modes", "twilight"],
    ]
    for argv in cases:
        assert capture.main(argv) == 2, argv
        captured = capsys.readouterr()
        assert captured.err.startswith("error:")
        assert str(tmp_path) not in captured.err and str(PROJECT_ROOT) not in captured.err
        assert ":\\" not in captured.err and "/home/" not in captured.err


def test_main_without_a_vm_environment_exits_2_and_writes_a_manifest(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], project_out: Path
) -> None:
    """
    With an image directory that does not exist the real ``Vm`` refuses to start (missing
    KVM, QEMU or image): exit code 2, a manifest with outcome ``environment-error`` and no
    absolute path in the message.

    Args:
        tmp_path: Pytest temporary directory.
        capsys: Output capture.
        project_out: Output directory inside the project.

    Returns:
        None.
    """
    generated = tmp_path / "generated"
    (generated / "plasma").mkdir(parents=True)
    (generated / "plasma" / "kuura-light.colors").write_text("[General]\n", encoding="utf-8")
    argv = [
        "--out", str(project_out), "--name", "kuura", "--generated", str(generated),
        "--image-dir", str(tmp_path / "no-image"), "--states", "desktop-empty", "--modes", "light",
    ]
    assert capture.main(argv) == 2
    err = capsys.readouterr().err
    assert err.startswith("error:") and str(tmp_path) not in err
    manifest = json.loads((project_out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["outcome"] == "environment-error"


def test_main_help_exits_zero() -> None:
    """
    ``--help`` prints usage and exits 0.

    Returns:
        None.
    """
    with pytest.raises(SystemExit) as caught:
        capture.main(["--help"])
    assert caught.value.code == 0


def test_print_summary_lists_every_result(capsys: pytest.CaptureFixture[str]) -> None:
    """
    The table shows mode, state, status and the summary line.

    Args:
        capsys: Output capture.

    Returns:
        None.
    """
    manifest = {
        "results": [
            {"mode": "light", "state": "a", "status": "ok", "settle_s": 1.0, "frames": 3, "duration_s": 2.0, "error": ""},
            {"mode": "dark", "state": "b", "status": "failed", "settle_s": 0.0, "frames": 0, "duration_s": 1.0, "error": "step 0: boom"},
        ],
        "summary": {"total": 2, "ok": 1, "failed": 1},
        "total_seconds": 12.3,
    }
    capture.print_summary(manifest)
    out = capsys.readouterr().out
    assert "light" in out and "failed" in out and "step 0: boom" in out and "1/2 states captured" in out


# --- the VM object ------------------------------------------------------------------------------------


def test_build_command_is_a_list_with_the_required_devices(tmp_path: Path) -> None:
    """
    The QEMU command is a list of strings (never a shell string) with KVM, host CPU, the
    virtio display at the configured resolution, the tablet, no network, the snapshot
    switch, the fixed clock and the sockets in the run directory.

    Args:
        tmp_path: Pytest temporary directory.

    Returns:
        None.
    """
    config = VmConfig(image_dir=tmp_path / "img", resolution=(2560, 1440), rtc_base="2026-09-25T12:00:00")
    command = vm.build_command(config, tmp_path / "run")
    assert all(isinstance(part, str) for part in command)
    joined = " ".join(command)
    for expected in ("-accel kvm", "-cpu host", "-snapshot", "-nic none", "-display none", "-m 4096", "-smp 4",
                     "virtio-vga,xres=2560,yres=1440", "usb-tablet", "base=2026-09-25T12:00:00,clock=vm", "-no-reboot"):
        assert expected in joined, expected
    assert any(part.startswith("unix:") and part.endswith("qmp.sock,server=on,wait=off") for part in command)
    assert any("qga.sock" in part for part in command)


def test_build_command_escapes_commas_in_paths(tmp_path: Path) -> None:
    """
    A comma in a path would end a QEMU option value; it is doubled, which is QEMU's escape.

    Args:
        tmp_path: Pytest temporary directory.

    Returns:
        None.
    """
    config = VmConfig(image_dir=tmp_path / "a,b")
    command = vm.build_command(config, tmp_path / "run")
    drive = command[command.index("-drive") + 1]
    assert "a,,b" in drive and drive.endswith("if=virtio,format=raw")


@pytest.mark.parametrize(
    "change",
    [
        {"rtc_base": "2026-09-25"},
        {"rtc_base": "2026-09-25T12:00:00; rm"},
        {"resolution": (100, 100)},
        {"resolution": (99999, 1440)},
        {"memory_mib": 16},
        {"cpus": 0},
    ],
)
def test_vm_config_validation_rejects_values_that_reach_the_command_line(tmp_path: Path, change: dict[str, Any]) -> None:
    """
    Malformed clock, resolution, memory or CPU values are ValueErrors.

    Args:
        tmp_path: Pytest temporary directory.
        change: The bad field value.

    Returns:
        None.
    """
    with pytest.raises(ValueError):
        VmConfig(image_dir=tmp_path, **change).validate()


def test_preflight_names_missing_files_without_directories(tmp_path: Path) -> None:
    """
    Missing image files and a missing QEMU binary are ``VmEnvironmentError`` naming only
    the file or program.

    Args:
        tmp_path: Pytest temporary directory.

    Returns:
        None.
    """
    image = tmp_path / "secret-dir"
    image.mkdir()
    machine = Vm(VmConfig(image_dir=image, qemu_binary=sys.executable, require_kvm=False))
    with pytest.raises(VmEnvironmentError, match="root.img is missing") as caught:
        machine._preflight()
    assert "secret-dir" not in str(caught.value)

    absent = Vm(VmConfig(image_dir=image, qemu_binary="no-such-qemu-binary", require_kvm=False))
    with pytest.raises(VmEnvironmentError, match="no-such-qemu-binary"):
        absent._preflight()


@pytest.mark.skipif(ON_WINDOWS, reason="POSIX permissions")
def test_run_directory_is_private(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    The runtime directory (sockets, overlay) is created with mode 0700.

    Args:
        tmp_path: Pytest temporary directory.
        monkeypatch: Pytest monkeypatch.

    Returns:
        None.
    """
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    machine = Vm(VmConfig(image_dir=tmp_path))
    run_dir = machine._make_run_dir()
    try:
        assert stat.S_IMODE(run_dir.stat().st_mode) == 0o700
    finally:
        shutil.rmtree(run_dir)


def test_summarise_resources_math() -> None:
    """
    CPU cores, seconds, peak memory and minimum free memory come out of the samples; too
    few samples give an empty summary.

    Returns:
        None.
    """
    samples = [
        {"t": 0.0, "proc_cpu_s": 0.0, "rss_mb": 100.0, "sys_busy": 0.0, "sys_total": 0.0, "mem_avail_mb": 900.0},
        {"t": 10.0, "proc_cpu_s": 15.0, "rss_mb": 300.0, "sys_busy": 20.0, "sys_total": 100.0, "mem_avail_mb": 700.0},
    ]
    summary = vm.summarise_resources(samples, 0.0, 10.0)
    assert summary["qemu_avg_cores"] == 1.5 and summary["qemu_cpu_seconds"] == 15.0
    assert summary["system_busy_pct"] == 20.0 and summary["qemu_peak_rss_mb"] == 300
    assert summary["host_mem_available_min_mb"] == 700 and summary["host_mem_available_start_mb"] == 900
    assert vm.summarise_resources(samples[:1], 0.0, 10.0) == {}
    assert vm.summarise_resources(samples, 20.0, 30.0) == {}


def test_host_summary_has_a_cpu_count() -> None:
    """
    The host summary always reports the logical CPU count.

    Returns:
        None.
    """
    assert vm.host_summary()["cpu_count"] >= 1


def write_fake_qemu(tmp_path: Path, body: str) -> Path:
    """
    Create a shell script that stands in for QEMU.

    Args:
        tmp_path: Pytest temporary directory.
        body: Script text after the shebang line.

    Returns:
        The path of the executable script.
    """
    script = tmp_path / "fake-qemu"
    script.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    script.chmod(0o755)
    return script


def make_image_dir(tmp_path: Path) -> Path:
    """
    Create an image directory with the three (empty) files ``Vm`` checks for.

    Args:
        tmp_path: Pytest temporary directory.

    Returns:
        The directory.
    """
    image = tmp_path / "image"
    image.mkdir()
    for name in ("root.img", "vmlinuz", "initramfs.img"):
        (image / name).write_bytes(b"")
    return image


def process_exists(pid: int) -> bool:
    """
    Tell whether a process still exists.

    Args:
        pid: Process id.

    Returns:
        True if signal 0 can be delivered.
    """
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


@pytest.mark.skipif(ON_WINDOWS, reason="needs POSIX processes and UNIX sockets")
def test_a_boot_that_times_out_leaves_no_process_and_no_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    QEMU that starts but never opens its sockets: ``VmBootError`` after the timeout, the
    process (and its group) is gone and the runtime directory is deleted.

    Args:
        tmp_path: Pytest temporary directory.
        monkeypatch: Pytest monkeypatch.

    Returns:
        None.
    """
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))
    pid_file = tmp_path / "pid"
    script = write_fake_qemu(tmp_path, f'echo $$ > "{pid_file}"\nexec sleep 60\n')
    config = VmConfig(image_dir=make_image_dir(tmp_path), qemu_binary=str(script), require_kvm=False, boot_timeout_s=1.0)
    with pytest.raises(VmBootError):
        with Vm(config):
            pytest.fail("the body must not run when the boot fails")
    pid = int(pid_file.read_text())
    deadline = time.monotonic() + 5
    while process_exists(pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not process_exists(pid)
    assert list(scratch.glob("vm-*")) == []


@pytest.mark.skipif(ON_WINDOWS, reason="needs POSIX processes and UNIX sockets")
def test_a_qemu_that_exits_at_once_is_reported_quickly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    QEMU that dies immediately does not make the harness wait for the full timeout.

    Args:
        tmp_path: Pytest temporary directory.
        monkeypatch: Pytest monkeypatch.

    Returns:
        None.
    """
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))
    script = write_fake_qemu(tmp_path, "echo 'qemu: bad option' >&2\nexit 3\n")
    config = VmConfig(image_dir=make_image_dir(tmp_path), qemu_binary=str(script), require_kvm=False, boot_timeout_s=120.0)
    started = time.monotonic()
    with pytest.raises(VmBootError, match="exited"):
        Vm(config).__enter__()
    assert time.monotonic() - started < 20
    assert list(scratch.glob("vm-*")) == []


@pytest.mark.skipif(ON_WINDOWS, reason="needs POSIX processes")
def test_an_exception_in_the_body_still_stops_the_vm(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Whatever ends the ``with`` block (here an exception raised by the caller), QEMU's whole
    process group is killed and the runtime directory removed.

    Args:
        tmp_path: Pytest temporary directory.
        monkeypatch: Pytest monkeypatch.

    Returns:
        None.
    """
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))
    pids: list[int] = []

    class StartedVm(Vm):
        """A VM whose ``start`` runs a plain ``sleep`` instead of QEMU."""

        def start(self) -> None:
            """Start a stand-in process in its own process group."""
            self._make_run_dir()
            self._process = subprocess.Popen(["sleep", "60"], start_new_session=True)
            pids.append(self._process.pid)

    with pytest.raises(RuntimeError, match="body failed"):
        with StartedVm(VmConfig(image_dir=tmp_path)):
            assert process_exists(pids[0])
            raise RuntimeError("body failed")
    assert not process_exists(pids[0])
    assert list(scratch.glob("vm-*")) == []


def test_stop_is_safe_before_start_and_twice(tmp_path: Path) -> None:
    """
    ``stop`` on a VM that never started, and a second ``stop``, do nothing and do not fail.

    Args:
        tmp_path: Pytest temporary directory.

    Returns:
        None.
    """
    machine = Vm(VmConfig(image_dir=tmp_path))
    machine.stop()
    machine.stop()
    assert machine.is_alive() is False and machine.serial_tail() == []
