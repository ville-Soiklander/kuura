"""
Tests for the KDE Plasma colour scheme generator (design.generators.plasma_colors).

The golden strings below are written out by hand from the layout in the module
docstring of plasma_colors, NOT computed with the generator or its helpers, so a
wrong key order, token mapping or number format cannot hide behind shared code.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest

from design.generators import plasma_colors

# The real design tokens live next to the tests' parent package (design/).
REAL_TOKENS_PATH = Path(__file__).resolve().parent.parent / "tokens.json"

# Section order and per-section key order required by the locked interface.
GROUP_KEYS = [
    "BackgroundAlternate",
    "BackgroundNormal",
    "DecorationFocus",
    "DecorationHover",
    "ForegroundActive",
    "ForegroundInactive",
    "ForegroundLink",
    "ForegroundNegative",
    "ForegroundNeutral",
    "ForegroundNormal",
    "ForegroundPositive",
    "ForegroundVisited",
]
EXPECTED_KEYS = {
    "ColorEffects:Disabled": [
        "Color",
        "ColorAmount",
        "ColorEffect",
        "ContrastAmount",
        "ContrastEffect",
        "IntensityAmount",
        "IntensityEffect",
    ],
    "ColorEffects:Inactive": [
        "ChangeSelectionColor",
        "Color",
        "ColorAmount",
        "ColorEffect",
        "ContrastAmount",
        "ContrastEffect",
        "Enable",
        "IntensityAmount",
        "IntensityEffect",
    ],
    "Colors:Button": GROUP_KEYS,
    "Colors:Complementary": GROUP_KEYS,
    "Colors:Header": GROUP_KEYS,
    "Colors:Selection": GROUP_KEYS,
    "Colors:Tooltip": GROUP_KEYS,
    "Colors:View": GROUP_KEYS,
    "Colors:Window": GROUP_KEYS,
    "General": ["ColorScheme", "Name"],
    "KDE": ["contrast"],
    "WM": [
        "activeBackground",
        "activeBlend",
        "activeForeground",
        "inactiveBackground",
        "inactiveBlend",
        "inactiveForeground",
    ],
}

# Synthetic tokens: every one of the 20 colour keys per mode gets a distinct,
# easy-to-read colour (light: bytes 1,2,3 / 4,5,6 / ... ; dark: from 101 up).
# Light "accent" carries an alpha suffix to prove the alpha channel is dropped.
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
    }
}

GOLDEN_LIGHT = """\
[ColorEffects:Disabled]
Color=16,17,18
ColorAmount=0
ColorEffect=0
ContrastAmount=0.65
ContrastEffect=1
IntensityAmount=0.1
IntensityEffect=2

[ColorEffects:Inactive]
ChangeSelectionColor=true
Color=13,14,15
ColorAmount=0.025
ColorEffect=2
ContrastAmount=0.1
ContrastEffect=2
Enable=false
IntensityAmount=0
IntensityEffect=0

[Colors:Button]
BackgroundAlternate=4,5,6
BackgroundNormal=7,8,9
DecorationFocus=19,20,21
DecorationHover=19,20,21
ForegroundActive=19,20,21
ForegroundInactive=13,14,15
ForegroundLink=28,29,30
ForegroundNegative=34,35,36
ForegroundNeutral=37,38,39
ForegroundNormal=10,11,12
ForegroundPositive=40,41,42
ForegroundVisited=31,32,33

[Colors:Complementary]
BackgroundAlternate=7,8,9
BackgroundNormal=1,2,3
DecorationFocus=19,20,21
DecorationHover=19,20,21
ForegroundActive=19,20,21
ForegroundInactive=13,14,15
ForegroundLink=28,29,30
ForegroundNegative=34,35,36
ForegroundNeutral=37,38,39
ForegroundNormal=10,11,12
ForegroundPositive=40,41,42
ForegroundVisited=31,32,33

[Colors:Header]
BackgroundAlternate=7,8,9
BackgroundNormal=1,2,3
DecorationFocus=19,20,21
DecorationHover=19,20,21
ForegroundActive=19,20,21
ForegroundInactive=13,14,15
ForegroundLink=28,29,30
ForegroundNegative=34,35,36
ForegroundNeutral=37,38,39
ForegroundNormal=10,11,12
ForegroundPositive=40,41,42
ForegroundVisited=31,32,33

[Colors:Selection]
BackgroundAlternate=19,20,21
BackgroundNormal=19,20,21
DecorationFocus=22,23,24
DecorationHover=22,23,24
ForegroundActive=22,23,24
ForegroundInactive=22,23,24
ForegroundLink=22,23,24
ForegroundNegative=34,35,36
ForegroundNeutral=37,38,39
ForegroundNormal=22,23,24
ForegroundPositive=40,41,42
ForegroundVisited=22,23,24

[Colors:Tooltip]
BackgroundAlternate=43,44,45
BackgroundNormal=43,44,45
DecorationFocus=19,20,21
DecorationHover=19,20,21
ForegroundActive=46,47,48
ForegroundInactive=46,47,48
ForegroundLink=46,47,48
ForegroundNegative=34,35,36
ForegroundNeutral=37,38,39
ForegroundNormal=46,47,48
ForegroundPositive=40,41,42
ForegroundVisited=46,47,48

