"""
Tests for harness.shots.runner: settle logic, resets, steps, modes and frame comparison.

No VM is involved. ``FakeDesktop`` plays the screen, the input devices and the guest at
once: the "screen" is a short byte string that changes a scripted time after an action,
and time is a fake clock that only advances when the runner sleeps.
"""

from __future__ import annotations

import struct
import zlib
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from harness.shots.diff import Rect
from harness.shots.guest import ExecResult, GuestUser
from harness.shots.qmp import QmpError
from harness.shots.runner import (
    Runner,
    StepError,
    _differs_outside_mask_rows,
    _png_scanlines,
    frames_match,
)
from harness.shots.states import Mode, Settings, State, Step

PANEL_CLOCK = [Rect(2300, 1340, 2560, 1440)]


class FakeClock:
    """A clock that advances only when ``sleep`` is called."""

    def __init__(self) -> None:
        self.now = 0.0

    def time(self) -> float:
        """
        Return the current fake time.

        Returns:
            Seconds since the start of the test.
        """
        return self.now

    def sleep(self, seconds: float) -> None:
        """
        Advance the fake time.

        Args:
            seconds: How far to advance.
        """
        self.now += seconds


class FakeDesktop:
    """
    Screen, input and guest in one fake.

    Attributes:
        content: What the screen shows now (bytes; a real picture in miniature).
        rules: Maps an action ``(kind, value)`` to a list of ``(delay, new content)``;
            the change appears ``delay`` fake seconds after the action.
        log: Every input action and guest call in order, as ``(kind, value)``.
        files: Files written into the guest by path.
        exit_codes: Exit code per program name for ``run_as_user(wait_exit=True)``.
        running: Answers of ``process_running``, consumed one by one (then True).
        frame_fn: If set, ``frame_fn(n)`` gives the picture of the n-th screendump
            (1-based) and overrides ``content``.
        tick: Append a per-screendump counter to every picture, like a clock that changes
            all the time (the stand-in for the masked panel clock).
        fail_keys: Raise ``QmpError`` when a key is sent.
    """

    def __init__(self, clock: FakeClock, content: bytes = b"desktop") -> None:
        self.clock = clock
        self.content = content
        self.rules: dict[tuple[str, Any], list[tuple[float, bytes]]] = {}
        self.log: list[tuple[str, Any]] = []
        self.files: dict[str, bytes] = {}
        self.exit_codes: dict[str, int] = {}
        self.running: list[bool] = []
        self.frame_fn: Callable[[int], bytes] | None = None
        self.tick = False
        self.fail_keys = False
        self.dumps = 0
        self.user = GuestUser()
        self._pending: list[tuple[float, bytes]] = []

    def _act(self, kind: str, value: Any) -> None:
        """
        Record an action and schedule the picture changes it causes.

        Args:
            kind: Action kind (``key``, ``run`` ...).
            value: Its value.
        """
        self.log.append((kind, value))
        for delay, content in self.rules.get((kind, value), []):
            self._pending.append((self.clock.now + delay, content))

    def screendump(self, path: Path) -> None:
        """
        Write the current picture to ``path``.

        Args:
            path: Destination file.
        """
        self.dumps += 1
        due = [item for item in self._pending if item[0] <= self.clock.now]
        for item in sorted(due, key=lambda entry: entry[0]):
            self.content = item[1]
        self._pending = [item for item in self._pending if item[0] > self.clock.now]
        picture = self.frame_fn(self.dumps) if self.frame_fn else self.content
        if self.tick:
            picture += b"|" + str(self.dumps).encode()
        path.write_bytes(picture)

    def send_keys(self, chord: str) -> None:
        """
        Record a key chord.

        Args:
            chord: The chord.

        Raises:
            QmpError: if ``fail_keys`` is set.
        """
        if self.fail_keys:
            raise QmpError("QMP command 'input-send-event' failed: nope")
        self._act("key", chord)

    def type_text(self, text: str) -> None:
        """
        Record typed text.

        Args:
            text: The text.
        """
        self._act("type", text)

    def pointer_move(self, x: int, y: int) -> None:
        """
        Record a pointer move.

        Args:
            x: Column.
            y: Row.
        """
        self._act("move", (x, y))

    def pointer_click(self, x: int, y: int) -> None:
        """
        Record a click.

        Args:
            x: Column.
            y: Row.
        """
        self._act("click", (x, y))

    def run_as_user(self, argv: list[str], wait_exit: bool = False, timeout: float = 30.0) -> ExecResult | None:
        """
        Record a program start.

        Args:
            argv: The command.
            wait_exit: Whether the caller waits.
            timeout: Ignored.

        Returns:
            An ``ExecResult`` when waiting, else None.
        """
        self._act("run", argv[0])
        self.log.append(("run-wait", wait_exit))
        if wait_exit:
            return ExecResult(self.exit_codes.get(argv[0], 0), "", "")
        return None

    def write_file(self, path: str, data: bytes) -> None:
        """
        Record a file written into the guest.

        Args:
            path: Guest path.
            data: Content.
        """
        self.files[path] = data
        self.log.append(("write", path))

    def process_running(self, name: str) -> bool:
        """
        Tell whether a process runs (scripted).

        Args:
            name: Process name.

        Returns:
            The next scripted answer, True when the script is used up.
        """
        return self.running.pop(0) if self.running else True


