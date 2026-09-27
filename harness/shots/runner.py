"""
Drives one running VM through the states of ``harness/states.toml``.

``Runner`` owns everything that happens INSIDE a boot: applying a colour mode, running
the reset steps, executing a state's steps, waiting until the screen has settled and
taking the final screenshot (QMP ``screendump``, always from the host).

The one piece of logic that decides whether a screenshot is any good is SETTLE:

* Frames are polled every ``settle_interval_s``. ``settle_frames`` consecutive frames
  that are identical outside the state's masks count as stable.
* Identical means raw PNG bytes first (fast path); when the bytes differ, the frames
  are compared with ``diff.compare_images(..., tolerance=0, max_diff_ratio=0, masks)``,
  so a ticking clock inside a mask does not keep the screen "unsettled". Because that
  comparison decodes both images (seconds in pure Python), a cheap pre-screen on the
  still-filtered PNG rows rejects frames that clearly differ outside the masks first.
* THE STARTUP TRAP: right after a program is started (or a mode is applied) the screen
  does not change for a while, so "two identical frames" would be satisfied by the
  OLD picture. Every settle that follows an action therefore also requires that the
  screen has changed from the frame that was there before the action.
* THE STARVED-GUEST TRAP: when the host is busy, an application can make no visible
  progress for several seconds (a file manager that has not listed its devices yet, a
  search box that has processed only two of five typed letters) and two identical frames
  are again the wrong answer. So a frame only counts as stable if the GUEST WAS ALSO
  QUIET while it was taken: at most ``MAX_BUSY_FRACTION`` of the guest's CPU time was
  spent since the previous poll (measured from ``/proc/stat`` through the guest agent;
  an idle desktop uses about 1 %). Without a probe the frame criterion stands alone.
* A settle that runs out of ``settle_timeout_s`` is a failed state.

Time and sleeping are injected so the logic is testable without waiting.
Standard library only.
"""

from __future__ import annotations

import shutil
import struct
import time
import zlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from harness.shots.diff import Rect, compare_images
from harness.shots.guest import ExecResult
from harness.shots.states import EFFECT_KINDS, Mode, Settings, State, Step

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

# A poll counts as "guest quiet" when at most this share of the guest's CPU time was busy
# since the previous poll. Measured idle desktops, open menus and windows use 1-2 %;
# loading applications use far more.
MAX_BUSY_FRACTION = 0.15

# Reads the guest's CPU counters: returns (busy, idle) jiffies summed over all CPUs.
CpuProbe = Callable[[], "tuple[int, int]"]


class ScreenAndInput(Protocol):
    """The parts of ``harness.shots.qmp.Qmp`` the runner uses (a fake in tests)."""

    def screendump(self, path: Path) -> None:
        """Write the current screen to a PNG file."""

    def send_keys(self, chord: str) -> None:
        """Press and release a key chord."""

    def type_text(self, text: str) -> None:
        """Type text."""

    def pointer_move(self, x: int, y: int) -> None:
        """Move the pointer to absolute pixel coordinates."""

    def pointer_click(self, x: int, y: int) -> None:
        """Move and click the left button."""


class GuestLike(Protocol):
    """The parts of ``harness.shots.guest.GuestAgent`` the runner uses (a fake in tests)."""

    user: Any

    def run_as_user(self, argv: list[str], wait_exit: bool = False, timeout: float = 30.0) -> ExecResult | None:
        """Run a program as the desktop user."""

    def write_file(self, path: str, data: bytes) -> None:
        """Write a file into the guest."""

    def process_running(self, name: str) -> bool:
        """Tell whether a process exists in the guest."""


FrameMatcher = Callable[[Path, Path, Sequence[Rect]], bool]


class StepError(RuntimeError):
    """A step of a state failed (or the screen did not settle); the message says which."""


@dataclass(frozen=True)
class SettleResult:
    """
    Outcome of one settle.

    Attributes:
        stable: True if the screen settled, False on timeout.
        seconds: Time spent waiting.
        frames: Number of frames taken.
        reason: For an unstable result, why (``"timeout"`` or ``"never changed"``).
    """

    stable: bool
    seconds: float
    frames: int
    reason: str = ""


