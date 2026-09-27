"""Tests for harness.shots.states: parsing and validation of states.toml (no VM involved)."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from harness.shots import states
from harness.shots.states import REQUIRED_STATES, load_states, parse_states, parse_step, select

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SHIPPED = PROJECT_ROOT / "harness" / "states.toml"
RESOLUTION = (2560, 1440)


def valid_doc() -> dict[str, Any]:
    """
    Build a small valid document as ``tomllib`` would return it.

    Returns:
        A fresh dictionary that tests may modify.
    """
    return copy.deepcopy(
        {
            "settings": {
                "resolution": [2560, 1440],
                "settle_frames": 2,
                "settle_interval_s": 1.0,
                "settle_timeout_s": 30,
                "rtc_base": "2026-09-25T12:00:00",
                "reset": [{"key": "escape"}, {"key": "escape"}],
            },
            "defaults": {"tolerance": 3, "max_diff_ratio": 0.0005, "mask": [[2300, 1340, 2560, 1440]]},
            "modes": {"light": {"scheme": "light"}, "dark": {"scheme": "dark"}},
            "state": [
                {"name": "desktop-empty", "description": "Empty desktop.", "steps": []},
                {
                    "name": "overview",
                    "description": "Overview.",
                    "steps": [{"key": "meta+w"}, {"settle": True}],
                    "modes": ["light"],
                },
            ],
        }
    )


def test_valid_document_parses() -> None:
    """
    A valid document becomes the expected dataclasses.

    Returns:
        None.
    """
    parsed = parse_states(valid_doc())
    assert parsed.settings.resolution == (2560, 1440)
    assert parsed.settings.settle_frames == 2
    assert [m.name for m in parsed.modes] == ["light", "dark"]
    assert [s.name for s in parsed.states] == ["desktop-empty", "overview"]
    # A state without "modes" runs in every defined mode; an explicit list restricts it.
    assert parsed.states[0].modes == ("light", "dark")
    assert parsed.states[1].modes == ("light",)
    assert parsed.states[1].steps[0].kind == "key"
    assert parsed.settings.reset[0].value == "escape"


def test_shipped_states_file_validates_and_is_complete() -> None:
    """
    The real ``harness/states.toml`` is valid and defines the nine required states in
    both modes, each with a one-line description and at least one step (except the
    empty desktop).

    Returns:
        None.
    """
    parsed = load_states(SHIPPED)
    names = [s.name for s in parsed.states]
    assert set(REQUIRED_STATES) <= set(names)
    assert len(names) == len(set(names))
    assert parsed.mode_names() == ("light", "dark")
    for state in parsed.states:
        assert set(state.modes) == {"light", "dark"}, state.name
        assert state.description and "\n" not in state.description
        if state.name != "desktop-empty":
            assert state.steps, state.name
    assert parsed.settings.resolution == (2560, 1440)
    assert parsed.settings.reset, "the reset steps must exist"


def test_shipped_states_end_settled_or_are_captured_after_an_implicit_settle() -> None:
    """
    Every action-only step list is still safe: states end with a settle or with steps
    that need none (the runner adds an implicit settle after a trailing action).

    Returns:
        None.
    """
    parsed = load_states(SHIPPED)
    for state in parsed.states:
        kinds = [s.kind for s in state.steps]
        if kinds:
            assert "settle" in kinds, f"{state.name} never waits for the screen"


def test_shipped_file_comparison_rules_load() -> None:
    """
    The comparison side reads the same file (tolerance, ratio, masks) without error.

    Returns:
        None.
    """
    from harness.shots.compare import load_rules

    rules = load_rules(SHIPPED)
    assert set(REQUIRED_STATES) <= set(rules)
    for rule in rules.values():
        assert rule.masks, "every state masks at least the panel clock"


@pytest.mark.parametrize(
    "mutate, fragment",
    [
        (lambda d: d.update(bogus=1), "unknown key"),
        (lambda d: d.pop("settings"), "[settings]"),
        (lambda d: d["settings"].update(extra=1), "unknown key"),
        (lambda d: d["settings"].pop("settle_frames"), "missing key"),
        (lambda d: d["settings"].update(resolution=[2560]), "resolution"),
        (lambda d: d["settings"].update(resolution=[2560.0, 1440]), "resolution"),
        (lambda d: d["settings"].update(resolution="2560x1440"), "resolution"),
        (lambda d: d["settings"].update(resolution=[100, 100]), "between"),
        (lambda d: d["settings"].update(resolution=[9000, 1440]), "between"),
        (lambda d: d["settings"].update(settle_frames=0), "settle_frames"),
        (lambda d: d["settings"].update(settle_frames=11), "settle_frames"),
        (lambda d: d["settings"].update(settle_frames=True), "settle_frames"),
        (lambda d: d["settings"].update(settle_frames=2.5), "settle_frames"),
        (lambda d: d["settings"].update(settle_interval_s=0.01), "settle_interval_s"),
        (lambda d: d["settings"].update(settle_interval_s=99), "settle_interval_s"),
        (lambda d: d["settings"].update(settle_interval_s="1"), "settle_interval_s"),
        (lambda d: d["settings"].update(settle_timeout_s=0), "settle_timeout_s"),
        (lambda d: d["settings"].update(settle_timeout_s=601), "settle_timeout_s"),
        (lambda d: d["settings"].update(rtc_base="2026-09-25 12:00:00"), "rtc_base"),
        (lambda d: d["settings"].update(rtc_base="2026-13-45T25:61:00"), "rtc_base"),
        (lambda d: d["settings"].update(rtc_base=5), "rtc_base"),
        (lambda d: d["settings"].update(reset="escape"), "steps must be a list"),
        (lambda d: d["settings"].update(reset=[{"key": "escape"}, {"key": "nope"}]), "settings.reset step 1"),
    ],
)
def test_invalid_settings_are_rejected(mutate: Any, fragment: str) -> None:
    """
    Every kind of bad ``[settings]`` value is a ValueError with a helpful message.

    Args:
        mutate: Function that breaks a valid document.
        fragment: Text the error message must contain.

    Returns:
        None.
    """
    doc = valid_doc()
    mutate(doc)
    with pytest.raises(ValueError, match=fragment):
        parse_states(doc)


@pytest.mark.parametrize(
    "mutate, fragment",
    [
        (lambda d: d.update(defaults="x"), "defaults"),
        (lambda d: d["defaults"].update(colour=1), "unknown key"),
        (lambda d: d["defaults"].update(tolerance=-1), "tolerance"),
        (lambda d: d["defaults"].update(tolerance=256), "tolerance"),
        (lambda d: d["defaults"].update(tolerance=True), "tolerance"),
        (lambda d: d["defaults"].update(tolerance=1.5), "tolerance"),
        (lambda d: d["defaults"].update(max_diff_ratio=1.5), "max_diff_ratio"),
        (lambda d: d["defaults"].update(max_diff_ratio=-0.1), "max_diff_ratio"),
        (lambda d: d["defaults"].update(max_diff_ratio="0"), "max_diff_ratio"),
        (lambda d: d["defaults"].update(mask="all"), "mask must be a list"),
        (lambda d: d["defaults"].update(mask=[[1, 2, 3]]), "four integers"),
        (lambda d: d["defaults"].update(mask=[[10, 10, 10, 20]]), "x0 < x1"),
        (lambda d: d["defaults"].update(mask=[[0, 0, 2561, 10]]), "x0 < x1"),
        (lambda d: d["defaults"].update(mask=[[0, 5, 10, 1441]]), "y0 < y1"),
        (lambda d: d["defaults"].update(mask=[[-1, 0, 10, 10]]), "x0 < x1"),
    ],
)
def test_invalid_defaults_are_rejected(mutate: Any, fragment: str) -> None:
    """
    Bad ``[defaults]`` values (tolerance, ratio, mask rectangles) are rejected.

    Args:
        mutate: Function that breaks a valid document.
        fragment: Text the error message must contain.

    Returns:
        None.
    """
    doc = valid_doc()
    mutate(doc)
    with pytest.raises(ValueError, match=fragment):
        parse_states(doc)


@pytest.mark.parametrize(
    "mutate, fragment",
    [
        (lambda d: d.pop("modes"), "at least one"),
        (lambda d: d.update(modes={}), "at least one"),
        (lambda d: d["modes"].update({"Light": {"scheme": "light"}}), "name may only"),
        (lambda d: d["modes"].update({"has space": {"scheme": "x"}}), "name may only"),
        (lambda d: d["modes"].update(bad="light"), "must be a table"),
        (lambda d: d["modes"]["light"].update(extra=1), "unknown key"),
        (lambda d: d["modes"]["light"].pop("scheme"), "scheme"),
        (lambda d: d["modes"]["light"].update(scheme="Light"), "scheme"),
        (lambda d: d["modes"]["light"].update(scheme="../x"), "scheme"),
        (lambda d: d["modes"]["light"].update(scheme=3), "scheme"),
    ],
)
def test_invalid_modes_are_rejected(mutate: Any, fragment: str) -> None:
    """
    Missing, badly named or malformed modes are rejected.

    Args:
        mutate: Function that breaks a valid document.
        fragment: Text the error message must contain.

    Returns:
        None.
    """
    doc = valid_doc()
    mutate(doc)
    with pytest.raises(ValueError, match=fragment):
        parse_states(doc)


@pytest.mark.parametrize(
    "mutate, fragment",
    [
        (lambda d: d.pop("state"), "at least one"),
        (lambda d: d.update(state=[]), "at least one"),
        (lambda d: d.update(state=["x"]), "must be a table"),
        (lambda d: d["state"][0].pop("name"), "name must be"),
        (lambda d: d["state"][0].update(name="Bad_Name"), "name must be"),
        (lambda d: d["state"][0].update(name="with space"), "name must be"),
        (lambda d: d["state"][0].update(name="../x"), "name must be"),
        (lambda d: d["state"][0].update(name=""), "name must be"),
        (lambda d: d["state"][1].update(name="desktop-empty"), "used twice"),
        (lambda d: d["state"][0].update(extra=1), "unknown key"),
        (lambda d: d["state"][0].pop("description"), "description"),
        (lambda d: d["state"][0].update(description="  "), "description"),
        (lambda d: d["state"][0].update(description="two\nlines"), "description"),
        (lambda d: d["state"][0].update(description="x" * 201), "description"),
        (lambda d: d["state"][0].update(description=5), "description"),
        (lambda d: d["state"][0].pop("steps"), "steps is missing"),
        (lambda d: d["state"][0].update(steps="none"), "steps must be a list"),
        (lambda d: d["state"][1].update(modes=["twilight"]), "not defined"),
        (lambda d: d["state"][1].update(modes=["light", "light"]), "twice"),
        (lambda d: d["state"][1].update(modes=[]), "non-empty"),
        (lambda d: d["state"][1].update(modes="light"), "non-empty"),
        (lambda d: d["state"][1].update(tolerance=300), "tolerance"),
        (lambda d: d["state"][1].update(max_diff_ratio=2), "max_diff_ratio"),
        (lambda d: d["state"][1].update(mask=[[5, 5, 1, 1]]), "x0 < x1"),
    ],
)
def test_invalid_states_are_rejected(mutate: Any, fragment: str) -> None:
    """
    Every error path of a ``[[state]]`` table raises ValueError.

    Args:
        mutate: Function that breaks a valid document.
        fragment: Text the error message must contain.

    Returns:
        None.
    """
    doc = valid_doc()
    mutate(doc)
    with pytest.raises(ValueError, match=fragment):
        parse_states(doc)


def test_valid_per_state_overrides_are_accepted() -> None:
    """
    Per-state tolerance, ratio, mask and modes overrides validate.

    Returns:
        None.
    """
    doc = valid_doc()
    doc["state"][1].update(tolerance=5, max_diff_ratio=0.01, mask=[[0, 0, 10, 10]], modes=["dark"])
    assert parse_states(doc).states[1].modes == ("dark",)


@pytest.mark.parametrize(
    "raw, fragment",
    [
        ("key", "must be a table"),
        ({}, "exactly one"),
        ({"key": "escape", "wait": 1}, "exactly one"),
        ({"bogus": 1}, "unknown key"),
        ({"key": "escape", "extra": 1}, "unknown key"),
        ({"key": "meta+banana"}, "banana"),
        ({"key": ""}, "empty"),
        ({"key": 5}, "string"),
        ({"type": "hello!"}, "cannot be typed"),
        ({"type": ""}, "empty"),
        ({"type": 5}, "string"),
        ({"move": [10]}, r"\[x, y\]"),
        ({"move": [10, 10, 10]}, r"\[x, y\]"),
        ({"move": [1.5, 10]}, r"\[x, y\]"),
        ({"move": [True, 10]}, r"\[x, y\]"),
        ({"move": "10,10"}, r"\[x, y\]"),
        ({"move": [2560, 10]}, "outside"),
        ({"move": [10, 1440]}, "outside"),
        ({"move": [-1, 10]}, "outside"),
        ({"click": [0, -5]}, "outside"),
        ({"click": [99999, 0]}, "outside"),
        ({"run": []}, "non-empty list"),
        ({"run": "dolphin"}, "non-empty list"),
        ({"run": [""]}, "non-empty strings"),
        ({"run": ["a", 5]}, "non-empty strings"),
        ({"run": ["a\x00b"]}, "NUL"),
        ({"run": ["A=b", "x"]}, "'='"),
        ({"run": ["x"] * 65}, "at most"),
        ({"wait": -1}, "wait must be"),
        ({"wait": 61}, "wait must be"),
        ({"wait": "1"}, "wait must be"),
        ({"wait": True}, "wait must be"),
        ({"settle": False}, "settle must be true"),
        ({"settle": "yes"}, "settle must be true"),
        ({"key": "escape", "wait_exit": True}, "only allowed on a run"),
        ({"run": ["x"], "wait_exit": "yes"}, "true or false"),
    ],
)
def test_invalid_steps_are_rejected(raw: Any, fragment: str) -> None:
    """
    Each way of writing a bad step raises ValueError with the location prefix.

    Args:
        raw: The bad step.
        fragment: Text the message must contain.

    Returns:
        None.
    """
    with pytest.raises(ValueError, match=fragment) as caught:
        parse_step(raw, RESOLUTION, "state 'x' step 3")
    assert "state 'x' step 3" in str(caught.value)


@pytest.mark.parametrize(
    "raw, kind, value",
    [
        ({"key": "meta+w"}, "key", "meta+w"),
        ({"type": "files 1"}, "type", "files 1"),
        ({"move": [0, 0]}, "move", (0, 0)),
        ({"click": [2559, 1439]}, "click", (2559, 1439)),
        ({"run": ["dolphin", "Documents"]}, "run", ("dolphin", "Documents")),
        ({"wait": 0}, "wait", 0.0),
        ({"wait": 60}, "wait", 60.0),
        ({"wait": 1.5}, "wait", 1.5),
        ({"settle": True}, "settle", True),
    ],
)
def test_valid_steps_including_range_limits(raw: Any, kind: str, value: Any) -> None:
    """
    Each step kind parses; the coordinate and wait limits themselves are allowed.

    Args:
        raw: The step table.
        kind: Expected kind.
        value: Expected parsed value.

    Returns:
        None.
    """
    step = parse_step(raw, RESOLUTION, "state 'x' step 0")
    assert (step.kind, step.value) == (kind, value)


def test_run_step_wait_exit_flag() -> None:
    """
    ``wait_exit`` is kept on run steps and defaults to False.

    Returns:
        None.
    """
    assert parse_step({"run": ["x"]}, RESOLUTION, "s").wait_exit is False
    assert parse_step({"run": ["x"], "wait_exit": True}, RESOLUTION, "s").wait_exit is True


def test_error_message_names_state_and_step_index() -> None:
    """
    A broken step inside a state is reported as ``state '<name>' step <index>``.

    Returns:
        None.
    """
    doc = valid_doc()
    doc["state"][1]["steps"] = [{"key": "meta+w"}, {"settle": True}, {"click": [9999, 1]}]
    with pytest.raises(ValueError) as caught:
        parse_states(doc)
    message = str(caught.value)
    assert "state 'overview'" in message and "step 2" in message


def test_load_states_reports_missing_and_broken_files_without_paths(tmp_path: Path) -> None:
    """
    A missing or unparsable file is a ValueError that names the file, not its directory.

    Args:
        tmp_path: Pytest temporary directory.

    Returns:
        None.
    """
    with pytest.raises(ValueError) as missing:
        load_states(tmp_path / "nothing.toml")
    assert "nothing.toml" in str(missing.value)
    assert str(tmp_path) not in str(missing.value)

    broken = tmp_path / "broken.toml"
    broken.write_text("this is = = not toml", encoding="utf-8")
    with pytest.raises(ValueError, match="not valid TOML") as bad:
        load_states(broken)
    assert str(tmp_path) not in str(bad.value)


def test_load_states_reads_a_file(tmp_path: Path) -> None:
    """
    A TOML file with the shipped structure loads.

    Args:
        tmp_path: Pytest temporary directory.

    Returns:
        None.
    """
    text = """