def make_settings(frames: int = 2, timeout: float = 10.0, reset: tuple[Step, ...] = ()) -> Settings:
    """
    Build settings for a test.

    Args:
        frames: ``settle_frames``.
        timeout: ``settle_timeout_s``.
        reset: The reset steps.

    Returns:
        The settings.
    """
    return Settings((2560, 1440), frames, 1.0, timeout, "2026-09-25T12:00:00", reset)


def strip_tick(picture: bytes) -> bytes:
    """
    Remove the per-screendump counter (the "masked clock") from a picture.

    Args:
        picture: A picture as written by ``FakeDesktop``.

    Returns:
        The picture without the counter.
    """
    return picture.split(b"|")[0]


def fake_matcher(first: Path, second: Path, masks: Any) -> bool:
    """
    Compare two fake pictures the way ``frames_match`` compares real ones.

    Args:
        first: One picture file.
        second: The other picture file.
        masks: Masks; when any exist the per-screendump counter is ignored.

    Returns:
        True if the pictures are equal (outside the masks).
    """
    a, b = first.read_bytes(), second.read_bytes()
    return strip_tick(a) == strip_tick(b) if masks else a == b


def make_runner(
    tmp_path: Path,
    desktop: FakeDesktop,
    clock: FakeClock,
    settings: Settings,
    cpu_probe: Callable[[], tuple[int, int]] | None = None,
) -> Runner:
    """
    Build a runner on the fakes.

    Args:
        tmp_path: Scratch directory.
        desktop: The fake desktop.
        clock: The fake clock.
        settings: The settings.
        cpu_probe: Guest CPU probe, or None for the frame criterion alone.

    Returns:
        The runner.
    """
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    return Runner(desktop, desktop, settings, work, matcher=fake_matcher, clock=clock.time, sleep=clock.sleep, cpu_probe=cpu_probe)


def scripted_cpu(busy_fraction: Callable[[int], float]) -> Callable[[], tuple[int, int]]:
    """
    Build a fake CPU probe whose n-th reading closes an interval with a given busy share.

    Args:
        busy_fraction: Maps the reading number (1 for the first interval) to the share of
            busy time in the interval ending at that reading.

    Returns:
        A probe returning cumulative ``(busy, idle)`` counters.
    """
    counters = {"calls": 0, "busy": 0, "idle": 0}

    def probe() -> tuple[int, int]:
        if counters["calls"] > 0:
            fraction = busy_fraction(counters["calls"])
            counters["busy"] += round(100 * fraction)
            counters["idle"] += round(100 * (1 - fraction))
        counters["calls"] += 1
        return counters["busy"], counters["idle"]

    return probe


@pytest.fixture
def clock() -> FakeClock:
    """
    Provide a fresh fake clock.

    Returns:
        The clock.
    """
    return FakeClock()


@pytest.fixture
def desktop(clock: FakeClock) -> FakeDesktop:
    """
    Provide a fresh fake desktop.

    Args:
        clock: The fake clock.

    Returns:
        The desktop.
    """
    return FakeDesktop(clock)


# --- settle ----------------------------------------------------------------------------


