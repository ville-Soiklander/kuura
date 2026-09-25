"""
Tests for the Kvantum theme configuration generator (design.generators.kvantum).

The golden strings below are written out by hand from the layout in the module
docstring of kvantum, NOT computed with the generator or its helpers, so a wrong
key order, token mapping or number format cannot hide behind shared code.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest

from design.generators import kvantum

# The real design tokens live next to the tests' parent package (design/).
REAL_TOKENS_PATH = Path(__file__).resolve().parent.parent / "tokens.json"

# Key order required by the locked interface.
GENERAL_KEYS = [
    "author",
    "comment",
    "composite",
    "translucent_windows",
    "blurring",
    "popup_blurring",
    "animate_states",
    "reduce_window_opacity",
    "reduce_menu_opacity",
]
COLOR_KEYS = [
    "window.color",
    "inactive.window.color",
    "base.color",
    "inactive.base.color",
    "alt.base.color",
    "inactive.alt.base.color",
    "button.color",
    "light.color",
    "mid.light.color",
    "dark.color",
    "mid.color",
    "highlight.color",
    "inactive.highlight.color",
    "text.color",
    "inactive.text.color",
    "window.text.color",
    "inactive.window.text.color",
    "button.text.color",
    "disabled.text.color",
    "tooltip.base.color",
    "tooltip.text.color",
    "highlight.text.color",
    "link.color",
    "link.visited.color",
]

# Synthetic tokens: every one of the 20 colour keys per mode gets a distinct,
# easy-to-read colour (light: bytes 1,2,3 / 4,5,6 / ... ; dark: from 101 up).
# Light "accent" carries an alpha suffix to prove the alpha channel is dropped;
# upper-case hex digits prove the output is lower-cased.
SYNTHETIC_TOKENS = {
    "color": {
        "light": {
            "window": "#010203",
            "surface": "#040506",
            "surface_alt": "#070809",
            "text": "#0A0B0C",
            "text_secondary": "#0D0E0F",
            "text_disabled": "#101112",
            "accent": "#131415CC",
            "accent_text": "#161718",
            "separator": "#191A1B",
            "link": "#1C1D1E",
            "link_visited": "#1F2021",
            "error": "#222324",
            "warning": "#252627",
            "success": "#28292A",
            "tooltip_bg": "#2B2C2D",
            "tooltip_text": "#2E2F30",
            "shadow": "#313233",
            "button_close": "#343536",
            "button_minimize": "#373839",
            "button_maximize": "#3A3B3C",
        },
        "dark": {
            "window": "#656667",
            "surface": "#68696A",
            "surface_alt": "#6B6C6D",
            "text": "#6E6F70",
            "text_secondary": "#717273",
            "text_disabled": "#747576",
            "accent": "#777879",
            "accent_text": "#7A7B7C",
            "separator": "#7D7E7F",
            "link": "#808182",
            "link_visited": "#838485",
            "error": "#868788",
            "warning": "#898A8B",
            "success": "#8C8D8E",
            "tooltip_bg": "#8F9091",
            "tooltip_text": "#929394",
            "shadow": "#959697",
            "button_close": "#98999A",
            "button_minimize": "#9B9C9D",
            "button_maximize": "#9E9FA0",
        },
    },
    # Only sidebar and menu are read; 0.55 -> 45 and 0.70 -> 30.
    "material": {"bg_opacity": {"sidebar": 0.55, "menu": 0.70}},
}

GOLDEN_LIGHT = """\
[%General]
author=design tokens generator
comment=Golden - generated from design tokens, do not edit
composite=true
translucent_windows=true
blurring=true
popup_blurring=true
animate_states=true
reduce_window_opacity=45
reduce_menu_opacity=30

[GeneralColors]
window.color=#010203
inactive.window.color=#010203
base.color=#040506
inactive.base.color=#040506
alt.base.color=#070809
inactive.alt.base.color=#070809
button.color=#070809
light.color=#040506
mid.light.color=#070809
dark.color=#191a1b
mid.color=#191a1b
highlight.color=#131415
inactive.highlight.color=#131415
text.color=#0a0b0c
inactive.text.color=#0a0b0c
window.text.color=#0a0b0c
inactive.window.text.color=#0a0b0c
button.text.color=#0a0b0c
disabled.text.color=#101112
tooltip.base.color=#2b2c2d
tooltip.text.color=#2e2f30
highlight.text.color=#161718
link.color=#1c1d1e
link.visited.color=#1f2021
"""

GOLDEN_DARK = """\
[%General]
author=design tokens generator
comment=Golden - generated from design tokens, do not edit
composite=true
translucent_windows=true
blurring=true
popup_blurring=true
animate_states=true
reduce_window_opacity=45
reduce_menu_opacity=30