@dataclass
class StateResult:
    """
    Outcome of one state in one mode (one entry of the manifest).

    Attributes:
        state: State name.
        mode: Mode name.
        status: ``"ok"`` or ``"failed"``.
        settle_s: Seconds spent settling (after the reset and during the state's steps).
        frames: Frames taken while settling.
        duration_s: Total seconds for the state including reset.
        shot: Path of the screenshot relative to the output directory ("" if none).
        error: Failure description (empty when ok).
        diagnostic: Path (relative to the output directory) of the ``.FAILED.png``
            saved for a failed state, "" otherwise.
    """

    state: str
    mode: str
    status: str = "ok"
    settle_s: float = 0.0
    frames: int = 0
    duration_s: float = 0.0
    shot: str = ""
    error: str = ""
    diagnostic: str = ""


def _png_scanlines(data: bytes) -> tuple[int, int, bytes] | None:
    """
    Split a PNG into its still-filtered scanlines without reconstructing pixels.

    Only the plain layout QEMU writes is understood (8 bit RGB or RGBA, not interlaced).

    Args:
        data: The whole file.

    Returns:
        ``(height, bytes per scanline including the filter byte, raw data)`` or None for
        anything else (the caller then falls back to the exact comparison).
    """
    if data[:8] != _PNG_SIGNATURE:
        return None
    position = 8
    header: tuple[int, int, int, int, int, int, int] | None = None
    idat: list[bytes] = []
    try:
        while position + 8 <= len(data):
            length, kind = struct.unpack(">I4s", data[position : position + 8])
            body = data[position + 8 : position + 8 + length]
            position += 12 + length
            if kind == b"IHDR":
                header = struct.unpack(">IIBBBBB", body)
            elif kind == b"IDAT":
                idat.append(body)
            elif kind == b"IEND":
                break
        if header is None:
            return None
        width, height, depth, colour, _compression, _filter, interlace = header
        if depth != 8 or colour not in (2, 6) or interlace != 0:
            return None
        raw = zlib.decompress(b"".join(idat))
    except (struct.error, zlib.error):
        return None
    line = 1 + width * (3 if colour == 2 else 4)
    if len(raw) != line * height:
        return None
    return height, line, raw


def _differs_outside_mask_rows(a: bytes, b: bytes, masks: Sequence[Rect]) -> bool:
    """
    Cheap "these frames DEFINITELY differ outside the masks" test.

    A filtered scanline depends only on its own pixels and those of the line above, and
    both PNGs come from the same encoder. So if a filtered scanline differs and neither
    it nor its predecessor touches a mask, real pixels differ outside every mask. The
    converse is not claimed: when all differing scanlines lie inside mask rows the
    caller must still run the exact comparison.

    Args:
        a: First PNG file content.
        b: Second PNG file content.
        masks: Mask rectangles (``y1`` exclusive).

    Returns:
        True only when a difference outside all masks is certain; False means
        "unknown, run the exact comparison".
    """
    lines_a, lines_b = _png_scanlines(a), _png_scanlines(b)
    if lines_a is None or lines_b is None or lines_a[:2] != lines_b[:2]:
        return False
    height, line, raw_a = lines_a
    raw_b = lines_b[2]
    if raw_a == raw_b:
        return False
    for row in range(height):
        start = row * line
        if raw_a[start : start + line] == raw_b[start : start + line]:
            continue
        # Row `row` may differ because pixel rows `row - 1` or `row` changed, i.e. it can
        # be explained by a mask that covers pixel rows y0..y1-1, so filtered rows y0..y1.
        if not any(mask.y0 <= row <= mask.y1 for mask in masks):
            return True
    return False


def frames_match(first: Path, second: Path, masks: Sequence[Rect]) -> bool:
    """
    Tell whether two frames are identical outside the masks.

    Args:
        first: Path of one PNG.
        second: Path of the other PNG.
        masks: Rectangles to ignore.

    Returns:
        True if the raw bytes are equal, or if the exact comparison
        (tolerance 0, ratio 0) finds no differing pixel outside the masks.
    """
    data_a, data_b = first.read_bytes(), second.read_bytes()
    if data_a == data_b:
        return True
    if not masks:
        return False
    if _differs_outside_mask_rows(data_a, data_b, masks):
        return False
    try:
        return compare_images(first, second, 0, 0.0, list(masks)).passed
    except ValueError:
        return False  # different sizes or an unsupported image: not the same frame