def test_settle_is_stable_after_n_identical_frames(tmp_path: Path, clock: FakeClock, desktop: FakeDesktop) -> None:
    """
    With ``settle_frames = 3`` an unchanging screen settles on the third frame, two poll
    intervals after the first.

    Args:
        tmp_path: Pytest temporary directory.
        clock: Fake clock.
        desktop: Fake desktop.

    Returns:
        None.
    """
    runner = make_runner(tmp_path, desktop, clock, make_settings(frames=3))
    result = runner.settle([])
    assert result.stable and result.frames == 3
    assert result.seconds == pytest.approx(2.0)


def test_settle_waits_out_a_screen_that_keeps_changing_then_stops(tmp_path: Path, clock: FakeClock, desktop: FakeDesktop) -> None:
    """
    Frames that change for three polls and then stay the same settle one frame after the
    last change (two identical frames are needed).

    Args:
        tmp_path: Pytest temporary directory.
        clock: Fake clock.
        desktop: Fake desktop.

    Returns:
        None.
    """
    desktop.frame_fn = lambda n: b"c%d" % min(n, 3)
    runner = make_runner(tmp_path, desktop, clock, make_settings(frames=2))
    result = runner.settle([])
    assert result.stable and result.frames == 4


def test_settle_times_out_on_flapping_frames(tmp_path: Path, clock: FakeClock, desktop: FakeDesktop) -> None:
    """
    A screen that alternates between two pictures never has two identical frames in a
    row, so the settle ends with a timeout (never with a false "stable").

    Args:
        tmp_path: Pytest temporary directory.
        clock: Fake clock.
        desktop: Fake desktop.

    Returns:
        None.
    """
    desktop.frame_fn = lambda n: b"A" if n % 2 else b"B"
    runner = make_runner(tmp_path, desktop, clock, make_settings(frames=2, timeout=10))
    result = runner.settle([])
    assert not result.stable and result.reason == "timeout"
    assert result.seconds >= 10
    assert result.frames >= 10


def test_settle_times_out_on_a_screen_that_never_stops_changing(tmp_path: Path, clock: FakeClock, desktop: FakeDesktop) -> None:
    """
    Frames that are new every time (an endless animation) time out.

    Args:
        tmp_path: Pytest temporary directory.
        clock: Fake clock.
        desktop: Fake desktop.

    Returns:
        None.
    """
    desktop.frame_fn = lambda n: b"frame-%d" % n
    runner = make_runner(tmp_path, desktop, clock, make_settings(timeout=5))
    assert not runner.settle([]).stable


def test_settle_ignores_changes_inside_the_mask_only(tmp_path: Path, clock: FakeClock, desktop: FakeDesktop) -> None:
    """
    Frames that differ only in the masked part (a ticking clock) count as identical when a
    mask is given, and as different without one.

    Args:
        tmp_path: Pytest temporary directory.
        clock: Fake clock.
        desktop: Fake desktop.

    Returns:
        None.
    """
    desktop.tick = True
    runner = make_runner(tmp_path, desktop, clock, make_settings(frames=3, timeout=8))
    assert runner.settle(PANEL_CLOCK).stable
    desktop.dumps = 0
    assert not runner.settle([]).stable


def test_settle_waits_for_the_guest_to_go_quiet(tmp_path: Path, clock: FakeClock, desktop: FakeDesktop) -> None:
    """
    THE STARVED-GUEST TRAP: an application that makes no visible progress for a while is
    not finished. Identical frames only count while the guest CPU is quiet; here the
    guest is busy for three polls, so the settle needs a fourth.

    Args:
        tmp_path: Pytest temporary directory.
        clock: Fake clock.
        desktop: Fake desktop.

    Returns:
        None.
    """
    runner = make_runner(tmp_path, desktop, clock, make_settings(frames=2), cpu_probe=scripted_cpu(lambda n: 0.9 if n <= 3 else 0.01))
    result = runner.settle([])
    assert result.stable and result.frames == 4

    # Without a probe the same (unchanging) screen settles as soon as two frames agree.
    plain = make_runner(tmp_path, desktop, clock, make_settings(frames=2))
    assert plain.settle([]).frames == 2


