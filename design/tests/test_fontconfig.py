"""
Tests for the fontconfig alias generator (design.generators.fontconfig).

The golden text below is written out by hand from the module's own locked output
spec (design/generators/fontconfig.py's docstring's EXACT OUTPUT section), not
computed with the generator itself - a wrong element, a wrong indent or a leaked
literal cannot hide behind shared code, matching design/tests/test_cpp_header.py's
and design/tests/test_plasma_layout.py's own convention.
"""

from __future__ import annotations

import copy
import json
import xml.etree.ElementTree as ET
from pathlib import Path

from design.generators.fontconfig import render

# The real design tokens live next to the tests' parent package (design/).
REAL_TOKENS_PATH = Path(__file__).resolve().parent.parent / "tokens.json"

# A small synthetic token tree with distinct, easy-to-spot family names, so a test
# that mutates one family cannot pass by coincidentally matching the other.
SYNTHETIC_TOKENS = {
    "type": {"family_ui": "Synthetic Sans Family", "family_mono": "Synthetic Mono Family"},
}

SYNTHETIC_GOLDEN = (
    '<?xml version="1.0"?>\n'
    '<!DOCTYPE fontconfig SYSTEM "fonts.dtd">\n'
    "<fontconfig>\n"
    "  <alias>\n"
    "    <family>Kuura Sans</family>\n"
    "    <prefer><family>Synthetic Sans Family</family></prefer>\n"
    "  </alias>\n"
    "  <alias>\n"
    "    <family>Kuura Mono</family>\n"
    "    <prefer><family>Synthetic Mono Family</family></prefer>\n"
    "  </alias>\n"
    "</fontconfig>\n"
)


def test_golden_output_synthetic_tokens() -> None:
    """The entire XML output equals the hand-written golden text above."""
    assert render(SYNTHETIC_TOKENS, "kuura") == SYNTHETIC_GOLDEN


def test_name_is_capitalized_for_the_alias_family() -> None:
    """`name` becomes `name.capitalize()` in both alias <family> elements."""
    text = render(SYNTHETIC_TOKENS, "kuura")
    assert "<family>Kuura Sans</family>" in text
    assert "<family>Kuura Mono</family>" in text
    # The raw, uncapitalized name must not appear as a family name.
    assert "<family>kuura Sans</family>" not in text
    assert "<family>kuura Mono</family>" not in text


def test_output_is_well_formed_xml() -> None:
    """The output parses cleanly as XML (stdlib ElementTree, no new dependency)."""
    text = render(SYNTHETIC_TOKENS, "kuura")
    root = ET.fromstring(text)
    assert root.tag == "fontconfig"
    aliases = root.findall("alias")
    assert len(aliases) == 2


def test_output_ends_with_single_trailing_newline() -> None:
    """Exactly one trailing newline, no CR (matches the other generators' convention)."""
    text = render(SYNTHETIC_TOKENS, "kuura")
    assert text.endswith("\n")
    assert not text.endswith("\n\n")
    assert "\r" not in text


def test_output_uses_prefer_not_default_or_accept() -> None:
    """
    Must use <prefer> (fontconfig's real "substitute this family first" semantic
    for a pure rename), never <default> or <accept>, which mean something else.
    """
    text = render(SYNTHETIC_TOKENS, "kuura")
    assert "<prefer>" in text
    assert "<default>" not in text
    assert "<accept>" not in text


class TestTokenPropagation:
    """
    Mutating design/tokens.json's type.family_ui / type.family_mono must change
    the corresponding <prefer> family in the output - mirroring the spirit of
    design/tests/test_dod.py's own token-mutation-propagates pattern, applied to
    this single-generator module instead of design.generate's cross-generator DoD.
    """

    def test_changing_family_ui_changes_only_the_sans_alias(self) -> None:
        tokens = json.loads(REAL_TOKENS_PATH.read_text(encoding="utf-8"))
        original = render(tokens, "kuura")

        changed = copy.deepcopy(tokens)
        changed["type"]["family_ui"] = "Some Other UI Family"
        mutated = render(changed, "kuura")

        assert original != mutated
        assert "Some Other UI Family" in mutated
        assert "Some Other UI Family" not in original
        # The mono alias must stay byte-identical: only the Sans <prefer> line changes.
        original_lines = original.splitlines()
        mutated_lines = mutated.splitlines()
        assert len(original_lines) == len(mutated_lines)
        diff = [(o, m) for o, m in zip(original_lines, mutated_lines, strict=True) if o != m]
        assert diff == [
            (
                f'    <prefer><family>{tokens["type"]["family_ui"]}</family></prefer>',
                "    <prefer><family>Some Other UI Family</family></prefer>",
            )
        ]

    def test_changing_family_mono_changes_only_the_mono_alias(self) -> None:
        tokens = json.loads(REAL_TOKENS_PATH.read_text(encoding="utf-8"))
        original = render(tokens, "kuura")

        changed = copy.deepcopy(tokens)
        changed["type"]["family_mono"] = "Some Other Mono Family"
        mutated = render(changed, "kuura")

        assert original != mutated
        assert "Some Other Mono Family" in mutated
        assert "Some Other Mono Family" not in original
        original_lines = original.splitlines()
        mutated_lines = mutated.splitlines()
        assert len(original_lines) == len(mutated_lines)
        diff = [(o, m) for o, m in zip(original_lines, mutated_lines, strict=True) if o != m]
        assert diff == [
            (
                f'    <prefer><family>{tokens["type"]["family_mono"]}</family></prefer>',
                "    <prefer><family>Some Other Mono Family</family></prefer>",
            )
        ]

    def test_real_tokens_produce_inter_and_jetbrains_mono(self) -> None:
        """
        Sanity check against the real, committed tokens.json: today's real values
        (Inter / JetBrains Mono) show up in the output, proving render() actually
        reads tokens["type"]["family_ui"/"family_mono"] rather than being a no-op.
        """
        tokens = json.loads(REAL_TOKENS_PATH.read_text(encoding="utf-8"))
        text = render(tokens, "kuura")
        assert "<prefer><family>Inter</family></prefer>" in text
        assert "<prefer><family>JetBrains Mono</family></prefer>" in text
        assert "<family>Kuura Sans</family>" in text
        assert "<family>Kuura Mono</family>" in text
