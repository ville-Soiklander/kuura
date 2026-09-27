"""
Parser and validator for ``harness/states.toml`` (schema: docs/HARNESS_CONTRACT.md).

The file is read with ``tomllib`` and turned into frozen dataclasses. Everything the
capture side needs is validated HERE, before a VM is booted, so a typo costs
milliseconds and not a boot: unique state names, exactly one known key per step, value
types and ranges (coordinates inside the resolution, waits of 0..60 s, key chords that
exist), sane settings, and modes that are defined. Every error is a ``ValueError`` whose
message names the state and the step index (0-based).

Comparison rules (tolerance, ratio, masks) belong to ``harness.shots.compare.load_rules``.
They are only checked here for shape and range, so that a broken value is reported by
the same command that would otherwise fail later.

Standard library only.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from harness.shots import keys

# State and mode names become directory and file names: lowercase letters, digits, "-".
NAME_PATTERN = re.compile(r"^[a-z0-9-]+$")
# A colour scheme name is part of the generated file name <name>-<scheme>.colors.
SCHEME_PATTERN = re.compile(r"^[a-z0-9_-]+$")
RTC_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")

# The step vocabulary of the contract.
STEP_KINDS = ("key", "type", "move", "click", "run", "wait", "settle")
# Steps that act on the desktop (as opposed to only waiting). The runner uses this to
# know when a following settle must see the screen change.
EFFECT_KINDS = ("key", "type", "move", "click", "run")

MAX_WAIT_S = 60.0
MAX_RUN_ARGS = 64
MAX_RUN_ARG_LENGTH = 4096
MAX_DESCRIPTION_LENGTH = 200

# The nine states the working brief requires (see the contract).
REQUIRED_STATES = (
    "desktop-empty",
    "menubar-open",
    "shelf-hover",
    "overview",
    "search-open",
    "files-window",
    "settings-window",
    "notification",
    "browser-window",
)

_TOP_LEVEL_KEYS = {"settings", "defaults", "modes", "state"}
_SETTINGS_KEYS = {"resolution", "settle_frames", "settle_interval_s", "settle_timeout_s", "rtc_base", "reset"}
_DEFAULTS_KEYS = {"tolerance", "max_diff_ratio", "mask"}
_STATE_KEYS = {"name", "description", "steps", "tolerance", "max_diff_ratio", "mask", "modes"}


@dataclass(frozen=True)
class Step:
    """
    One step of a state.

    Attributes:
        kind: One of ``STEP_KINDS``.
        value: The step's value: chord string (key), text (type), ``(x, y)`` (move,
            click), argument tuple (run), seconds as float (wait), True (settle).
        wait_exit: Only for ``run``: wait for the program to exit.
    """

    kind: str
    value: Any
    wait_exit: bool = False


@dataclass(frozen=True)
class Settings:
    """
    The ``[settings]`` table.

    Attributes:
        resolution: Display size in physical pixels (width, height).
        settle_frames: Consecutive identical frames that count as stable.
        settle_interval_s: Seconds between polled frames.
        settle_timeout_s: Seconds after which an unsettled screen is a failed state.
        rtc_base: Initial guest clock, ``YYYY-MM-DDTHH:MM:SS``.
        reset: Steps that run before every state.
    """

    resolution: tuple[int, int]
    settle_frames: int
    settle_interval_s: float
    settle_timeout_s: float
    rtc_base: str
    reset: tuple[Step, ...]


@dataclass(frozen=True)
class Mode:
    """
    A colour mode (``[modes.<name>]``).

    Attributes:
        name: Mode name; it is also the sub-directory of the shots.
        scheme: Scheme suffix of the generated ``<name>-<scheme>.colors`` file.
    """

    name: str
    scheme: str


@dataclass(frozen=True)
class State:
    """
    One named desktop state.

    Attributes:
        name: Unique state name (file name of the shot).
        description: One line: what is shown and which stock component plays the role
            of the future bespoke one.
        steps: The steps that lead from the reset desktop to the state.
        modes: Names of the modes this state is captured in.
    """

    name: str
    description: str
    steps: tuple[Step, ...]
    modes: tuple[str, ...]


@dataclass(frozen=True)
class StatesFile:
    """
    The whole validated file.

    Attributes:
        settings: The ``[settings]`` table.
        modes: Defined modes in file order.
        states: Defined states in file order.
    """

    settings: Settings
    modes: tuple[Mode, ...]
    states: tuple[State, ...]

    def mode_names(self) -> tuple[str, ...]:
        """Return the names of all defined modes, in file order."""
        return tuple(mode.name for mode in self.modes)

    def get_mode(self, name: str) -> Mode:
        """
        Look a mode up by name.

        Args:
            name: Mode name.

        Returns:
            The mode.

        Raises:
            KeyError: if no such mode is defined.
        """
        for mode in self.modes:
            if mode.name == name:
                return mode
        raise KeyError(name)


def _is_number(value: Any) -> bool:
    """
    Tell whether a value is an int or float (a bool is NOT a number here).

    Args:
        value: Any TOML value.

    Returns:
        True for int and float, False for everything else including bool.
    """
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_int(value: Any) -> bool:
    """
    Tell whether a value is an int (a bool is not).

    Args:
        value: Any TOML value.

    Returns:
        True for a real integer.
    """
    return isinstance(value, int) and not isinstance(value, bool)


def _check_unknown_keys(table: dict[str, Any], allowed: set[str], where: str) -> None:
    """
    Reject keys a table is not allowed to have (a typo must not be silently ignored).

    Args:
        table: The table to check.
        allowed: The permitted keys.
        where: Text naming the table in the error message.

    Raises:
        ValueError: on any unknown key.
    """
    unknown = sorted(set(table) - allowed)
    if unknown:
        raise ValueError(f"{where}: unknown key(s) {', '.join(repr(k) for k in unknown)}")


def _parse_coordinate_pair(value: Any, resolution: tuple[int, int], where: str) -> tuple[int, int]:
    """
    Validate an ``[x, y]`` pointer position.

    Args:
        value: The TOML value.
        resolution: Display size (width, height).
        where: Text naming the step in error messages.

    Returns:
        The position as a tuple.

    Raises:
        ValueError: if it is not two integers inside the screen.
    """
    if not isinstance(value, list) or len(value) != 2 or not all(_is_int(v) for v in value):
        raise ValueError(f"{where}: expected [x, y] with two integers")
    x, y = value
    width, height = resolution
    if not (0 <= x < width and 0 <= y < height):
        raise ValueError(f"{where}: position [{x}, {y}] is outside the {width}x{height} screen")
    return x, y


def parse_step(raw: Any, resolution: tuple[int, int], where: str) -> Step:
    """
    Validate one step table.

    Args:
        raw: The TOML inline table.
        resolution: Display size, used to range-check pointer positions.
        where: Text naming the step, for example ``"state 'overview' step 1"``.

    Returns:
        The parsed step.

    Raises:
        ValueError: if the step is not a table, has zero or several step keys, an unknown
            key, a value of the wrong type or range, a chord or text that cannot be
            sent, or ``wait_exit`` on a step other than ``run``.
    """
    if not isinstance(raw, dict):
        raise ValueError(f"{where}: a step must be a table like {{ key = \"escape\" }}")
    kinds = [k for k in raw if k in STEP_KINDS]
    extras = [k for k in raw if k not in STEP_KINDS and k != "wait_exit"]
    if extras:
        raise ValueError(f"{where}: unknown key(s) {', '.join(repr(k) for k in sorted(extras))}")
    if len(kinds) != 1:
        raise ValueError(f"{where}: a step needs exactly one of {', '.join(STEP_KINDS)} (found {len(kinds)})")
    kind = kinds[0]
    value = raw[kind]

    wait_exit = False
    if "wait_exit" in raw:
        if kind != "run":
            raise ValueError(f"{where}: wait_exit is only allowed on a run step")
        if not isinstance(raw["wait_exit"], bool):
            raise ValueError(f"{where}: wait_exit must be true or false")
        wait_exit = raw["wait_exit"]

    if kind == "key":
        try:
            keys.parse_chord(value)
        except ValueError as exc:
            raise ValueError(f"{where}: {exc}") from None
        return Step("key", value)
    if kind == "type":
        try:
            keys.text_to_chords(value)
        except ValueError as exc:
            raise ValueError(f"{where}: {exc}") from None
        return Step("type", value)
    if kind in ("move", "click"):
        return Step(kind, _parse_coordinate_pair(value, resolution, where))
    if kind == "run":
        if not isinstance(value, list) or not value:
            raise ValueError(f"{where}: run needs a non-empty list of strings")
        if len(value) > MAX_RUN_ARGS:
            raise ValueError(f"{where}: run may have at most {MAX_RUN_ARGS} arguments")
        for item in value:
            if not isinstance(item, str) or not item or "\x00" in item or len(item) > MAX_RUN_ARG_LENGTH:
                raise ValueError(f"{where}: run arguments must be non-empty strings without NUL")
        if "=" in value[0]:
            raise ValueError(f"{where}: the program name of a run step must not contain '='")
        return Step("run", tuple(value), wait_exit)
    if kind == "wait":
        if not _is_number(value) or not 0 <= value <= MAX_WAIT_S:
            raise ValueError(f"{where}: wait must be a number of seconds from 0 to {MAX_WAIT_S:g}")
        return Step("wait", float(value))
    # kind == "settle"
    if value is not True:
        raise ValueError(f"{where}: settle must be true")
    return Step("settle", True)


def _parse_steps(raw: Any, resolution: tuple[int, int], where: str) -> tuple[Step, ...]:
    """
    Validate a list of steps.

    Args:
        raw: The TOML array.
        resolution: Display size.
        where: Text naming the owner, for example ``"state 'overview'"``.

    Returns:
        The parsed steps.

    Raises:
        ValueError: if ``raw`` is not a list or a step is invalid (message names the index).
    """
    if not isinstance(raw, list):
        raise ValueError(f"{where}: steps must be a list")
    return tuple(parse_step(item, resolution, f"{where} step {index}") for index, item in enumerate(raw))


def _parse_settings(raw: Any) -> Settings:
    """
    Validate the ``[settings]`` table.

    Args:
        raw: The table.

    Returns:
        The settings.

    Raises:
        ValueError: on a missing table, an unknown or missing key, or a value that is
            not sane.
    """
    if not isinstance(raw, dict):
        raise ValueError("settings: the [settings] table is missing")
    _check_unknown_keys(raw, _SETTINGS_KEYS, "settings")
    missing = sorted(_SETTINGS_KEYS - set(raw))
    if missing:
        raise ValueError(f"settings: missing key(s) {', '.join(repr(k) for k in missing)}")

    resolution = raw["resolution"]
    if not isinstance(resolution, list) or len(resolution) != 2 or not all(_is_int(v) for v in resolution):
        raise ValueError("settings: resolution must be [width, height] with two integers")
    width, height = resolution
    if not (640 <= width <= 7680 and 480 <= height <= 4320):
        raise ValueError("settings: resolution must be between 640x480 and 7680x4320")

    frames = raw["settle_frames"]
    if not _is_int(frames) or not 1 <= frames <= 10:
        raise ValueError("settings: settle_frames must be an integer from 1 to 10")
    interval = raw["settle_interval_s"]
    if not _is_number(interval) or not 0.1 <= interval <= 10:
        raise ValueError("settings: settle_interval_s must be a number from 0.1 to 10")
    timeout = raw["settle_timeout_s"]
    if not _is_number(timeout) or not 1 <= timeout <= 600:
        raise ValueError("settings: settle_timeout_s must be a number from 1 to 600")

    rtc_base = raw["rtc_base"]
    if not isinstance(rtc_base, str) or not RTC_PATTERN.match(rtc_base):
        raise ValueError("settings: rtc_base must look like 2026-09-25T12:00:00")
    try:
        datetime.fromisoformat(rtc_base)
    except ValueError:
        raise ValueError("settings: rtc_base is not a real date and time") from None

    size = (width, height)
    reset = _parse_steps(raw["reset"], size, "settings.reset")
    return Settings(size, frames, float(interval), float(timeout), rtc_base, reset)


def _check_rules(table: dict[str, Any], resolution: tuple[int, int], where: str) -> None:
    """
    Range-check the comparison keys (tolerance, max_diff_ratio, mask) of a table.

    Args:
        table: ``[defaults]`` or one ``[[state]]``.
        resolution: Display size; masks must lie inside it.
        where: Text naming the table in error messages.

    Raises:
        ValueError: on a value out of range or a malformed mask rectangle.
    """
    if "tolerance" in table and (not _is_int(table["tolerance"]) or not 0 <= table["tolerance"] <= 255):
        raise ValueError(f"{where}: tolerance must be an integer from 0 to 255")
    if "max_diff_ratio" in table and (
        not _is_number(table["max_diff_ratio"]) or not 0 <= table["max_diff_ratio"] <= 1
    ):
        raise ValueError(f"{where}: max_diff_ratio must be a number from 0 to 1")
    if "mask" in table:
        masks = table["mask"]
        if not isinstance(masks, list):
            raise ValueError(f"{where}: mask must be a list of [x0, y0, x1, y1] rectangles")
        width, height = resolution
        for index, rect in enumerate(masks):
            if not isinstance(rect, list) or len(rect) != 4 or not all(_is_int(v) for v in rect):
                raise ValueError(f"{where}: mask {index} must be [x0, y0, x1, y1] with four integers")
            x0, y0, x1, y1 = rect
            if not (0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height):
                raise ValueError(f"{where}: mask {index} must satisfy 0 <= x0 < x1 <= {width} and 0 <= y0 < y1 <= {height}")


def _parse_modes(raw: Any) -> tuple[Mode, ...]:
    """
    Validate the ``[modes.*]`` tables.

    Args:
        raw: The ``modes`` table.

    Returns:
        The modes in file order.

    Raises:
        ValueError: if there is no mode, a name or scheme is malformed, or a mode table
            has unknown keys.
    """
    if not isinstance(raw, dict) or not raw:
        raise ValueError("modes: define at least one [modes.<name>] table")
    modes = []
    for name, table in raw.items():
        if not NAME_PATTERN.match(name):
            raise ValueError(f"mode {name!r}: the name may only contain lowercase letters, digits and '-'")
        if not isinstance(table, dict):
            raise ValueError(f"mode {name!r}: must be a table with a scheme")
        _check_unknown_keys(table, {"scheme"}, f"mode {name!r}")
        scheme = table.get("scheme")
        if not isinstance(scheme, str) or not SCHEME_PATTERN.match(scheme):
            raise ValueError(f"mode {name!r}: scheme must be lowercase letters, digits, '_' or '-'")
        modes.append(Mode(name, scheme))
    return tuple(modes)


def _parse_state(raw: Any, index: int, resolution: tuple[int, int], mode_names: tuple[str, ...]) -> State:
    """
    Validate one ``[[state]]`` table.

    Args:
        raw: The table.
        index: Its position in the file (for messages about a state without a name).
        resolution: Display size.
        mode_names: Names of the defined modes.

    Returns:
        The parsed state.

    Raises:
        ValueError: on a malformed or unknown key/value; the message names the state.
    """
    if not isinstance(raw, dict):
        raise ValueError(f"state #{index}: must be a table")
    name = raw.get("name")
    if not isinstance(name, str) or not NAME_PATTERN.match(name):
        raise ValueError(f"state #{index}: name must be lowercase letters, digits and '-' (got {name!r})")
    where = f"state {name!r}"
    _check_unknown_keys(raw, _STATE_KEYS, where)

    description = raw.get("description")
    if (
        not isinstance(description, str)
        or not description.strip()
        or "\n" in description
        or len(description) > MAX_DESCRIPTION_LENGTH
    ):
        raise ValueError(f"{where}: description must be one non-empty line of at most {MAX_DESCRIPTION_LENGTH} characters")
    if "steps" not in raw:
        raise ValueError(f"{where}: steps is missing (use steps = [] for none)")
    steps = _parse_steps(raw["steps"], resolution, where)
    _check_rules(raw, resolution, where)

    modes = raw.get("modes", list(mode_names))
    if not isinstance(modes, list) or not modes or not all(isinstance(m, str) for m in modes):
        raise ValueError(f"{where}: modes must be a non-empty list of mode names")
    if len(set(modes)) != len(modes):
        raise ValueError(f"{where}: modes lists a mode twice")
    for mode in modes:
        if mode not in mode_names:
            raise ValueError(f"{where}: mode {mode!r} is not defined in [modes]")
    return State(name, description.strip(), steps, tuple(modes))


def parse_states(data: dict[str, Any]) -> StatesFile:
    """
    Validate a parsed TOML document.

    Args:
        data: The dictionary produced by ``tomllib``.

    Returns:
        The validated file.

    Raises:
        ValueError: on any schema violation (see the module docstring).
    """
    if not isinstance(data, dict):
        raise ValueError("the states file must be a TOML table")
    _check_unknown_keys(data, _TOP_LEVEL_KEYS, "states file")

    settings = _parse_settings(data.get("settings"))
    defaults = data.get("defaults", {})
    if not isinstance(defaults, dict):
        raise ValueError("defaults: must be a table")
    _check_unknown_keys(defaults, _DEFAULTS_KEYS, "defaults")
    _check_rules(defaults, settings.resolution, "defaults")

    modes = _parse_modes(data.get("modes"))
    mode_names = tuple(mode.name for mode in modes)

    raw_states = data.get("state")
    if not isinstance(raw_states, list) or not raw_states:
        raise ValueError("define at least one [[state]]")
    states = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_states):
        state = _parse_state(raw, index, settings.resolution, mode_names)
        if state.name in seen:
            raise ValueError(f"state {state.name!r}: the name is used twice")
        seen.add(state.name)
        states.append(state)
    return StatesFile(settings, modes, tuple(states))


def load_states(path: Path) -> StatesFile:
    """
    Read and validate a states file.

    Args:
        path: Path of ``states.toml``.

    Returns:
        The validated file.

    Raises:
        ValueError: if the file cannot be read, is not valid TOML, or breaks the schema.
            Messages carry the file NAME only, never its directory.
    """
    try:
        with open(path, "rb") as handle:
            data = tomllib.load(handle)
    except OSError:
        raise ValueError(f"cannot read the states file {path.name!r}") from None
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"{path.name}: not valid TOML: {exc}") from None
    return parse_states(data)


def select(
    states_file: StatesFile,
    state_names: list[str] | None,
    mode_names: list[str] | None,
) -> tuple[list[Mode], list[State]]:
    """
    Apply the ``--states`` and ``--modes`` selections.

    Args:
        states_file: The validated file.
        state_names: State names to keep, or None for all.
        mode_names: Mode names to keep, or None for all.

    Returns:
        The selected modes (file order) and the selected states (file order). A state is
        run in a mode only if it lists that mode; the caller checks ``state.modes``.

    Raises:
        ValueError: if a requested state or mode is not defined.
    """
    known_states = {state.name for state in states_file.states}
    known_modes = set(states_file.mode_names())
    for name in state_names or []:
        if name not in known_states:
            raise ValueError(f"unknown state {name!r} (defined: {', '.join(sorted(known_states))})")
    for name in mode_names or []:
        if name not in known_modes:
            raise ValueError(f"unknown mode {name!r} (defined: {', '.join(sorted(known_modes))})")
    modes = [m for m in states_file.modes if mode_names is None or m.name in mode_names]
    states = [s for s in states_file.states if state_names is None or s.name in state_names]
    return modes, states