def test_settle_times_out_when_the_guest_never_goes_quiet(tmp_path: Path, clock: FakeClock, desktop: FakeDesktop) -> None:
    """
    A screen that does not change but a guest that stays busy is not settled.

    Args:
        tmp_path: Pytest temporary directory.
        clock: Fake clock.
        desktop: Fake desktop.

    Returns:
        None.
    """
    runner = make_runner(tmp_path, desktop, clock, make_settings(timeout=6), cpu_probe=scripted_cpu(lambda n: 0.5))
    result = runner.settle([])
    assert not result.stable and result.reason == "timeout"


def test_settle_ignores_a_probe_that_fails_but_not_a_lost_connection(tmp_path: Path, clock: FakeClock, desktop: FakeDesktop) -> None:
    """
    If the guest agent cannot answer for a moment the frame criterion decides alone; a lost
    connection is still an error.

    Args:
        tmp_path: Pytest temporary directory.
        clock: Fake clock.
        desktop: Fake desktop.

    Returns:
        None.
    """

    def flaky() -> tuple[int, int]:
        raise TimeoutError("agent busy")

    runner = make_runner(tmp_path, desktop, clock, make_settings(frames=2), cpu_probe=flaky)
    assert runner.settle([]).stable

    def gone() -> tuple[int, int]:
        raise ConnectionError("peer closed the connection")

    with pytest.raises(ConnectionError):
        make_runner(tmp_path, desktop, clock, make_settings(), cpu_probe=gone).settle([])


def test_guest_quiet_threshold() -> None:
    """
    Missing readings and no elapsed time count as quiet; the busy share must be at most
    ``MAX_BUSY_FRACTION``.

    Returns:
        None.
    """
    assert Runner._guest_quiet(None, (10, 10)) is True
    assert Runner._guest_quiet((5, 5), (5, 5)) is True
    assert Runner._guest_quiet((0, 0), (15, 85)) is True
    assert Runner._guest_quiet((0, 0), (16, 84)) is False
    assert Runner._guest_quiet((0, 0), (100, 0)) is False


def test_settle_needs_the_screen_to_change_from_the_reference(tmp_path: Path, clock: FakeClock, desktop: FakeDesktop) -> None:
    """
    THE STARTUP TRAP: right after an action the screen still shows the old picture. Two
    identical OLD frames must not count as settled when a reference is given; the settle
    waits for the new picture and then for it to be stable.

    Args:
        tmp_path: Pytest temporary directory.
        clock: Fake clock.
        desktop: Fake desktop.

    Returns:
        None.
    """
    runner = make_runner(tmp_path, desktop, clock, make_settings(frames=2, timeout=30))
    reference = tmp_path / "reference.png"
    reference.write_bytes(b"desktop")
    desktop.frame_fn = lambda n: b"desktop" if n <= 5 else b"menu"

    guarded = runner.settle([], reference=reference)
    assert guarded.stable and guarded.frames == 7  # 5 old frames, then 2 identical new ones
    assert runner._last_frame.read_bytes() == b"menu"

    # Without the reference the same screen "settles" on the old picture: the trap.
    desktop.dumps = 0
    unguarded = runner.settle([])
    assert unguarded.stable and unguarded.frames == 2
    assert runner._last_frame.read_bytes() == b"desktop"


def test_settle_reports_a_screen_that_never_changed(tmp_path: Path, clock: FakeClock, desktop: FakeDesktop) -> None:
    """
    If the screen stays equal to the reference until the timeout, the result says so.

    Args:
        tmp_path: Pytest temporary directory.
        clock: Fake clock.
        desktop: Fake desktop.

    Returns:
        None.
    """
    runner = make_runner(tmp_path, desktop, clock, make_settings(timeout=6))
    reference = tmp_path / "reference.png"
    reference.write_bytes(b"desktop")
    result = runner.settle([], reference=reference)
    assert not result.stable and result.reason == "never changed"


def test_wait_for_desktop_polls_for_the_shell_then_settles(tmp_path: Path, clock: FakeClock, desktop: FakeDesktop) -> None:
    """
    The boot wait asks for the shell process until it exists, then uses a slower, stricter
    settle (at least three frames).

    Args:
        tmp_path: Pytest temporary directory.
        clock: Fake clock.
        desktop: Fake desktop.

    Returns:
        None.
    """
    desktop.running = [False, False, True]
    runner = make_runner(tmp_path, desktop, clock, make_settings(frames=2))
    result = runner.wait_for_desktop([])
    assert result.stable and result.frames == 3
    assert clock.now >= 1.0 + 2 * 2.0  # two 0.5 s polls, then two 2 s frame intervals