[settings]
resolution = [1280, 720]
settle_frames = 2
settle_interval_s = 0.5
settle_timeout_s = 10
rtc_base = "2026-09-25T12:00:00"
reset = [ { key = "escape" } ]

[modes.light]
scheme = "light"

[[state]]
name = "a"
description = "A."
steps = [ { click = [10, 10] } ]
"""
    path = tmp_path / "states.toml"
    path.write_text(text, encoding="utf-8")
    parsed = load_states(path)
    assert parsed.settings.resolution == (1280, 720)
    assert parsed.states[0].steps[0].value == (10, 10)


def test_select_filters_and_validates_names() -> None:
    """
    ``--states`` and ``--modes`` selections keep file order and reject unknown names.

    Returns:
        None.
    """
    parsed = parse_states(valid_doc())
    modes, chosen = select(parsed, None, None)
    assert [m.name for m in modes] == ["light", "dark"]
    assert [s.name for s in chosen] == ["desktop-empty", "overview"]

    modes, chosen = select(parsed, ["overview"], ["dark"])
    assert [m.name for m in modes] == ["dark"]
    assert [s.name for s in chosen] == ["overview"]

    with pytest.raises(ValueError, match="unknown state 'nope'"):
        select(parsed, ["nope"], None)
    with pytest.raises(ValueError, match="unknown mode 'nope'"):
        select(parsed, None, ["nope"])


def test_get_mode() -> None:
    """
    ``get_mode`` finds a mode by name and raises KeyError otherwise.

    Returns:
        None.
    """
    parsed = parse_states(valid_doc())
    assert parsed.get_mode("dark").scheme == "dark"
    with pytest.raises(KeyError):
        parsed.get_mode("missing")


def test_effect_kinds_are_a_subset_of_the_vocabulary() -> None:
    """
    The runner's notion of "acts on the desktop" only uses known step kinds and excludes
    the pure waits.

    Returns:
        None.
    """
    assert set(states.EFFECT_KINDS) <= set(states.STEP_KINDS)
    assert "wait" not in states.EFFECT_KINDS and "settle" not in states.EFFECT_KINDS
