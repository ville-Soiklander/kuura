"""
Tests for the Calamares branding generator (design.generators.calamares_branding).

The golden text below is written out by hand from the module's own locked output
spec (design/generators/calamares_branding.py's docstring's EXACT OUTPUT section),
not computed with the generator itself - a wrong key, a wrong indent or a leaked
literal cannot hide behind shared code, matching design/tests/test_fontconfig.py's
and design/tests/test_kwin_motion.py's own convention.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
import yaml

from design.generators.calamares_branding import render

# The real design tokens live next to the tests' parent package (design/).
REAL_TOKENS_PATH = Path(__file__).resolve().parent.parent / "tokens.json"

# A small synthetic token tree with distinct, easy-to-spot colour values, so a
# test cannot pass by coincidentally matching the real tokens.json's own values.
SYNTHETIC_TOKENS = {
    "color": {
        "light": {"window": "#111111", "text": "#222222", "accent": "#333333", "accent_text": "#444444"},
        "dark": {"window": "#AAAAAA", "text": "#BBBBBB", "accent": "#CCCCCC", "accent_text": "#DDDDDD"},
    },
}

SYNTHETIC_GOLDEN = (
    "# Calamares branding - generated from design/tokens.json, do not edit.\n"
    "componentName: kuura\n"
    "welcomeStyleCalamares: true\n"
    "welcomeExpandingLogo: true\n"
    "strings:\n"
    '  productName: "Kuura"\n'
    '  shortProductName: "Kuura"\n'
    '  version: "0.1.0"\n'
    '  versionedName: "Kuura 0.1.0"\n'
    "images:\n"
    '  productIcon: "systray.svg"\n'
    '  productLogo: "systray.svg"\n'
    '  productWelcome: "kuura-vertical-dawn-light.png"\n'
    "style:\n"
    '  SidebarBackground: "#AAAAAA"\n'
    '  SidebarText: "#BBBBBB"\n'
    '  SidebarBackgroundCurrent: "#CCCCCC"\n'
    '  SidebarTextCurrent: "#DDDDDD"\n'
    "slideshow: []\n"
)


def test_golden_output_synthetic_tokens() -> None:
    """The entire YAML output equals the hand-written golden text above."""
    assert render(SYNTHETIC_TOKENS, "kuura") == SYNTHETIC_GOLDEN


def test_uses_dark_palette_not_light() -> None:
    """The style: section must come from color.dark, never color.light - see the
    module docstring's "WHY the dark palette specifically" section."""
    text = render(SYNTHETIC_TOKENS, "kuura")
    assert "#AAAAAA" in text  # dark.window
    assert "#BBBBBB" in text  # dark.text
    assert "#CCCCCC" in text  # dark.accent
    assert "#DDDDDD" in text  # dark.accent_text
    # None of the light-mode synthetic colours must leak into the output.
    assert "#111111" not in text
    assert "#222222" not in text
    assert "#333333" not in text
    assert "#444444" not in text


def test_name_is_capitalized_for_product_strings_but_not_componentname() -> None:
    """`name` becomes `name.capitalize()` for the strings:, but componentName: and
    the image filenames keep the raw, lowercase name (it must match the real
    installed directory name and the real generated wallpaper filename)."""
    text = render(SYNTHETIC_TOKENS, "kuura")
    assert 'productName: "Kuura"' in text
    assert "componentName: kuura" in text
    assert "componentName: Kuura" not in text
    assert "kuura-vertical-dawn-light.png" in text


def test_slideshow_key_is_present_as_empty_sequence() -> None:
    """docs/ISO_CONTRACT.md's own locked decision is still "no slideshow, no new
    artwork" - but real Calamares 3.4.2 (Branding.cpp, confirmed 2026-10-08 by a
    real live boot plus re-reading the pinned-tag source) bails fatally if the
    `slideshow:` key is absent at all. `slideshow: []` is the correct way to
    express "no slideshow" - present, but an empty sequence - see the module
    docstring's REVISED 2026-10-08 section for the full story."""
    text = render(SYNTHETIC_TOKENS, "kuura")
    assert "slideshow: []" in text


def test_images_reference_the_systray_glyph_and_one_wallpaper() -> None:
    """productIcon/productLogo reuse the systray glyph; productWelcome reuses one
    specific, fixed wallpaper composition/mode pair (see module docstring)."""
    text = render(SYNTHETIC_TOKENS, "kuura")
    assert 'productIcon: "systray.svg"' in text
    assert 'productLogo: "systray.svg"' in text
    assert 'productWelcome: "kuura-vertical-dawn-light.png"' in text