def test_wait_for_desktop_fails_when_the_shell_never_starts(tmp_path: Path, clock: FakeClock, desktop: FakeDesktop) -> None:
    """
    A shell that never appears is a StepError after the timeout.

    Args:
        tmp_path: Pytest temporary directory.
        clock: Fake clock.
        desktop: Fake desktop.

    Returns:
        None.
    """
    desktop.process_running = lambda name: False  # type: ignore[method-assign]
    runner = make_runner(tmp_path, desktop, clock, make_settings())
    with pytest.raises(StepError, match="did not start"):
        runner.wait_for_desktop([], timeout=3)


# --- states ----------------------------------------------------------------------------

LIGHT = Mode("light", "light")
RESET = (Step("key", "escape"), Step("key", "escape"))


def state(name: str, *steps: Step) -> State:
    """
    Build a state that runs in the light mode.

    Args:
        name: State name.
        *steps: Its steps.

    Returns:
        The state.
    """
    return State(name, "A state.", tuple(steps), ("light",))


def test_run_state_executes_reset_then_steps_and_captures_the_settled_screen(tmp_path: Path, clock: FakeClock, desktop: FakeDesktop) -> None:
    """
    Order: reset keys, then the state's steps; the shot shows the settled state; the
    result carries timings.

    Args:
        tmp_path: Pytest temporary directory.
        clock: Fake clock.
        desktop: Fake desktop.

    Returns:
        None.
    """
    desktop.rules[("key", "meta+w")] = [(1.5, b"overview")]
    runner = make_runner(tmp_path, desktop, clock, make_settings(reset=RESET))
    shot = tmp_path / "shots" / "light" / "overview.png"
    shot.parent.mkdir(parents=True)
    result = runner.run_state(state("overview", Step("key", "meta+w"), Step("settle", True)), LIGHT, [], shot, "light/overview.png")
    assert result.status == "ok" and result.error == ""
    assert result.shot == "light/overview.png"
    assert shot.read_bytes() == b"overview"
    assert result.frames >= 3 and result.settle_s > 0
    assert [entry for entry in desktop.log if entry[0] == "key"] == [("key", "escape"), ("key", "escape"), ("key", "meta+w")]


def test_reset_between_states_restores_the_empty_desktop(tmp_path: Path, clock: FakeClock, desktop: FakeDesktop) -> None:
    """
    The reset steps run before EVERY state: after the first state opens an overlay, the
    second state (an empty one) starts from a closed overlay because the reset's escape
    key closed it before anything was captured.

    Args:
        tmp_path: Pytest temporary directory.
        clock: Fake clock.
        desktop: Fake desktop.

    Returns:
        None.
    """
    desktop.rules[("key", "meta+w")] = [(1.0, b"overview")]
    desktop.rules[("key", "escape")] = [(0.5, b"desktop")]
    runner = make_runner(tmp_path, desktop, clock, make_settings(reset=RESET))
    out = tmp_path / "shots"
    out.mkdir()
    first = runner.run_state(state("overview", Step("key", "meta+w"), Step("settle", True)), LIGHT, [], out / "overview.png", "overview.png")
    assert first.status == "ok" and (out / "overview.png").read_bytes() == b"overview"
    second = runner.run_state(state("desktop-empty"), LIGHT, [], out / "empty.png", "empty.png")
    assert second.status == "ok"
    assert (out / "empty.png").read_bytes() == b"desktop"
    keys = [value for kind, value in desktop.log if kind == "key"]
    # escape, escape | meta+w | escape, escape (the second state's reset)
    assert keys == ["escape", "escape", "meta+w", "escape", "escape"]