class Runner:
    """
    Executes modes, resets and states against one VM.

    Args:
        screen: QMP client (screendump and input).
        guest: Guest-agent client.
        settings: The ``[settings]`` table.
        work_dir: Existing directory for scratch frames (removed by the caller).
        matcher: Frame comparison used by settle; ``frames_match`` by default.
        clock: Monotonic clock (replaced in tests).
        sleep: Sleep function (replaced in tests).
        log: Progress callback receiving one line of text.
        cpu_probe: Returns ``(busy, idle)`` guest CPU counters, or None to settle on
            the frame criterion alone (see the module docstring, "starved guest").
    """

    def __init__(
        self,
        screen: ScreenAndInput,
        guest: GuestLike,
        settings: Settings,
        work_dir: Path,
        matcher: FrameMatcher = frames_match,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        log: Callable[[str], None] = lambda line: None,
        cpu_probe: CpuProbe | None = None,
    ) -> None:
        self._screen = screen
        self._guest = guest
        self._settings = settings
        self._work = work_dir
        self._matcher = matcher
        self._clock = clock
        self._sleep = sleep
        self._log = log
        self._cpu_probe = cpu_probe
        self._frame_paths = (work_dir / "frame-a.png", work_dir / "frame-b.png")
        self._last_frame = self._frame_paths[0]

    def _read_cpu(self) -> tuple[int, int] | None:
        """
        Read the guest's CPU counters.

        Returns:
            ``(busy, idle)`` or None when there is no probe or the guest agent could not
            answer this time (the frame criterion then decides alone for this poll).

        Raises:
            ConnectionError: the VM connection is gone.
        """
        if self._cpu_probe is None:
            return None
        try:
            return self._cpu_probe()
        except (TimeoutError, RuntimeError, ValueError):
            return None

    @staticmethod
    def _guest_quiet(before: tuple[int, int] | None, after: tuple[int, int] | None) -> bool:
        """
        Tell whether the guest was quiet between two CPU readings.

        Args:
            before: Earlier ``(busy, idle)`` reading, or None.
            after: Later reading, or None.

        Returns:
            True if a reading is missing (no evidence of activity), no time passed, or
            at most ``MAX_BUSY_FRACTION`` of the elapsed CPU time was busy.
        """
        if before is None or after is None:
            return True
        busy, idle = after[0] - before[0], after[1] - before[1]
        if busy + idle <= 0:
            return True
        return busy / (busy + idle) <= MAX_BUSY_FRACTION

    def settle(
        self,
        masks: Sequence[Rect],
        reference: Path | None = None,
        frames: int | None = None,
        interval: float | None = None,
    ) -> SettleResult:
        """
        Wait until the screen is stable and the guest is quiet.

        Args:
            masks: Rectangles ignored when comparing frames.
            reference: A frame the screen must first DIFFER from (the picture before an
                action); guards against "stable" meaning "nothing has happened yet". None
                when no change is expected.
            frames: Consecutive identical frames required (setting default when None).
            interval: Seconds between frames (setting default when None).

        Returns:
            The result; the last polled frame stays in ``self._last_frame``.

        Raises:
            QmpError, ConnectionError: if screenshots cannot be taken at all.
        """
        need = frames or self._settings.settle_frames
        wait = interval or self._settings.settle_interval_s
        timeout = self._settings.settle_timeout_s
        start = self._clock()
        taken = 0
        run = 1
        previous: Path | None = None
        changed = reference is None
        slot = 0
        cpu_before = self._read_cpu()
        while True:
            current = self._frame_paths[slot]
            self._screen.screendump(current)
            taken += 1
            self._last_frame = current
            cpu_after = self._read_cpu()
            quiet = self._guest_quiet(cpu_before, cpu_after)
            cpu_before = cpu_after
            if not changed:
                assert reference is not None
                if self._matcher(current, reference, masks):
                    run, previous = 1, None  # still the old picture: keep waiting
                else:
                    changed = True
            if changed:
                if previous is not None and quiet and self._matcher(current, previous, masks):
                    run += 1
                else:
                    run = 1
                previous = current
                if run >= need:
                    return SettleResult(True, self._clock() - start, taken)
                slot = 1 - slot  # keep `previous` intact for the next comparison
            if self._clock() - start >= timeout:
                reason = "timeout" if changed else "never changed"
                return SettleResult(False, self._clock() - start, taken, reason)
            self._sleep(wait)

    def _snapshot(self, name: str) -> Path:
        """
        Keep a copy of the last polled frame.

        Args:
            name: File stem for the copy inside the work directory.

        Returns:
            Path of the copy.
        """
        target = self._work / f"{name}.png"
        shutil.copyfile(self._last_frame, target)
        return target

    def wait_for_desktop(self, masks: Sequence[Rect], timeout: float = 120.0) -> SettleResult:
        """
        Wait until the desktop shell runs and the screen is quiet (end of boot).

        Args:
            masks: Rectangles ignored when comparing frames.
            timeout: Seconds to wait for the shell process.

        Returns:
            The settle result (a longer, slower settle than between states: the shell
            is still busy right after it starts).

        Raises:
            StepError: the shell process never appeared, or the screen never settled.
        """
        start = self._clock()
        while True:
            try:
                if self._guest.process_running("plasmashell"):
                    break
            except (TimeoutError, RuntimeError):
                pass  # the agent is busy or refused once; ask again
            if self._clock() - start > timeout:
                raise StepError("the desktop shell did not start")
            self._sleep(0.5)
        result = self.settle(masks, frames=max(3, self._settings.settle_frames), interval=max(2.0, self._settings.settle_interval_s))
        if not result.stable:
            raise StepError("the desktop did not settle after boot")
        return result

    def apply_mode(self, mode: Mode, generated_dir: Path, name: str, masks: Sequence[Rect]) -> SettleResult:
        """
        Switch the desktop to a colour mode.

        The generated scheme file is written into the desktop user's colour scheme
        directory through the guest agent, activated with ``plasma-apply-colorscheme``
        and the screen is allowed to settle. (The image never contains the scheme, so it
        does not depend on the design tokens.)

        Args:
            mode: The mode to apply.
            generated_dir: Directory produced by ``python -m design.generate``.
            name: Theme name (the ``<name>`` of ``<name>-<scheme>.colors``).
            masks: Rectangles ignored while settling.

        Returns:
            The settle result.

        Raises:
            StepError: the file is missing, the tool failed or the screen did not change
                and settle.
        """
        scheme_id = f"{name}-{mode.scheme}"
        source = generated_dir / "plasma" / f"{scheme_id}.colors"
        try:
            data = source.read_bytes()
        except OSError:
            raise StepError(f"generated colour scheme {source.name} is missing") from None
        before = self._snapshot_now("mode-before")
        destination = f"{self._guest.user.home}/.local/share/color-schemes/{scheme_id}.colors"
        self._guest.write_file(destination, data)
        result = self._guest.run_as_user(["plasma-apply-colorscheme", scheme_id], wait_exit=True, timeout=60)
        if result is None or result.exit_code != 0:
            raise StepError(f"plasma-apply-colorscheme failed for {scheme_id}")
        settled = self.settle(masks, reference=before)
        if not settled.stable:
            raise StepError(f"the screen did not settle after applying mode {mode.name} ({settled.reason})")
        return settled

    def _snapshot_now(self, name: str) -> Path:
        """
        Take a fresh frame and keep it (the reference for a later "must change" settle).

        Args:
            name: File stem for the copy inside the work directory.

        Returns:
            Path of the copy.
        """
        self._screen.screendump(self._frame_paths[0])
        self._last_frame = self._frame_paths[0]
        return self._snapshot(name)

    def _execute(self, step: Step) -> None:
        """
        Carry out one non-settle step.

        Args:
            step: The step.

        Raises:
            StepError: a program that had to exit successfully did not.
        """
        if step.kind == "key":
            self._screen.send_keys(step.value)
        elif step.kind == "type":
            self._screen.type_text(step.value)
        elif step.kind == "move":
            self._screen.pointer_move(*step.value)
        elif step.kind == "click":
            self._screen.pointer_click(*step.value)
        elif step.kind == "run":
            result = self._guest.run_as_user(list(step.value), wait_exit=step.wait_exit, timeout=60)
            if step.wait_exit and (result is None or result.exit_code != 0):
                raise StepError(f"{step.value[0]} exited with an error")
        elif step.kind == "wait":
            self._sleep(step.value)

    def _run_steps(
        self,
        steps: Sequence[Step],
        masks: Sequence[Rect],
        baseline: Path | None,
        label: str,
    ) -> tuple[float, int]:
        """
        Execute a step list with the settle rules.

        Args:
            steps: The steps.
            masks: Rectangles ignored while settling.
            baseline: The settled frame before the first step. When given, every settle
                that follows an action must see the screen change from the last settled
                frame, and a list that ends with an action gets an implicit final settle
                (the capture must never happen mid-change). None for the reset steps,
                which may legitimately change nothing; the caller settles afterwards.
            label: Text for messages, ``"step"`` or ``"reset step"``.

        Returns:
            Seconds spent settling and frames taken while doing so.

        Raises:
            StepError: a step failed or a settle did not succeed (message names the index).
            ConnectionError: the VM connection is gone.
        """
        settle_s, frames = 0.0, 0
        dirty = False
        reference = baseline
        for index, step in enumerate(steps):
            try:
                if step.kind == "settle":
                    result = self.settle(masks, reference=reference if dirty else None)
                    settle_s += result.seconds
                    frames += result.frames
                    if not result.stable:
                        raise StepError(f"the screen did not settle ({result.reason})")
                    if baseline is not None:
                        reference = self._snapshot("settled")
                    dirty = False
                else:
                    self._execute(step)
                    dirty = dirty or step.kind in EFFECT_KINDS
            except StepError as exc:
                raise StepError(f"{label} {index} ({step.kind}): {exc}") from None
            except (TimeoutError, RuntimeError, ValueError) as exc:
                raise StepError(f"{label} {index} ({step.kind}): {exc}") from None
        if dirty and baseline is not None:
            # The steps ended with an action: an implicit settle makes the capture safe.
            result = self.settle(masks, reference=reference)
            settle_s += result.seconds
            frames += result.frames
            if not result.stable:
                raise StepError(f"the screen did not settle after the last {label} ({result.reason})")
        return settle_s, frames

    def run_state(
        self,
        state: State,
        mode: Mode,
        masks: Sequence[Rect],
        shot: Path,
        shot_relative: str,
    ) -> StateResult:
        """
        Bring the desktop to a state and photograph it.

        Sequence: reset steps, an implicit settle, the state's steps, the final settle,
        then ``screendump`` to ``shot``. On any failure a diagnostic screenshot is saved
        as ``<state>.FAILED.png`` next to the shot and the result is ``failed`` (the
        caller continues with the next state).

        Args:
            state: The state to capture.
            mode: The mode (used for labels only; the mode is already applied).
            masks: The state's comparison masks (ignored while settling too).
            shot: Where the screenshot goes.
            shot_relative: The same location relative to the output directory, for the
                manifest.

        Returns:
            The result with timings.

        Raises:
            ConnectionError: the VM connection is gone (not a state failure).
        """
        started = self._clock()
        result = StateResult(state=state.name, mode=mode.name)
        self._log(f"[{mode.name}] {state.name}")
        try:
            # Reset first, then settle once: the desktop must be quiet before the state's
            # own steps start, and that quiet frame is the reference for "did it change".
            self._run_steps(self._settings.reset, masks, None, "reset step")
            baseline_settle = self.settle(masks)
            if not baseline_settle.stable:
                raise StepError(f"the desktop did not settle after the reset ({baseline_settle.reason})")
            baseline = self._snapshot("baseline")
            settle_s, frames = self._run_steps(state.steps, masks, baseline, "step")
            result.settle_s = baseline_settle.seconds + settle_s
            result.frames = baseline_settle.frames + frames
            self._screen.screendump(shot)
            result.shot = shot_relative
        except StepError as exc:
            result.status, result.error = "failed", str(exc)
        except ConnectionError:
            raise
        except (TimeoutError, RuntimeError, ValueError, OSError) as exc:
            result.status, result.error = "failed", f"{type(exc).__name__}: {exc}"
        if result.status == "failed":
            failed = shot.with_name(f"{state.name}.FAILED.png")
            try:
                self._screen.screendump(failed)
                result.diagnostic = f"{Path(shot_relative).parent.as_posix()}/{failed.name}"
            except (RuntimeError, OSError, TimeoutError):
                pass  # no diagnostic possible; the error text still stands
        result.duration_s = round(self._clock() - started, 1)
        result.settle_s = round(result.settle_s, 1)
        self._log(f"  -> {result.status} in {result.duration_s}s ({result.frames} frames)" + (f": {result.error}" if result.error else ""))
        return result
