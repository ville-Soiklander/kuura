"""Tests for the SDDM greeter theme generator (mirrors design/tests/test_firefox_theme.py)."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from design.generators.sddm_theme import render_main_qml, render_theme_conf

# Synthetic tokens containing every colour key and all required non-colour keys
# this generator reads, mirroring design/tests/test_firefox_theme.py's own
# fixture shape.
_TOKENS = {
    "color": {
        "light": {
            "window": "#010203", "surface": "#020304", "surface_alt": "#030405",
            "text": "#040506", "text_secondary": "#050607", "text_disabled": "#060708",
            "accent": "#070809", "accent_text": "#08090A", "separator": "#090A0B",
            "link": "#0A0B0C", "link_visited": "#0B0C0D",
            "error": "#0C0D0E", "warning": "#0D0E0F", "success": "#0E0F10",
            "tooltip_bg": "#0F1011", "tooltip_text": "#101112", "shadow": "#00000033",
            "button_close": "#111213", "button_minimize": "#121314", "button_maximize": "#131415",
        },
        "dark": {
            "window": "#201202", "surface": "#212223", "surface_alt": "#222324",
            "text": "#232425", "text_secondary": "#242526", "text_disabled": "#252627",
            "accent": "#262728", "accent_text": "#272829", "separator": "#28292A",
            "link": "#292A2B", "link_visited": "#2A2B2C",
            "error": "#2B2C2D", "warning": "#2C2D2E", "success": "#2D2E2F",
            "tooltip_bg": "#2E2F30", "tooltip_text": "#2F3031", "shadow": "#00000066",
            "button_close": "#303132", "button_minimize": "#313233", "button_maximize": "#323334",
        },
    },
    "radius": {"window": 14, "panel": 12, "menu": 10, "card": 12, "button": 8, "field": 8, "tooltip": 8, "icon": "squircle-n5"},
    "type": {"family_ui": "TestFont", "family_mono": "TestMono", "size": {"caption": 11, "body": 13, "title": 15, "header": 22}, "weight": {"regular": 400, "medium": 500, "semibold": 600}, "tracking": {"body": -0.01, "header": -0.02}},
    "motion": {"duration": {"instant": 100, "fast": 180, "base": 260, "slow": 400}, "easing_standard": "cubic-bezier(0.32, 0.72, 0, 1)", "easing_spring": {"mass": 1, "stiffness": 340, "damping": 32}},
    "spacing": {"grid": 4, "gutter": 12, "section": 20},
}


class TestRenderThemeConf:
    """Tests for render_theme_conf()."""

    def test_bad_mode_raises_valueerror(self):
        with pytest.raises(ValueError, match="light.*dark"):
            render_theme_conf(_TOKENS, mode="invalid", name="theme")

    def test_exact_keys_in_order(self):
        result = render_theme_conf(_TOKENS, mode="dark", name="theme")
        assert result.splitlines() == [
            "[General]",
            "background=#201202",
            "accent=#262728",
            "fontSize=13",
        ]

    def test_light_mode_uses_light_palette(self):
        result = render_theme_conf(_TOKENS, mode="light", name="theme")
        assert "background=#010203" in result
        assert "accent=#070809" in result

    def test_name_not_leaked_into_output(self):
        result = render_theme_conf(_TOKENS, mode="dark", name="my-distro-name")
        assert "my-distro-name" not in result

    def test_ends_with_exactly_one_newline(self):
        result = render_theme_conf(_TOKENS, mode="dark", name="theme")
        assert result.endswith("\n")
        assert not result.endswith("\n\n")

    def test_deterministic(self):
        assert render_theme_conf(_TOKENS, mode="dark", name="theme") == render_theme_conf(_TOKENS, mode="dark", name="theme")

    def test_changing_accent_token_changes_output(self):
        """Regression: a changed colour token must actually reach theme.conf."""
        modified = copy.deepcopy(_TOKENS)
        modified["color"]["dark"]["accent"] = "#ff00ff"

        original = render_theme_conf(_TOKENS, mode="dark", name="theme")
        changed = render_theme_conf(modified, mode="dark", name="theme")

        assert original != changed
        assert "accent=#ff00ff" in changed

    def test_real_tokens_json_renders_without_error(self):
        """End-to-end smoke test against the real, checked-in tokens.json."""
        from design.validate import load_tokens

        tokens = load_tokens(Path(__file__).parent.parent / "tokens.json")
        result = render_theme_conf(tokens, mode="dark", name="theme")
        assert result.startswith("[General]\n")
        assert result.endswith("\n")


class TestRenderMainQml:
    """Tests for render_main_qml()."""

    def test_bad_mode_raises_valueerror(self):
        with pytest.raises(ValueError, match="light.*dark"):
            render_main_qml(_TOKENS, mode="invalid", name="theme")

    def test_confirmed_imports_present(self):
        """Only the plain-QtQuick import surface named in the module docstring."""
        result = render_main_qml(_TOKENS, mode="dark", name="theme")
        import_lines = [line for line in result.splitlines() if line.startswith("import ")]
        assert import_lines == [
            "import QtQuick",
            "import QtQuick.Controls as QQC2",
            "import QtQuick.Layouts",
        ]
        # No dependency on Kirigami / PlasmaComponents3 / the theme-local Breeze
        # components module (see module docstring's scope decision) - checked
        # against the import lines only, since the module docstring's own prose
        # legitimately names them when explaining what was deliberately left out.
        assert not any("kirigami" in line.lower() or "plasma" in line.lower() for line in import_lines)

    def test_confirmed_sddm_api_surface_used(self):
        """Every real, confirmed sddm/userModel/sessionModel/config call actually appears."""
        result = render_main_qml(_TOKENS, mode="dark", name="theme")
        for token in (
            "sddm.login(", "onLoginFailed", "onLoginSucceeded",
            "sddm.canSuspend", "sddm.canReboot", "sddm.canPowerOff",
            "sddm.suspend()", "sddm.reboot()", "sddm.powerOff()",
            "userModel", "userModel.lastUser", "userModel.lastIndex",
            "sessionModel", "sessionModel.lastIndex",
            'config.stringValue("background")', 'config.stringValue("accent")',
            'config.intValue("fontSize")',
        ):
            assert token in result, f"Missing confirmed API use: {token}"

    def test_background_and_accent_read_from_config_not_baked(self):
        """These two colours must come from theme.conf at runtime, never a literal."""
        result = render_main_qml(_TOKENS, mode="dark", name="theme")
        # The dark palette's window/accent hex must NOT appear as bare QML colour
        # literals - they are only reachable via config.stringValue() above.
        assert '"#201202"' not in result
        assert '"#262728"' not in result

    def test_literal_colors_baked_for_the_selected_mode(self):
        """Every OTHER colour token is baked as a literal, and changes with mode."""
        dark = render_main_qml(_TOKENS, mode="dark", name="theme")
        light = render_main_qml(_TOKENS, mode="light", name="theme")
        assert "#212223" in dark  # tokens.color.dark.surface via to_qml()
        assert "#020304" in light  # tokens.color.light.surface via to_qml()
        assert dark != light

    def test_radius_and_type_tokens_used(self):
        result = render_main_qml(_TOKENS, mode="dark", name="theme")
        assert "radiusWindow: 14" in result
        assert "radiusField: 8" in result
        assert "radiusButton: 8" in result
        assert "radiusMenu: 10" in result
        assert '"TestFont"' in result
        assert "fontSizeHeader: 22" in result
        assert "transitionMs: 180" in result

    def test_name_not_leaked_into_output(self):
        result = render_main_qml(_TOKENS, mode="dark", name="my-distro-name")
        assert "my-distro-name" not in result

    def test_ends_with_exactly_one_newline(self):
        result = render_main_qml(_TOKENS, mode="dark", name="theme")
        assert result.endswith("\n")
        assert not result.endswith("\n\n")

    def test_deterministic(self):
        assert render_main_qml(_TOKENS, mode="dark", name="theme") == render_main_qml(_TOKENS, mode="dark", name="theme")

    def test_balanced_braces(self):
        """A gross but cheap syntax sanity check before qmllint ever runs."""
        result = render_main_qml(_TOKENS, mode="dark", name="theme")
        assert result.count("{") == result.count("}")

    def test_real_tokens_json_renders_without_error(self):
        """End-to-end smoke test against the real, checked-in tokens.json."""
        from design.validate import load_tokens

        tokens = load_tokens(Path(__file__).parent.parent / "tokens.json")
        result = render_main_qml(tokens, mode="dark", name="theme")
        assert result.endswith("\n")
        assert result.count("{") == result.count("}")