[GeneralColors]
window.color=#656667
inactive.window.color=#656667
base.color=#68696a
inactive.base.color=#68696a
alt.base.color=#6b6c6d
inactive.alt.base.color=#6b6c6d
button.color=#6b6c6d
light.color=#68696a
mid.light.color=#6b6c6d
dark.color=#7d7e7f
mid.color=#7d7e7f
highlight.color=#777879
inactive.highlight.color=#777879
text.color=#6e6f70
inactive.text.color=#6e6f70
window.text.color=#6e6f70
inactive.window.text.color=#6e6f70
button.text.color=#6e6f70
disabled.text.color=#747576
tooltip.base.color=#8f9091
tooltip.text.color=#929394
highlight.text.color=#7a7b7c
link.color=#808182
link.visited.color=#838485
"""


def _parse(text: str) -> list[tuple[str, list[tuple[str, str]]]]:
    """
    Split ".kvconfig" INI text into an ordered list of (section, [(key, value)]).

    Args:
        text: Output of kvantum.render.

    Returns:
        Sections in file order, each with its key/value pairs in file order.
    """
    sections: list[tuple[str, list[tuple[str, str]]]] = []
    for line in text.splitlines():
        if line.startswith("["):
            sections.append((line[1:-1], []))
        elif line:
            key, _, value = line.partition("=")
            sections[-1][1].append((key, value))
    return sections


def _with_opacity(sidebar: float, menu: float) -> dict:
    """
    Copy the synthetic tokens with different sidebar and menu opacities.

    Args:
        sidebar: Value for material.bg_opacity.sidebar.
        menu: Value for material.bg_opacity.menu.

    Returns:
        A deep copy, so the shared module-level fixture is never mutated.
    """
    tokens = copy.deepcopy(SYNTHETIC_TOKENS)
    tokens["material"]["bg_opacity"] = {"sidebar": sidebar, "menu": menu}
    return tokens


@pytest.fixture(scope="module")
def real_tokens() -> dict:
    """Load the real design/tokens.json once (tests deep-copy before mutating)."""
    return json.loads(REAL_TOKENS_PATH.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("mode", "expected"), [("light", GOLDEN_LIGHT), ("dark", GOLDEN_DARK)]
)
def test_golden_output_synthetic_tokens(mode: str, expected: str) -> None:
    """The entire output equals the hand-written golden text for each mode."""
    assert kvantum.render(SYNTHETIC_TOKENS, mode, "Golden") == expected


def test_default_arguments_are_light_and_theme(real_tokens: dict) -> None:
    """Omitting mode and name means mode="light", name="Theme"."""
    assert kvantum.render(real_tokens) == kvantum.render(real_tokens, "light", "Theme")


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_real_tokens_section_order_and_keys(real_tokens: dict, mode: str) -> None:
    """Sections appear in the specified order and each has its keys in order."""
    sections = _parse(kvantum.render(real_tokens, mode))
    assert [name for name, _ in sections] == ["%General", "GeneralColors"]
    assert [key for key, _ in sections[0][1]] == GENERAL_KEYS
    assert [key for key, _ in sections[1][1]] == COLOR_KEYS


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_real_tokens_file_shape_and_values(real_tokens: dict, mode: str) -> None:
    """One blank line between sections, one trailing newline, typed values."""
    text = kvantum.render(real_tokens, mode, "Golden")
    assert text.endswith("\n")
    assert not text.endswith("\n\n")
    assert len(text[:-1].split("\n\n")) == 2
    assert "\r" not in text

    general, colors = (dict(pairs) for _, pairs in _parse(text))
    assert general["author"] == "design tokens generator"
    assert general["comment"] == "Golden - generated from design tokens, do not edit"
    flags = ("composite", "translucent_windows", "blurring", "popup_blurring")
    assert all(general[key] == "true" for key in flags + ("animate_states",))
    # Reduction values are whole percentages, never floats such as "44.99...".
    assert re.fullmatch(r"\d{1,3}", general["reduce_window_opacity"])
    assert re.fullmatch(r"\d{1,3}", general["reduce_menu_opacity"])
    assert all(re.fullmatch(r"#[0-9a-f]{6}", value) for value in colors.values())


def test_output_is_deterministic(real_tokens: dict) -> None:
    """Identical inputs (even from a deep copy) give byte-identical output."""
    first = kvantum.render(real_tokens, "dark", "Same")
    second = kvantum.render(copy.deepcopy(real_tokens), "dark", "Same")
    assert first == second


def test_accent_change_alters_only_highlight_lines(real_tokens: dict) -> None:
    """Changing light accent rewrites exactly the two highlight colours, light only."""
    changed = copy.deepcopy(real_tokens)
    changed["color"]["light"]["accent"] = "#010203"

    before = kvantum.render(real_tokens, "light")
    after = kvantum.render(changed, "light")
    assert before != after

    # Same structure, so lines can be compared pairwise.
    before_lines, after_lines = before.splitlines(), after.splitlines()
    assert len(before_lines) == len(after_lines)
    diff = [(b, a) for b, a in zip(before_lines, after_lines) if b != a]
    assert [new for _, new in diff] == [
        "highlight.color=#010203",
        "inactive.highlight.color=#010203",
    ]

    # The dark palette is a separate token set and must not move.
    assert kvantum.render(real_tokens, "dark") == kvantum.render(changed, "dark")


def test_separator_change_alters_dark_and_mid_colors(real_tokens: dict) -> None:
    """The separator token feeds exactly dark.color and mid.color."""
    changed = copy.deepcopy(real_tokens)
    changed["color"]["dark"]["separator"] = "#0A0B0C"
    before = dict(_parse(kvantum.render(real_tokens, "dark"))[1][1])
    after = dict(_parse(kvantum.render(changed, "dark"))[1][1])
    differing = {key for key in before if before[key] != after[key]}
    assert differing == {"dark.color", "mid.color"}
    assert after["dark.color"] == after["mid.color"] == "#0a0b0c"


@pytest.mark.parametrize(
    "token",
    [
        "error",
        "warning",
        "success",
        "shadow",
        "button_close",
        "button_minimize",
        "button_maximize",
    ],
)
def test_unused_tokens_do_not_change_output(real_tokens: dict, token: str) -> None:
    """Tokens the Kvantum config does not read must not influence the output."""
    changed = copy.deepcopy(real_tokens)
    changed["color"]["light"][token] = "#0A0B0C"
    assert kvantum.render(changed, "light") == kvantum.render(real_tokens, "light")


def test_unused_opacities_do_not_change_output(real_tokens: dict) -> None:
    """Only bg_opacity.sidebar and .menu are read; panel and modal are ignored."""
    changed = copy.deepcopy(real_tokens)
    changed["material"]["bg_opacity"]["panel"] = 0.11
    changed["material"]["bg_opacity"]["modal"] = 0.99
    assert kvantum.render(changed, "light") == kvantum.render(real_tokens, "light")


@pytest.mark.parametrize(
    ("sidebar", "menu", "window_percent", "menu_percent"),
    [
        (0.55, 0.70, "45", "30"),  # the documented examples
        (0.62, 0.78, "38", "22"),
        (0.50, 0.25, "50", "75"),
        (1.0, 0.0, "0", "100"),  # fully opaque window, fully transparent menu
        (0.333, 0.667, "67", "33"),  # 66.7 rounds up, 33.3 rounds down
    ],
)
def test_reduce_opacity_follows_round_rule(
    sidebar: float, menu: float, window_percent: str, menu_percent: str
) -> None:
    """reduce_* = round((1 - opacity) * 100) as a whole number, per token."""
    text = kvantum.render(_with_opacity(sidebar, menu), "light")
    general = dict(_parse(text)[0][1])
    assert general["reduce_window_opacity"] == window_percent
    assert general["reduce_menu_opacity"] == menu_percent


@pytest.mark.parametrize("bad_mode", ["sepia", "", "Light", "DARK", None])
def test_invalid_mode_raises_value_error(real_tokens: dict, bad_mode: object) -> None:
    """Anything except the exact strings "light" and "dark" is rejected."""
    with pytest.raises(ValueError):
        kvantum.render(real_tokens, bad_mode)  # type: ignore[arg-type]
