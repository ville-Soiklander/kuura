"""
Tests for the C++ token header generator (design.generators.cpp_header).

The golden text below is written out by hand from the module's own locked output
spec (design/generators/cpp_header.py's docstring), not computed with the generator
itself - a wrong constant name, a wrong type mapping or a dropped/leaked token cannot
hide behind shared code, matching design/tests/test_plasma_layout.py's own convention.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from design.generators.cpp_header import render, render_colors

# The real design tokens live next to the tests' parent package (design/).
REAL_TOKENS_PATH = Path(__file__).resolve().parent.parent / "tokens.json"

# A small, synthetic token tree covering every leaf type this generator maps
# (bool, int, float, str), a nested path needing both "." and "_" splitting, and
# both excluded top-level keys (_meta, color) - so a leak of either can never hide
# behind a coincidence with an unrelated value already in the output.
SYNTHETIC_TOKENS = {
    "_meta": {"version": 1, "palette_status": "ignored"},
    "material": {
        "refraction": {"strength": 0.035, "edge_falloff": 12},
        "noise": 0.02,
    },
    "panel": {"shelf_icon": 52},
    "radius": {"icon": "squircle-n5"},
    "flag": {"enabled": True, "disabled": False},
    "color": {"light": {"window": "#FFFFFF"}, "dark": {"window": "#000000"}},
}

SYNTHETIC_GOLDEN = (
    "#pragma once\n"
    "\n"
    "// Design tokens - generated from design/tokens.json, do not edit by hand.\n"
    "// Numeric/string values only: colour tokens are mode-dependent and are not\n"
    "// exported here (see design/generators/qml_singleton.py for those).\n"
    "namespace Kuura::Tokens\n"
    "{\n"
    "inline constexpr bool kFlagDisabled = false;\n"
    "inline constexpr bool kFlagEnabled = true;\n"
    "inline constexpr float kMaterialNoise = 0.02f;\n"
    "inline constexpr int kMaterialRefractionEdgeFalloff = 12;\n"
    "inline constexpr float kMaterialRefractionStrength = 0.035f;\n"
    "inline constexpr int kPanelShelfIcon = 52;\n"
    'inline constexpr const char *const kRadiusIcon = "squircle-n5";\n'
    "} // namespace Kuura::Tokens\n"
)


def test_golden_output_synthetic_tokens() -> None:
    """The entire header output equals the hand-written golden text above."""
    assert render(SYNTHETIC_TOKENS) == SYNTHETIC_GOLDEN


def test_meta_and_color_are_excluded() -> None:
    """
    "_meta" and "color" leaves must never appear as constants - _meta is metadata,
    not a design value, and colour is mode-dependent while this generator's locked
    signature takes no mode argument at all (see the module docstring).
    """
    text = render(SYNTHETIC_TOKENS)
    assert "kVersion" not in text
    assert "kPaletteStatus" not in text
    assert "kColor" not in text
    assert "kLightWindow" not in text
    assert "kDarkWindow" not in text
    assert "#FFFFFF" not in text
    assert "#000000" not in text


def test_bool_type_mapping() -> None:
    """bool leaves map to C++ `bool` with lowercase true/false, checked before int."""
    text = render(SYNTHETIC_TOKENS)
    assert "inline constexpr bool kFlagEnabled = true;" in text
    assert "inline constexpr bool kFlagDisabled = false;" in text
    # Neither must be mistaken for `int` (bool is an int subclass in Python).
    assert "int kFlagEnabled" not in text
    assert "int kFlagDisabled" not in text


def test_int_type_mapping() -> None:
    """int leaves map to C++ `int`, printed with no suffix."""
    text = render(SYNTHETIC_TOKENS)
    assert "inline constexpr int kPanelShelfIcon = 52;" in text
    assert "inline constexpr int kMaterialRefractionEdgeFalloff = 12;" in text


def test_float_type_mapping_has_f_suffix() -> None:
    """
    float leaves map to C++ `float` with a trailing `f` - required so the literal is
    not silently narrowed from `double` (C++'s default for an unsuffixed decimal).
    """
    text = render(SYNTHETIC_TOKENS)
    assert "inline constexpr float kMaterialRefractionStrength = 0.035f;" in text
    assert "inline constexpr float kMaterialNoise = 0.02f;" in text
    # No unsuffixed float literal anywhere (would compile as `double`, not `float`).
    assert "= 0.035;" not in text
    assert "= 0.02;" not in text


def test_str_type_mapping() -> None:
    """str leaves map to C++ `const char *const`, double-quoted."""
    text = render(SYNTHETIC_TOKENS)
    assert 'inline constexpr const char *const kRadiusIcon = "squircle-n5";' in text


def test_string_with_backslash_and_quote_is_escaped() -> None:
    """Backslash and double quote inside a string leaf are backslash-escaped."""
    tokens = {"radius": {"icon": 'test\\path"'}}
    text = render(tokens)
    assert 'kRadiusIcon = "test\\\\path\\"";' in text


def test_underscore_and_hyphen_paths_become_pascal_case() -> None:
    """
    Both "_" (e.g. shelf_icon) and "." (dict nesting) are segment boundaries, and
    every segment is capitalised: material.refraction.edge_falloff ->
    kMaterialRefractionEdgeFalloff, not kMaterialRefractionEdge_falloff.
    """
    text = render(SYNTHETIC_TOKENS)
    assert "kMaterialRefractionEdgeFalloff" in text
    assert "edge_falloff" not in text
    assert "Edge_falloff" not in text


def test_output_is_sorted_ascending_by_constant_name() -> None:
    """Constants appear in ascending string order of their full "k..." name."""
    text = render(SYNTHETIC_TOKENS)
    # WHY split on "=" then take the last whitespace token before it: the type
    # itself can contain spaces ("const char *const"), so a fixed word index
    # would not reliably land on the constant name, but the name is always the
    # last token immediately before "=" regardless of how many words the type has.
    names = [
        line.split("=")[0].split()[-1]
        for line in text.splitlines()
        if line.startswith("inline constexpr")
    ]
    assert names == sorted(names)
    assert names == [
        "kFlagDisabled",
        "kFlagEnabled",
        "kMaterialNoise",
        "kMaterialRefractionEdgeFalloff",
        "kMaterialRefractionStrength",
        "kPanelShelfIcon",
        "kRadiusIcon",
    ]


def test_output_is_deterministic() -> None:
    """Identical inputs (even from a deep copy) give byte-identical output."""
    first = render(SYNTHETIC_TOKENS)
    second = render(copy.deepcopy(SYNTHETIC_TOKENS))
    assert first == second


def test_output_ends_with_single_trailing_newline() -> None:
    """Exactly one trailing newline, no CR (matches the other generators' convention)."""
    text = render(SYNTHETIC_TOKENS)
    assert text.endswith("\n")
    assert not text.endswith("\n\n")
    assert "\r" not in text


def test_output_has_pragma_once_and_namespace() -> None:
    """The header is a real, standalone, includable C++ header."""
    text = render(SYNTHETIC_TOKENS)
    assert text.startswith("#pragma once\n")
    assert "namespace Kuura::Tokens\n{\n" in text
    assert text.rstrip("\n").endswith("} // namespace Kuura::Tokens")


def test_real_tokens_produce_the_five_frost_material_constants() -> None:
    """
    Rendering the real design/tokens.json produces exactly the five material.*
    constants frost.h's apply() docstring lists as needed by the real shader
    (strength, edge_falloff, width, opacity, noise), with the real committed values.
    """
    real_tokens = json.loads(REAL_TOKENS_PATH.read_text(encoding="utf-8"))
    text = render(real_tokens)
    assert "inline constexpr float kMaterialRefractionStrength = 0.035f;" in text
    assert "inline constexpr int kMaterialRefractionEdgeFalloff = 12;" in text
    assert "inline constexpr float kMaterialEdgeHighlightWidth = 1.5f;" in text
    assert "inline constexpr float kMaterialEdgeHighlightOpacity = 0.55f;" in text
    assert "inline constexpr float kMaterialNoise = 0.03f;" in text


def test_real_tokens_changing_a_material_value_only_changes_that_constant() -> None:
    """Changing one token rewrites only its own constant line, nothing else."""
    real_tokens = json.loads(REAL_TOKENS_PATH.read_text(encoding="utf-8"))
    changed = copy.deepcopy(real_tokens)
    changed["material"]["refraction"]["strength"] = 0.099

    before = render(real_tokens).splitlines()
    after = render(changed).splitlines()
    assert len(before) == len(after)
    diff = [(b, a) for b, a in zip(before, after, strict=True) if b != a]
    assert diff == [
        (
            "inline constexpr float kMaterialRefractionStrength = 0.035f;",
            "inline constexpr float kMaterialRefractionStrength = 0.099f;",
        )
    ]


def test_real_tokens_color_values_never_leak_in() -> None:
    """None of the real hex colour values from tokens.json appear in the header."""
    real_tokens = json.loads(REAL_TOKENS_PATH.read_text(encoding="utf-8"))
    text = render(real_tokens)
    for mode in ("light", "dark"):
        for value in real_tokens["color"][mode].values():
            assert value not in text


def test_real_tokens_export_the_stroke_constants() -> None:
    """stroke.* reach C++ as float constants with the real token values."""
    text = render(json.loads(REAL_TOKENS_PATH.read_text(encoding="utf-8")))
    assert "inline constexpr float kStrokeHairline = 1.0f;" in text
    assert "inline constexpr float kStrokeFocus = 2.0f;" in text


# ---------------------------------------------------------------- render_colors()

# Small colour fixture: an opaque token, a token with explicit alpha, lowercase hex
# input, a two-word key, and keys given out of alphabetical order, so sorting, the
# alpha rule, uppercasing and the naming rule are each exercised.
COLOR_TOKENS = {
    "color": {
        "light": {"window": "#f2f4f7", "shadow": "#00000033", "button_close": "#E5534B"},
        "dark": {"window": "#15181C", "shadow": "#00000066", "button_close": "#E5534B"},
    },
}

COLOR_GOLDEN = (
    "#pragma once\n"
    "\n"
    "// Colour tokens - generated from design/tokens.json, do not edit by hand.\n"
    '// Each value is 0xRRGGBBAA; a "#RRGGBB" token gets AA = FF.\n'
    "#include <cstdint>\n"
    "\n"
    "namespace Kuura::Tokens::Light\n"
    "{\n"
    "inline constexpr std::uint32_t kButtonClose = 0xE5534BFFu;\n"
    "inline constexpr std::uint32_t kShadow = 0x00000033u;\n"
    "inline constexpr std::uint32_t kWindow = 0xF2F4F7FFu;\n"
    "} // namespace Kuura::Tokens::Light\n"
    "\n"
    "namespace Kuura::Tokens::Dark\n"
    "{\n"
    "inline constexpr std::uint32_t kButtonClose = 0xE5534BFFu;\n"
    "inline constexpr std::uint32_t kShadow = 0x00000066u;\n"
    "inline constexpr std::uint32_t kWindow = 0x15181CFFu;\n"
    "} // namespace Kuura::Tokens::Dark\n"
)


def test_render_colors_golden_output() -> None:
    """The whole colour header equals the hand-written golden text above."""
    assert render_colors(COLOR_TOKENS) == COLOR_GOLDEN


def test_render_colors_naming_rule() -> None:
    """Snake_case keys become k + PascalCase, never keeping an underscore."""
    tokens = {"color": {"light": {"text_secondary": "#5B6470"}, "dark": {"text_secondary": "#98A2AE"}}}
    text = render_colors(tokens)
    assert "kTextSecondary = 0x5B6470FFu;" in text
    assert "kTextSecondary = 0x98A2AEFFu;" in text
    assert "Text_secondary" not in text


def test_render_colors_alpha_handling() -> None:
    """#RRGGBB gets alpha FF; #RRGGBBAA keeps its own alpha digits."""
    tokens = {"color": {"light": {"a": "#102030", "b": "#10203040"}, "dark": {"a": "#000000", "b": "#FFFFFF00"}}}
    text = render_colors(tokens)
    assert "kA = 0x102030FFu;" in text
    assert "kB = 0x10203040u;" in text
    assert "kA = 0x000000FFu;" in text
    assert "kB = 0xFFFFFF00u;" in text


def test_render_colors_sorted_by_constant_name_within_each_mode() -> None:
    """Constants appear in ascending order of the emitted name, in both namespaces."""
    real_tokens = json.loads(REAL_TOKENS_PATH.read_text(encoding="utf-8"))
    text = render_colors(real_tokens)
    for mode in ("Light", "Dark"):
        body = text.split(f"namespace Kuura::Tokens::{mode}\n{{\n")[1].split("}")[0]
        names = [line.split()[4] for line in body.splitlines()]
        assert names == sorted(names)
        assert len(names) == 20


def test_render_colors_real_shadow_values() -> None:
    """The decoration relies on shadow 0x00000033u (light) and 0x00000066u (dark)."""
    real_tokens = json.loads(REAL_TOKENS_PATH.read_text(encoding="utf-8"))
    text = render_colors(real_tokens)
    light, dark = text.split("\nnamespace Kuura::Tokens::Dark\n")
    assert "kShadow = 0x00000033u;" in light
    assert "kShadow = 0x00000066u;" in dark


def test_render_colors_is_deterministic_and_lf_only() -> None:
    """Same input, same bytes; no carriage return; exactly one trailing newline."""
    real_tokens = json.loads(REAL_TOKENS_PATH.read_text(encoding="utf-8"))
    first = render_colors(real_tokens)
    assert first == render_colors(copy.deepcopy(real_tokens))
    assert "\r" not in first
    assert first.endswith("\n") and not first.endswith("\n\n")


@pytest.mark.parametrize("bad", ["#12345", "#1234567", "#GGGGGG", "123456", "red", "", 12, None])
def test_render_colors_rejects_malformed_colour(bad: object) -> None:
    """A value that is not #RRGGBB / #RRGGBBAA raises ValueError naming the path."""
    tokens = {"color": {"light": {"window": bad}, "dark": {"window": "#000000"}}}
    with pytest.raises(ValueError, match="color.light.window"):
        render_colors(tokens)


@pytest.mark.parametrize("tokens", [{}, {"color": {}}, {"color": {"light": {}}}, {"color": {"light": {}, "dark": []}}])
def test_render_colors_rejects_missing_palettes(tokens: dict) -> None:
    """A missing or non-dict light/dark palette raises ValueError."""
    with pytest.raises(ValueError, match="color"):
        render_colors(tokens)


def test_render_does_not_leak_colours_and_includes_light_hairline_tokens() -> None:
    """tokens.h stays colour-free and exports the four Frost light-rim constants."""
    real_tokens = json.loads(REAL_TOKENS_PATH.read_text(encoding="utf-8"))
    text = render(real_tokens)
    assert "0x" not in text
    assert "inline constexpr float kMaterialEdgeHighlightLightHairlineOpacity = 0.3f;" in text
    assert "inline constexpr float kMaterialEdgeHighlightLightHairlineWidth = 1.0f;" in text
    assert "inline constexpr float kMaterialEdgeHighlightLightLumaLow = 0.55f;" in text
    assert "inline constexpr float kMaterialEdgeHighlightLightLumaHigh = 0.85f;" in text