[Colors:View]
BackgroundAlternate=7,8,9
BackgroundNormal=4,5,6
DecorationFocus=19,20,21
DecorationHover=19,20,21
ForegroundActive=19,20,21
ForegroundInactive=13,14,15
ForegroundLink=28,29,30
ForegroundNegative=34,35,36
ForegroundNeutral=37,38,39
ForegroundNormal=10,11,12
ForegroundPositive=40,41,42
ForegroundVisited=31,32,33

[Colors:Window]
BackgroundAlternate=7,8,9
BackgroundNormal=1,2,3
DecorationFocus=19,20,21
DecorationHover=19,20,21
ForegroundActive=19,20,21
ForegroundInactive=13,14,15
ForegroundLink=28,29,30
ForegroundNegative=34,35,36
ForegroundNeutral=37,38,39
ForegroundNormal=10,11,12
ForegroundPositive=40,41,42
ForegroundVisited=31,32,33

[General]
ColorScheme=Golden
Name=Golden

[KDE]
contrast=4

[WM]
activeBackground=1,2,3
activeBlend=10,11,12
activeForeground=10,11,12
inactiveBackground=1,2,3
inactiveBlend=13,14,15
inactiveForeground=13,14,15
"""

GOLDEN_DARK = """\
[ColorEffects:Disabled]
Color=116,117,118
ColorAmount=0
ColorEffect=0
ContrastAmount=0.65
ContrastEffect=1
IntensityAmount=0.1
IntensityEffect=2

[ColorEffects:Inactive]
ChangeSelectionColor=true
Color=113,114,115
ColorAmount=0.025
ColorEffect=2
ContrastAmount=0.1
ContrastEffect=2
Enable=false
IntensityAmount=0
IntensityEffect=0

[Colors:Button]
BackgroundAlternate=104,105,106
BackgroundNormal=107,108,109
DecorationFocus=119,120,121
DecorationHover=119,120,121
ForegroundActive=119,120,121
ForegroundInactive=113,114,115
ForegroundLink=128,129,130
ForegroundNegative=134,135,136
ForegroundNeutral=137,138,139
ForegroundNormal=110,111,112
ForegroundPositive=140,141,142
ForegroundVisited=131,132,133

[Colors:Complementary]
BackgroundAlternate=107,108,109
BackgroundNormal=101,102,103
DecorationFocus=119,120,121
DecorationHover=119,120,121
ForegroundActive=119,120,121
ForegroundInactive=113,114,115
ForegroundLink=128,129,130
ForegroundNegative=134,135,136
ForegroundNeutral=137,138,139
ForegroundNormal=110,111,112
ForegroundPositive=140,141,142
ForegroundVisited=131,132,133

[Colors:Header]
BackgroundAlternate=107,108,109
BackgroundNormal=101,102,103
DecorationFocus=119,120,121
DecorationHover=119,120,121
ForegroundActive=119,120,121
ForegroundInactive=113,114,115
ForegroundLink=128,129,130
ForegroundNegative=134,135,136
ForegroundNeutral=137,138,139
ForegroundNormal=110,111,112
ForegroundPositive=140,141,142
ForegroundVisited=131,132,133

[Colors:Selection]
BackgroundAlternate=119,120,121
BackgroundNormal=119,120,121
DecorationFocus=122,123,124
DecorationHover=122,123,124
ForegroundActive=122,123,124
ForegroundInactive=122,123,124
ForegroundLink=122,123,124
ForegroundNegative=134,135,136
ForegroundNeutral=137,138,139
ForegroundNormal=122,123,124
ForegroundPositive=140,141,142
ForegroundVisited=122,123,124

[Colors:Tooltip]
BackgroundAlternate=143,144,145
BackgroundNormal=143,144,145
DecorationFocus=119,120,121
DecorationHover=119,120,121
ForegroundActive=146,147,148
ForegroundInactive=146,147,148
ForegroundLink=146,147,148
ForegroundNegative=134,135,136
ForegroundNeutral=137,138,139
ForegroundNormal=146,147,148
ForegroundPositive=140,141,142
ForegroundVisited=146,147,148

[Colors:View]
BackgroundAlternate=107,108,109
BackgroundNormal=104,105,106
DecorationFocus=119,120,121
DecorationHover=119,120,121
ForegroundActive=119,120,121
ForegroundInactive=113,114,115
ForegroundLink=128,129,130
ForegroundNegative=134,135,136
ForegroundNeutral=137,138,139
ForegroundNormal=110,111,112
ForegroundPositive=140,141,142
ForegroundVisited=131,132,133

[Colors:Window]
BackgroundAlternate=107,108,109
BackgroundNormal=101,102,103
DecorationFocus=119,120,121
DecorationHover=119,120,121
ForegroundActive=119,120,121
ForegroundInactive=113,114,115
ForegroundLink=128,129,130
ForegroundNegative=134,135,136
ForegroundNeutral=137,138,139
ForegroundNormal=110,111,112
ForegroundPositive=140,141,142
ForegroundVisited=131,132,133