def test_a_failed_state_saves_a_diagnostic_and_the_next_state_still_runs(tmp_path: Path, clock: FakeClock, desktop: FakeDesktop) -> None:
    """
    A step that changes nothing ends in "never changed": the state fails with the step
    index in the message, ``<state>.FAILED.png`` is written next to the shot, and the
    following state is captured normally.

    Args:
        tmp_path: Pytest temporary directory.
        clock: Fake clock.
        desktop: Fake desktop.

    Returns:
        None.
    """
    desktop.rules[("key", "meta+w")] = [(0.5, b"overview")]
    runner = make_runner(tmp_path, desktop, clock, make_settings(timeout=5, reset=RESET))
    out = tmp_path / "light"
    out.mkdir()
    broken = state("search-open", Step("key", "alt+space"), Step("settle", True))
    failed = runner.run_state(broken, LIGHT, [], out / "search-open.png", "light/search-open.png")
    assert failed.status == "failed"
    assert "step 1" in failed.error and "never changed" in failed.error
    assert failed.shot == ""
    assert (out / "search-open.FAILED.png").is_file()
    assert failed.diagnostic == "light/search-open.FAILED.png"
    assert not (out / "search-open.png").exists()

    good = runner.run_state(state("overview", Step("key", "meta+w"), Step("settle", True)), LIGHT, [], out / "overview.png", "light/overview.png")
    assert good.status == "ok" and (out / "overview.png").is_file()


def test_a_trailing_action_gets_an_implicit_settle(tmp_path: Path, clock: FakeClock, desktop: FakeDesktop) -> None:
    """
    A state that ends with an action and no explicit settle is still captured only after
    the screen changed and stopped changing.

    Args:
        tmp_path: Pytest temporary directory.
        clock: Fake clock.
        desktop: Fake desktop.

    Returns:
        None.
    """
    desktop.rules[("click", (5, 5))] = [(3.0, b"menu")]
    runner = make_runner(tmp_path, desktop, clock, make_settings(timeout=20))
    shot = tmp_path / "menu.png"
    result = runner.run_state(state("menubar-open", Step("click", (5, 5))), LIGHT, [], shot, "menu.png")
    assert result.status == "ok"
    assert shot.read_bytes() == b"menu"


def test_wait_step_sleeps_and_needs_no_settle(tmp_path: Path, clock: FakeClock, desktop: FakeDesktop) -> None:
    """
    A state made only of a wait sleeps that long and is captured without a change check.

    Args:
        tmp_path: Pytest temporary directory.
        clock: Fake clock.
        desktop: Fake desktop.

    Returns:
        None.
    """
    runner = make_runner(tmp_path, desktop, clock, make_settings())
    before = clock.now
    shot = tmp_path / "w.png"
    result = runner.run_state(state("waiting", Step("wait", 2.5)), LIGHT, [], shot, "w.png")
    assert result.status == "ok"
    assert clock.now - before >= 2.5


def test_run_step_starts_detached_by_default_and_waits_on_request(tmp_path: Path, clock: FakeClock, desktop: FakeDesktop) -> None:
    """
    ``run`` does not wait unless ``wait_exit`` is set; a waited program that fails fails
    the state, an unwaited one is not asked for its status.

    Args:
        tmp_path: Pytest temporary directory.
        clock: Fake clock.
        desktop: Fake desktop.

    Returns:
        None.
    """
    desktop.rules[("run", "dolphin")] = [(1.0, b"files")]
    runner = make_runner(tmp_path, desktop, clock, make_settings())
    ok = runner.run_state(state("files-window", Step("run", ("dolphin", "Documents")), Step("settle", True)), LIGHT, [], tmp_path / "a.png", "a.png")
    assert ok.status == "ok"
    assert ("run-wait", False) in desktop.log

    desktop.exit_codes["cleanup"] = 3
    bad = runner.run_state(state("cleanup-fails", Step("run", ("cleanup",), True)), LIGHT, [], tmp_path / "b.png", "b.png")
    assert bad.status == "failed" and "step 0" in bad.error and "exited with an error" in bad.error


def test_input_errors_fail_the_state_with_the_step_index(tmp_path: Path, clock: FakeClock, desktop: FakeDesktop) -> None:
    """
    A QMP error while sending a key fails the state (it does not abort the run) and names
    the step.

    Args:
        tmp_path: Pytest temporary directory.
        clock: Fake clock.
        desktop: Fake desktop.

    Returns:
        None.
    """
    desktop.fail_keys = True
    runner = make_runner(tmp_path, desktop, clock, make_settings())
    result = runner.run_state(state("overview", Step("key", "meta+w"), Step("settle", True)), LIGHT, [], tmp_path / "o.png", "o.png")
    assert result.status == "failed" and "step 0" in result.error and "input-send-event" in result.error


