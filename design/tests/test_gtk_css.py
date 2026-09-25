"""Tests for GTK CSS generator."""

from pathlib import Path

import pytest

from design.generators.gtk_css import render


class TestGtkCssRender:
    """Tests for render function in gtk_css module."""

    def test_render_bad_mode_raises_valueerror(self):
        """Bad mode should raise ValueError."""
        tokens = {"color": {"light": {}, "dark": {}}}
        with pytest.raises(ValueError, match="light.*dark"):
            render(tokens, mode="invalid")

    def test_render_light_mode_full_output_golden(self):
        """Test full output of GTK CSS for light mode with synthetic tokens."""
        # Synthetic tokens containing every colour key and all required non-colour keys
        tokens = {
            "color": {
                "light": {
                    "window": "#010203",
                    "surface": "#010203",
                    "surface_alt": "#010203",
                    "text": "#010203",
                    "text_secondary": "#010203",
                    "text_disabled": "#010203",
                    "accent": "#010203",
                    "accent_text": "#010203",
                    "separator": "#010203",
                    "link": "#010203",
                    "link_visited": "#010203",
                    "error": "#010203",
                    "warning": "#010203",
                    "success": "#010203",
                    "tooltip_bg": "#010203",
                    "tooltip_text": "#010203",
                    "shadow": "#00000033",
                    "button_close": "#010203",
                    "button_minimize": "#010203",
                    "button_maximize": "#010203",
                },
                "dark": {
                    "window": "#040506",
                    "surface": "#040506",
                    "surface_alt": "#040506",
                    "text": "#040506",
                    "text_secondary": "#040506",
                    "text_disabled": "#040506",
                    "accent": "#040506",
                    "accent_text": "#040506",
                    "separator": "#040506",
                    "link": "#040506",
                    "link_visited": "#040506",
                    "error": "#040506",
                    "warning": "#040506",
                    "success": "#040506",
                    "tooltip_bg": "#040506",
                    "tooltip_text": "#040506",
                    "shadow": "#00000066",
                    "button_close": "#040506",
                    "button_minimize": "#040506",
                    "button_maximize": "#040506",
                },
            },
            "radius": {"window": 14, "panel": 12, "menu": 10, "card": 12, "button": 8, "field": 8, "tooltip": 8, "icon": "squircle"},
            "type": {"family_ui": "TestFont", "size": {"body": 13}, "weight": {"regular": 400}},
            "motion": {"duration": {"fast": 180}, "easing_standard": "cubic-bezier(0.32, 0.72, 0, 1)"},
            "spacing": {"grid": 4},
        }

        result = render(tokens, mode="light", name="TestTheme")

        # Verify header
        assert "/* TestTheme light - generated from design tokens, do not edit. */" in result

        # Verify all 20 color keys are present, in alphabetical order
        expected_keys = sorted([
            "accent", "accent_text", "button_close", "button_maximize", "button_minimize",
            "error", "link", "link_visited", "separator", "shadow", "success", "surface",
            "surface_alt", "text", "text_disabled", "text_secondary", "tooltip_bg",
            "tooltip_text", "warning", "window",
        ])
        for key in expected_keys:
            assert f"@define-color token_{key}" in result, f"Missing color key: {key}"

        # Verify font and size settings
        assert 'font-family: "TestFont"' in result
        assert "font-size: 13px" in result
        assert "font-weight: 400" in result

        # Verify border-radius values
        assert "window, .csd" in result
        assert "border-radius: 14px" in result
        assert "button {" in result
        assert "border-radius: 8px" in result
        assert "entry, spinbutton" in result
        assert "border-radius: 8px" in result
        assert "tooltip {" in result
        assert "border-radius: 8px" in result
        assert "popover > contents, menu {" in result
        assert "border-radius: 10px" in result
        assert ".card {" in result
        assert "border-radius: 12px" in result

        # Verify motion values
        assert "transition: all 180ms cubic-bezier(0.32, 0.72, 0, 1)" in result

        # Verify padding (spacing.grid=4, so grid*3=12)
        assert "padding: 4px 12px" in result

        # Verify ends with exactly one newline
        assert result.endswith("\n")
        assert not result.endswith("\n\n")

    def test_render_dark_mode_full_output_golden(self):
        """Test full output of GTK CSS for dark mode with synthetic tokens."""
        tokens = {
            "color": {
                "light": {
                    "window": "#010203",
                    "surface": "#010203",
                    "surface_alt": "#010203",
                    "text": "#010203",
                    "text_secondary": "#010203",
                    "text_disabled": "#010203",
                    "accent": "#010203",
                    "accent_text": "#010203",
                    "separator": "#010203",
                    "link": "#010203",
                    "link_visited": "#010203",
                    "error": "#010203",
                    "warning": "#010203",
                    "success": "#010203",
                    "tooltip_bg": "#010203",
                    "tooltip_text": "#010203",
                    "shadow": "#00000033",
                    "button_close": "#010203",
                    "button_minimize": "#010203",
                    "button_maximize": "#010203",
                },
                "dark": {
                    "window": "#040506",
                    "surface": "#040506",
                    "surface_alt": "#040506",
                    "text": "#040506",
                    "text_secondary": "#040506",
                    "text_disabled": "#040506",
                    "accent": "#040506",
                    "accent_text": "#040506",
                    "separator": "#040506",
                    "link": "#040506",
                    "link_visited": "#040506",
                    "error": "#040506",
                    "warning": "#040506",
                    "success": "#040506",
                    "tooltip_bg": "#040506",
                    "tooltip_text": "#040506",
                    "shadow": "#00000066",
                    "button_close": "#040506",
                    "button_minimize": "#040506",
                    "button_maximize": "#040506",
                },
            },
            "radius": {"window": 14, "panel": 12, "menu": 10, "card": 12, "button": 8, "field": 8, "tooltip": 8, "icon": "squircle"},
            "type": {"family_ui": "TestFont", "size": {"body": 13}, "weight": {"regular": 400}},
            "motion": {"duration": {"fast": 180}, "easing_standard": "cubic-bezier(0.32, 0.72, 0, 1)"},
            "spacing": {"grid": 4},
        }

        result = render(tokens, mode="dark", name="TestTheme")

        # Verify header specifies dark mode
        assert "/* TestTheme dark - generated from design tokens, do not edit. */" in result

        # Verify ends with exactly one newline
        assert result.endswith("\n")
        assert not result.endswith("\n\n")

    def test_render_real_tokens_deterministic(self, tmp_path):
        """Test with real tokens.json: output is deterministic and contains all color keys."""
        from design.validate import load_tokens

        tokens_path = Path(__file__).parent.parent / "tokens.json"
        tokens = load_tokens(tokens_path)

        # Render twice to verify determinism
        result1 = render(tokens, mode="light", name="Theme")
        result2 = render(tokens, mode="light", name="Theme")

        assert result1 == result2, "Output must be deterministic"

        # Verify it contains a line for every color key
        for key in tokens["color"]["light"].keys():
            assert f"@define-color token_{key}" in result1, f"Missing color key: {key}"

        # Verify ends with exactly one newline
        assert result1.endswith("\n")
        assert not result1.endswith("\n\n")

    def test_render_changing_token_changes_output(self, tmp_path):
        """Test that changing a color token changes the output."""
        from design.validate import load_tokens
        import copy

        tokens_path = Path(__file__).parent.parent / "tokens.json"
        tokens = load_tokens(tokens_path)

        # Render original
        result_original = render(tokens, mode="light", name="Theme")

        # Mutate a deep copy and render again
        tokens_modified = copy.deepcopy(tokens)
        tokens_modified["color"]["light"]["accent"] = "#FF0000"

        result_modified = render(tokens_modified, mode="light", name="Theme")

        # Output must be different
        assert result_original != result_modified, "Changing a token must change the output"

        # Original should have the original accent color (in lowercase, as to_css converts to lowercase)
        original_accent_lowercase = tokens["color"]["light"]["accent"].lower()
        assert original_accent_lowercase in result_original.lower()
        # Modified should have the new accent color
        assert "#ff0000" in result_modified.lower()