[General]
ColorScheme=Golden
Name=Golden

[KDE]
contrast=4

[WM]
activeBackground=101,102,103
activeBlend=110,111,112
activeForeground=110,111,112
inactiveBackground=101,102,103
inactiveBlend=113,114,115
inactiveForeground=113,114,115
"""


def _parse(text: str) -> list[tuple[str, list[tuple[str, str]]]]:
    """
    Split ".colors" INI text into an ordered list of (section, [(key, value)]).

    Args:
        text: Output of plasma_colors.render.

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


@pytest.fixture(scope="module")
def real_tokens() -> dict:
    """Load the real design/tokens.json once (tests deep-copy before mutating)."""
    return json.loads(REAL_TOKENS_PATH.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("mode", "expected"), [("light", GOLDEN_LIGHT), ("dark", GOLDEN_DARK)]
)
def test_golden_output_synthetic_tokens(mode: str, expected: str) -> None:
    """The entire output equals the hand-written golden text for each mode."""
    assert plasma_colors.render(SYNTHETIC_TOKENS, mode, "Golden") == expected


def test_default_arguments_are_light_and_theme(real_tokens: dict) -> None:
    """Omitting mode and name means mode="light", name="Theme"."""
    assert plasma_colors.render(real_tokens) == plasma_colors.render(
        real_tokens, "light", "Theme"
    )


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_real_tokens_section_order_and_keys(real_tokens: dict, mode: str) -> None:
    """Sections appear in the specified order and each has its keys in order."""
    sections = _parse(plasma_colors.render(real_tokens, mode))
    assert [name for name, _ in sections] == list(EXPECTED_KEYS)
    for name, pairs in sections:
        assert [key for key, _ in pairs] == EXPECTED_KEYS[name], name


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_real_tokens_file_shape(real_tokens: dict, mode: str) -> None:
    """One blank line between sections, one trailing newline, RGB triplets."""
    text = plasma_colors.render(real_tokens, mode, "Golden")
    assert text.endswith("\n")
    assert not text.endswith("\n\n")
    # WHY split on the blank line: every block must be exactly one section.
    blocks = text[:-1].split("\n\n")
    assert len(blocks) == len(EXPECTED_KEYS)
    assert all(block.startswith("[") for block in blocks)
    assert "\r" not in text

    rgb = re.compile(r"^\d{1,3},\d{1,3},\d{1,3}$")
    for name, pairs in _parse(text):
        if name.startswith("Colors:") or name == "WM":
            assert all(rgb.match(value) for _, value in pairs), name
    general = dict(dict(_parse(text))["General"])
    assert general == {"ColorScheme": "Golden", "Name": "Golden"}


def test_output_is_deterministic(real_tokens: dict) -> None:
    """Identical inputs (even from a deep copy) give byte-identical output."""
    first = plasma_colors.render(real_tokens, "dark", "Same")
    second = plasma_colors.render(copy.deepcopy(real_tokens), "dark", "Same")
    assert first == second


def test_accent_change_alters_only_accent_lines(real_tokens: dict) -> None:
    """Changing light accent rewrites exactly the accent-derived lines, light only."""
    changed = copy.deepcopy(real_tokens)
    changed["color"]["light"]["accent"] = "#010203"

    before = plasma_colors.render(real_tokens, "light")
    after = plasma_colors.render(changed, "light")
    assert before != after

    # Same structure, so lines can be compared pairwise; every differing line
    # must now carry the new accent, i.e. no unrelated token was touched.
    before_lines, after_lines = before.splitlines(), after.splitlines()
    assert len(before_lines) == len(after_lines)
    diff = [(b, a) for b, a in zip(before_lines, after_lines) if b != a]
    assert diff
    assert all(new.endswith("=1,2,3") for _, new in diff)
    view = dict(dict(_parse(after))["Colors:View"])
    assert view["DecorationFocus"] == "1,2,3"

    # The dark palette is a separate token set and must not move.
    assert plasma_colors.render(real_tokens, "dark") == plasma_colors.render(
        changed, "dark"
    )


@pytest.mark.parametrize(
    "token",
    ["separator", "shadow", "button_close", "button_minimize", "button_maximize"],
)
def test_unused_tokens_do_not_change_output(real_tokens: dict, token: str) -> None:
    """Tokens the KDE scheme has no key for must not influence the output."""
    changed = copy.deepcopy(real_tokens)
    changed["color"]["light"][token] = "#0A0B0C"
    assert plasma_colors.render(changed, "light") == plasma_colors.render(
        real_tokens, "light"
    )


@pytest.mark.parametrize("bad_mode", ["sepia", "", "Light", "DARK", None])
def test_invalid_mode_raises_value_error(real_tokens: dict, bad_mode: object) -> None:
    """Anything except the exact strings "light" and "dark" is rejected."""
    with pytest.raises(ValueError):
        plasma_colors.render(real_tokens, bad_mode)  # type: ignore[arg-type]