def test_a_lost_connection_is_not_swallowed(tmp_path: Path, clock: FakeClock, desktop: FakeDesktop) -> None:
    """
    ConnectionError means the VM is gone; it propagates so the caller can stop the run.

    Args:
        tmp_path: Pytest temporary directory.
        clock: Fake clock.
        desktop: Fake desktop.

    Returns:
        None.
    """

    def broken(path: Path) -> None:
        raise ConnectionError("peer closed the connection")

    desktop.screendump = broken  # type: ignore[method-assign]
    runner = make_runner(tmp_path, desktop, clock, make_settings())
    with pytest.raises(ConnectionError):
        runner.run_state(state("desktop-empty"), LIGHT, [], tmp_path / "x.png", "x.png")


# --- modes -----------------------------------------------------------------------------


def make_generated(tmp_path: Path) -> Path:
    """
    Create a generated-directory with a dark scheme file.

    Args:
        tmp_path: Pytest temporary directory.

    Returns:
        The directory.
    """
    generated = tmp_path / "generated"
    (generated / "plasma").mkdir(parents=True)
    (generated / "plasma" / "kuura-dark.colors").write_bytes(b"[General]\nName=kuura\n")
    return generated


def test_apply_mode_writes_the_scheme_activates_it_and_waits_for_the_change(tmp_path: Path, clock: FakeClock, desktop: FakeDesktop) -> None:
    """
    The generated file lands in the desktop user's colour scheme directory, the tool is
    run and waited for, and the settle needs the screen to change.

    Args:
        tmp_path: Pytest temporary directory.
        clock: Fake clock.
        desktop: Fake desktop.

    Returns:
        None.
    """
    desktop.rules[("run", "plasma-apply-colorscheme")] = [(1.0, b"dark-desktop")]
    runner = make_runner(tmp_path, desktop, clock, make_settings())
    result = runner.apply_mode(Mode("dark", "dark"), make_generated(tmp_path), "kuura", [])
    assert result.stable
    assert desktop.files == {"/home/desktop/.local/share/color-schemes/kuura-dark.colors": b"[General]\nName=kuura\n"}
    assert [entry[0] for entry in desktop.log] == ["write", "run", "run-wait"]
    assert desktop.log[2] == ("run-wait", True)


def test_apply_mode_errors(tmp_path: Path, clock: FakeClock, desktop: FakeDesktop) -> None:
    """
    A missing scheme file (message names only the file), a failing tool and a screen that
    never changes are StepErrors.

    Args:
        tmp_path: Pytest temporary directory.
        clock: Fake clock.
        desktop: Fake desktop.

    Returns:
        None.
    """
    runner = make_runner(tmp_path, desktop, clock, make_settings(timeout=5))
    with pytest.raises(StepError, match="kuura-dark.colors is missing") as missing:
        runner.apply_mode(Mode("dark", "dark"), tmp_path / "nowhere", "kuura", [])
    assert str(tmp_path) not in str(missing.value)

    generated = make_generated(tmp_path)
    desktop.exit_codes["plasma-apply-colorscheme"] = 255
    with pytest.raises(StepError, match="failed"):
        runner.apply_mode(Mode("dark", "dark"), generated, "kuura", [])

    desktop.exit_codes.clear()
    with pytest.raises(StepError, match="never changed"):
        runner.apply_mode(Mode("dark", "dark"), generated, "kuura", [])


# --- frame comparison on real PNG files ---------------------------------------------------


def make_png(width: int, height: int, pixel: Callable[[int, int], tuple[int, int, int]], depth: int = 8) -> bytes:
    """
    Encode a tiny RGB PNG (filter type 0 on every row).

    Args:
        width: Width in pixels.
        height: Height in pixels.
        pixel: Function returning the (r, g, b) of a pixel.
        depth: Bit depth written into the header (only 8 is decodable).

    Returns:
        The file content.
    """
    rows = b"".join(b"\x00" + b"".join(bytes(pixel(x, y)) for x in range(width)) for y in range(height))

    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", width, height, depth, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")