def test_output_is_valid_yaml_with_expected_keys() -> None:
    """The output parses cleanly as YAML (PyYAML, already a project dependency) and
    has exactly the keys the module docstring's EXACT OUTPUT spec names."""
    text = render(SYNTHETIC_TOKENS, "kuura")
    doc = yaml.safe_load(text)

    assert doc["componentName"] == "kuura"
    assert doc["welcomeStyleCalamares"] is True
    assert doc["welcomeExpandingLogo"] is True
    assert doc["slideshow"] == []

    assert doc["strings"]["productName"] == "Kuura"
    assert doc["strings"]["shortProductName"] == "Kuura"
    assert doc["strings"]["version"] == "0.1.0"
    assert doc["strings"]["versionedName"] == "Kuura 0.1.0"

    assert doc["images"]["productIcon"] == "systray.svg"
    assert doc["images"]["productLogo"] == "systray.svg"
    assert doc["images"]["productWelcome"] == "kuura-vertical-dawn-light.png"

    assert doc["style"]["SidebarBackground"] == "#AAAAAA"
    assert doc["style"]["SidebarText"] == "#BBBBBB"
    assert doc["style"]["SidebarBackgroundCurrent"] == "#CCCCCC"
    assert doc["style"]["SidebarTextCurrent"] == "#DDDDDD"


def test_output_ends_with_single_trailing_newline() -> None:
    """Exactly one trailing newline, no CR (matches the other generators' convention)."""
    text = render(SYNTHETIC_TOKENS, "kuura")
    assert text.endswith("\n")
    assert not text.endswith("\n\n")
    assert "\r" not in text


def test_componentname_matches_a_different_distro_name() -> None:
    """componentName: must track `name` exactly - Calamares' real Branding.cpp
    refuses to start if componentName does not match the branding directory name,
    so this value can never drift from the directory a PKGBUILD installs it to."""
    text = render(SYNTHETIC_TOKENS, "frost")
    assert "componentName: frost" in text
    assert "frost-vertical-dawn-light.png" in text
    assert 'productName: "Frost"' in text


def test_missing_dark_color_key_raises_keyerror() -> None:
    """A tokens dict missing color.dark.* must raise KeyError, not silently
    default, matching every other generator's trust-the-caller convention."""
    with pytest.raises(KeyError):
        render({"color": {"dark": {}}}, "kuura")


class TestTokenPropagation:
    """
    Mutating design/tokens.json's color.dark.* must change the corresponding
    style: value in the output - mirroring the spirit of
    design/tests/test_dod.py's own token-mutation-propagates pattern, applied to
    this single-generator module instead of design.generate's cross-generator DoD.
    """

    def test_changing_dark_accent_changes_only_the_two_current_step_keys(self) -> None:
        tokens = json.loads(REAL_TOKENS_PATH.read_text(encoding="utf-8"))
        original = render(tokens, "kuura")

        changed = copy.deepcopy(tokens)
        changed["color"]["dark"]["accent"] = "#123456"
        mutated = render(changed, "kuura")

        assert original != mutated
        assert "#123456" in mutated
        # accent_text is untouched, so SidebarTextCurrent must still show the
        # original accent_text value, not drift because accent changed.
        assert f'SidebarTextCurrent: "{tokens["color"]["dark"]["accent_text"]}"' in mutated

    def test_changing_light_accent_does_not_affect_output(self) -> None:
        """This generator never reads color.light.* - see module docstring."""
        tokens = json.loads(REAL_TOKENS_PATH.read_text(encoding="utf-8"))
        original = render(tokens, "kuura")

        changed = copy.deepcopy(tokens)
        changed["color"]["light"]["accent"] = "#FF00FF"
        changed["color"]["light"]["window"] = "#00FF00"

        assert render(changed, "kuura") == original

    def test_real_tokens_produce_the_real_dark_values(self) -> None:
        """
        Sanity check against the real, committed tokens.json: today's real
        color.dark values show up in the style: section, proving render() reads
        the real tokens rather than being a no-op.
        """
        tokens = json.loads(REAL_TOKENS_PATH.read_text(encoding="utf-8"))
        text = render(tokens, "kuura")
        dark = tokens["color"]["dark"]
        assert f'SidebarBackground: "{dark["window"]}"' in text
        assert f'SidebarText: "{dark["text"]}"' in text
        assert f'SidebarBackgroundCurrent: "{dark["accent"]}"' in text
        assert f'SidebarTextCurrent: "{dark["accent_text"]}"' in text
