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

from design.generators.cpp_header import render

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
    assert "inline constexpr float kMaterialEdgeHighlightWidth = 1.0f;" in text
    assert "inline constexpr float kMaterialEdgeHighlightOpacity = 0.28f;" in text
    assert "inline constexpr float kMaterialNoise = 0.02f;" in text


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