def write_pair(tmp_path: Path, second_pixel: Callable[[int, int], tuple[int, int, int]], size: tuple[int, int] = (40, 30)) -> tuple[Path, Path]:
    """
    Write a base picture and a modified one.

    Args:
        tmp_path: Pytest temporary directory.
        second_pixel: Pixel function of the second picture.
        size: Width and height of the second picture.

    Returns:
        The paths of the two files.
    """
    first, second = tmp_path / "a.png", tmp_path / "b.png"
    first.write_bytes(make_png(40, 30, lambda x, y: (10, 20, 30)))
    second.write_bytes(make_png(size[0], size[1], second_pixel))
    return first, second


def test_frames_match_identical_files_need_no_decoding(tmp_path: Path) -> None:
    """
    Equal bytes are equal frames, with or without masks (the fast path).

    Args:
        tmp_path: Pytest temporary directory.

    Returns:
        None.
    """
    first, second = write_pair(tmp_path, lambda x, y: (10, 20, 30))
    assert frames_match(first, second, [])
    assert frames_match(first, second, [Rect(0, 0, 5, 5)])


def test_frames_match_ignores_a_difference_inside_the_mask(tmp_path: Path) -> None:
    """
    Pixels that differ only inside the mask do not make the frames different (the clock).

    Args:
        tmp_path: Pytest temporary directory.

    Returns:
        None.
    """
    mask = Rect(30, 20, 40, 30)
    first, second = write_pair(tmp_path, lambda x, y: (200, 20, 30) if mask.contains(x, y) else (10, 20, 30))
    assert frames_match(first, second, [mask])
    assert not frames_match(first, second, [])


def test_frames_match_detects_a_difference_outside_the_mask(tmp_path: Path) -> None:
    """
    A changed pixel outside the mask makes the frames different, even if the mask also
    covers changed pixels.

    Args:
        tmp_path: Pytest temporary directory.

    Returns:
        None.
    """
    mask = Rect(30, 20, 40, 30)
    first, second = write_pair(tmp_path, lambda x, y: (200, 20, 30) if (mask.contains(x, y) or (x, y) == (3, 3)) else (10, 20, 30))
    assert not frames_match(first, second, [mask])
    # A change in a row that shares the mask's rows but lies left of it is caught too.
    first, second = write_pair(tmp_path, lambda x, y: (200, 20, 30) if (x, y) == (3, 22) else (10, 20, 30))
    assert not frames_match(first, second, [mask])


def test_frames_of_different_size_never_match(tmp_path: Path) -> None:
    """
    Pictures of different sizes are different frames (no crash).

    Args:
        tmp_path: Pytest temporary directory.

    Returns:
        None.
    """
    first, second = write_pair(tmp_path, lambda x, y: (10, 20, 30), size=(41, 30))
    assert not frames_match(first, second, [Rect(0, 0, 5, 5)])


def test_prescreen_only_claims_certain_differences(tmp_path: Path) -> None:
    """
    The cheap row test answers True only when a difference outside the mask rows is
    certain; a difference confined to the mask rows leaves the answer open (False).

    Args:
        tmp_path: Pytest temporary directory.

    Returns:
        None.
    """
    mask = Rect(0, 10, 40, 20)
    base = make_png(40, 30, lambda x, y: (10, 20, 30))
    outside = make_png(40, 30, lambda x, y: (99, 20, 30) if y == 3 else (10, 20, 30))
    inside = make_png(40, 30, lambda x, y: (99, 20, 30) if y == 12 else (10, 20, 30))
    edge = make_png(40, 30, lambda x, y: (99, 20, 30) if y == 19 else (10, 20, 30))
    assert _differs_outside_mask_rows(base, outside, [mask]) is True
    assert _differs_outside_mask_rows(base, inside, [mask]) is False
    assert _differs_outside_mask_rows(base, edge, [mask]) is False
    assert _differs_outside_mask_rows(base, base, [mask]) is False


def test_png_scanlines_understands_only_plain_pngs() -> None:
    """
    Garbage, a truncated file and an unsupported bit depth give None (the caller falls back
    to the exact comparison).

    Returns:
        None.
    """
    assert _png_scanlines(b"not a png") is None
    good = make_png(4, 4, lambda x, y: (1, 2, 3))
    assert _png_scanlines(good) is not None
    assert _png_scanlines(good[:40]) is None
    assert _png_scanlines(make_png(4, 4, lambda x, y: (1, 2, 3), depth=16)) is None
