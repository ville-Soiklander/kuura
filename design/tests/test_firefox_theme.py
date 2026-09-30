"""Tests for the Firefox userChrome.css/userContent.css generator."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from design.generators.firefox_theme import render_chrome, render_content

# Synthetic tokens containing every colour key and all required non-colour keys
# this generator reads, mirroring design/tests/test_gtk_css.py's own fixture shape.
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


class TestRenderChrome:
    """Tests for render_chrome()."""

    def test_bad_mode_raises_valueerror(self):
        """An invalid mode is rejected the same way every other generator rejects one."""
        with pytest.raises(ValueError, match="light.*dark"):
            render_chrome(_TOKENS, mode="invalid", name="theme")

    def test_both_modes_emitted_regardless_of_mode_argument(self):
        """Per the locked docstring, BOTH palettes always land in one file."""
        light_call = render_chrome(_TOKENS, mode="light", name="theme")
        dark_call = render_chrome(_TOKENS, mode="dark", name="theme")

        # Calling with mode="light" or mode="dark" must produce the identical
        # file: the argument only exists for signature parity, it never
        # filters the output (see module docstring).
        assert light_call == dark_call

        assert "@media (prefers-color-scheme: light)" in light_call
        assert "@media (prefers-color-scheme: dark)" in light_call
        # Both palettes' colours must actually be present, not just the media query text.
        assert "#010203" in light_call.lower() or "#010203".lower() in light_call.lower()
        assert "#212223" in light_call.lower()

    def test_confirmed_selectors_present(self):
        """Every confirmed real selector from the research pass is actually used."""
        result = render_chrome(_TOKENS, mode="light", name="theme")
        for selector in (
            "#navigator-toolbox", "#toolbar-menubar", "#nav-bar", "#TabsToolbar",
            "#urlbar", "#urlbar-background", ".urlbarView", "#identity-icon",
            ".urlbar-input-container",
        ):
            assert selector in result, f"Missing confirmed selector: {selector}"

    def test_radius_and_type_tokens_used(self):
        """Radius/type/motion/spacing token values must appear, never a literal guess."""
        result = render_chrome(_TOKENS, mode="light", name="theme")
        assert "8px" in result  # radius.field == radius.button == 8 in this fixture
        assert "10px" in result  # radius.menu
        assert '"TestFont"' in result
        assert "13px" in result  # type.size.body
        assert "180ms" in result  # motion.duration.fast
        assert "cubic-bezier(0.32, 0.72, 0, 1)" in result

    def test_name_not_leaked_into_output(self):
        """No visible 'kuura' branding belongs in browser chrome (module docstring)."""
        result = render_chrome(_TOKENS, mode="light", name="my-distro-name")
        assert "my-distro-name" not in result

    def test_ends_with_exactly_one_newline(self):
        """Matches every other generator's own output convention in this package."""
        result = render_chrome(_TOKENS, mode="light", name="theme")
        assert result.endswith("\n")
        assert not result.endswith("\n\n")

    def test_deterministic(self):
        """Same tokens in, byte-identical output out."""
        assert render_chrome(_TOKENS, mode="light", name="theme") == render_chrome(_TOKENS, mode="light", name="theme")

    def test_changing_accent_token_changes_output(self):
        """Regression: a changed colour token must actually reach the CSS."""
        modified = copy.deepcopy(_TOKENS)
        modified["color"]["light"]["accent"] = "#FF00FF"

        original = render_chrome(_TOKENS, mode="light", name="theme")
        changed = render_chrome(modified, mode="light", name="theme")

        assert original != changed
        assert "#ff00ff" in changed.lower()

    def test_real_tokens_json_renders_without_error(self):
        """End-to-end smoke test against the real, checked-in tokens.json."""
        from design.validate import load_tokens

        tokens = load_tokens(Path(__file__).parent.parent / "tokens.json")
        result = render_chrome(tokens, mode="light", name="theme")
        assert result.endswith("\n")
        assert "#urlbar-background" in result


class TestRenderContent:
    """Tests for render_content()."""

    def test_bad_mode_raises_valueerror(self):
        """An invalid mode is rejected the same way every other generator rejects one."""
        with pytest.raises(ValueError, match="light.*dark"):
            render_content(_TOKENS, mode="invalid", name="theme")

    def test_scoped_to_about_pages_only(self):
        """userContent.css must never apply to ordinary websites (module docstring)."""
        result = render_content(_TOKENS, mode="light", name="theme")
        assert '@-moz-document url-prefix("about:")' in result

    def test_both_modes_emitted_regardless_of_mode_argument(self):
        """Per the locked docstring, BOTH palettes always land in one file."""
        light_call = render_content(_TOKENS, mode="light", name="theme")
        dark_call = render_content(_TOKENS, mode="dark", name="theme")
        assert light_call == dark_call
        assert "@media (prefers-color-scheme: light)" in light_call
        assert "@media (prefers-color-scheme: dark)" in light_call

    def test_name_not_leaked_into_output(self):
        """No visible 'kuura' branding belongs in browser chrome (module docstring)."""
        result = render_content(_TOKENS, mode="light", name="my-distro-name")
        assert "my-distro-name" not in result

    def test_ends_with_exactly_one_newline(self):
        result = render_content(_TOKENS, mode="light", name="theme")
        assert result.endswith("\n")
        assert not result.endswith("\n\n")

    def test_deterministic(self):
        assert render_content(_TOKENS, mode="light", name="theme") == render_content(_TOKENS, mode="light", name="theme")

    def test_real_tokens_json_renders_without_error(self):
        """End-to-end smoke test against the real, checked-in tokens.json."""
        from design.validate import load_tokens

        tokens = load_tokens(Path(__file__).parent.parent / "tokens.json")
        result = render_content(tokens, mode="dark", name="theme")
        assert result.endswith("\n")
        assert '@-moz-document url-prefix("about:")' in result
