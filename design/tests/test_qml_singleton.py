"""Tests for QML singleton generator."""

from pathlib import Path

import pytest

from design.generators.qml_singleton import render


class TestQmlSingletonRender:
    """Tests for render function in qml_singleton module."""

    def test_render_bad_mode_raises_valueerror(self):
        """Bad mode should raise ValueError."""
        tokens = {"color": {"light": {}, "dark": {}}}
        with pytest.raises(ValueError, match="light.*dark"):
            render(tokens, mode="invalid")

    def test_render_light_mode_full_output_golden(self):
        """Test full output of QML singleton for light mode with all token types."""
        # Synthetic tokens with all types and all 20 color keys
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
            "material": {
                "blur_radius": 36,
                "noise": 0.02,
                "bg_opacity": {"panel": 0.62, "menu": 0.70, "sidebar": 0.55, "modal": 0.78},
                "edge_highlight": {"opacity": 0.28, "width": 1.0},
                "inner_shadow": {"opacity": 0.10, "blur": 3},
                "refraction": {"strength": 0.035, "edge_falloff": 12},
            },
            "spacing": {"grid": 4, "gutter": 12, "section": 20},
            "type": {
                "family_ui": "Inter",
                "family_mono": "JetBrains Mono",
                "size": {"caption": 11, "body": 13, "title": 15, "header": 22},
                "weight": {"regular": 400, "medium": 500, "semibold": 600},
                "tracking": {"body": -0.01, "header": -0.02},
            },
            "motion": {
                "duration": {"instant": 100, "fast": 180, "base": 260, "slow": 400},
                "easing_standard": "cubic-bezier(0.32, 0.72, 0, 1)",
                "easing_spring": {"mass": 1, "stiffness": 340, "damping": 32},
            },
            "panel": {"menubar_height": 26, "shelf_icon": 52, "shelf_margin": 8, "shelf_hover_scale": 1.35},
        }

        result = render(tokens, mode="light", name="TestTheme")

        # Verify header
        assert "pragma Singleton" in result
        assert "import QtQuick" in result
        assert "// TestTheme light - generated from design tokens, do not edit." in result
        assert "QtObject {" in result
        assert "}" in result

        # Verify "mode" property is present (without angle brackets around type)
        assert 'readonly property string mode: "light"' in result

        # Verify color properties (camelCased: accent -> colorAccent, without angle brackets)
        assert "readonly property color colorAccent:" in result
        assert "readonly property color colorTextSecondary:" in result
        assert "readonly property color colorTooltipBg:" in result

        # Verify non-color properties are present (without angle brackets around type)
        # int properties
        assert "readonly property int radiusWindow:" in result
        assert "readonly property int radiusButton:" in result
        assert "readonly property int spacingGrid:" in result
        # float properties (including 1.0, using "real" type)
        assert "readonly property real materialEdgeHighlightWidth:" in result
        # str properties
        assert "readonly property string typeFamilyUi:" in result
        assert "readonly property string radiusIcon:" in result

        # Verify motion.easing_standard as special property with array
        assert "readonly property var motionEasingStandardCurve:" in result
        assert "[0.32, 0.72, 0, 1, 1, 1]" in result

        # Verify indentation (4 spaces)
        lines = result.split("\n")
        for line in lines:
            if line.startswith("    readonly"):
                assert line.startswith("    "), f"Property must be indented by exactly 4 spaces: {line}"

        # Verify ends with exactly one newline
        assert result.endswith("\n")
        assert not result.endswith("\n\n")

    def test_render_dark_mode_full_output_golden(self):
        """Test full output of QML singleton for dark mode."""
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
            "material": {
                "blur_radius": 36,
                "noise": 0.02,
                "bg_opacity": {"panel": 0.62, "menu": 0.70, "sidebar": 0.55, "modal": 0.78},
                "edge_highlight": {"opacity": 0.28, "width": 1.0},
                "inner_shadow": {"opacity": 0.10, "blur": 3},
                "refraction": {"strength": 0.035, "edge_falloff": 12},
            },
            "spacing": {"grid": 4, "gutter": 12, "section": 20},
            "type": {
                "family_ui": "Inter",
                "family_mono": "JetBrains Mono",
                "size": {"caption": 11, "body": 13, "title": 15, "header": 22},
                "weight": {"regular": 400, "medium": 500, "semibold": 600},
                "tracking": {"body": -0.01, "header": -0.02},
            },
            "motion": {
                "duration": {"instant": 100, "fast": 180, "base": 260, "slow": 400},
                "easing_standard": "cubic-bezier(0.32, 0.72, 0, 1)",
                "easing_spring": {"mass": 1, "stiffness": 340, "damping": 32},
            },
            "panel": {"menubar_height": 26, "shelf_icon": 52, "shelf_margin": 8, "shelf_hover_scale": 1.35},
        }

        result = render(tokens, mode="dark", name="TestTheme")

        # Verify dark mode in header
        assert "// TestTheme dark - generated from design tokens, do not edit." in result
        # Verify dark mode in mode property (without angle brackets)
        assert 'readonly property string mode: "dark"' in result

        # Verify ends with exactly one newline
        assert result.endswith("\n")
        assert not result.endswith("\n\n")

    def test_render_camelcase_conversion(self):
        """Test that property names are correctly converted to camelCase."""
        tokens = {
            "color": {"light": {}, "dark": {}},
            "radius": {"window": 14, "panel": 12, "menu": 10, "card": 12, "button": 8, "field": 8, "tooltip": 8, "icon": "squircle"},
            "material": {
                "blur_radius": 36,
                "noise": 0.02,
                "bg_opacity": {"panel": 0.62, "menu": 0.70, "sidebar": 0.55, "modal": 0.78},
                "edge_highlight": {"opacity": 0.28, "width": 1.0},
                "inner_shadow": {"opacity": 0.10, "blur": 3},
                "refraction": {"strength": 0.035, "edge_falloff": 12},
            },
            "spacing": {"grid": 4, "gutter": 12, "section": 20},
            "type": {
                "family_ui": "Inter",
                "family_mono": "JetBrains Mono",
                "size": {"caption": 11, "body": 13, "title": 15, "header": 22},
                "weight": {"regular": 400, "medium": 500, "semibold": 600},
                "tracking": {"body": -0.01, "header": -0.02},
            },
            "motion": {
                "duration": {"instant": 100, "fast": 180, "base": 260, "slow": 400},
                "easing_standard": "cubic-bezier(0.32, 0.72, 0, 1)",
                "easing_spring": {"mass": 1, "stiffness": 340, "damping": 32},
            },
            "panel": {"menubar_height": 26, "shelf_icon": 52, "shelf_margin": 8, "shelf_hover_scale": 1.35},
        }

        result = render(tokens, mode="light", name="Theme")

        # Verify camelCase conversions
        # material.bg_opacity.panel -> materialBgOpacityPanel
        assert "materialBgOpacityPanel" in result
        # material.blur_radius -> materialBlurRadius
        assert "materialBlurRadius" in result
        # panel.shelf_icon -> panelShelfIcon
        assert "panelShelfIcon" in result
        # motion.easing_spring -> motionEasingSpring (and easing_standard is special)
        assert "motionEasingSpringMass" in result

    def test_render_real_tokens_deterministic(self):
        """Test with real tokens.json: output is deterministic and sorted."""
        from design.validate import load_tokens

        tokens_path = Path(__file__).parent.parent / "tokens.json"
        tokens = load_tokens(tokens_path)

        # Render twice to verify determinism
        result1 = render(tokens, mode="light", name="Theme")
        result2 = render(tokens, mode="light", name="Theme")

        assert result1 == result2, "Output must be deterministic"

        # Verify ends with exactly one newline
        assert result1.endswith("\n")
        assert not result1.endswith("\n\n")

        # Verify properties are sorted by extracting property names
        lines = result1.split("\n")
        property_names = []
        for line in lines:
            if "readonly property" in line and line.strip().startswith("readonly"):
                # Extract property name (e.g., "colorAccent" from "readonly property color colorAccent:")
                parts = line.split()
                if len(parts) >= 4:
                    prop_name = parts[3].split(":")[0]
                    property_names.append(prop_name)

        # Verify they are sorted
        assert property_names == sorted(property_names), f"Properties must be sorted: {property_names}"

    def test_render_changing_token_changes_output(self):
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

    def test_render_string_with_backslash_and_quote(self):
        """Test that string properties with backslash and double quote are properly escaped."""
        tokens = {
            "color": {"light": {}, "dark": {}},
            "radius": {"window": 14, "panel": 12, "menu": 10, "card": 12, "button": 8, "field": 8, "tooltip": 8, "icon": 'test\\path"'},
            "material": {
                "blur_radius": 36,
                "noise": 0.02,
                "bg_opacity": {"panel": 0.62, "menu": 0.70, "sidebar": 0.55, "modal": 0.78},
                "edge_highlight": {"opacity": 0.28, "width": 1.0},
                "inner_shadow": {"opacity": 0.10, "blur": 3},
                "refraction": {"strength": 0.035, "edge_falloff": 12},
            },
            "spacing": {"grid": 4, "gutter": 12, "section": 20},
            "type": {
                "family_ui": "Inter",
                "family_mono": "JetBrains Mono",
                "size": {"caption": 11, "body": 13, "title": 15, "header": 22},
                "weight": {"regular": 400, "medium": 500, "semibold": 600},
                "tracking": {"body": -0.01, "header": -0.02},
            },
            "motion": {
                "duration": {"instant": 100, "fast": 180, "base": 260, "slow": 400},
                "easing_standard": "cubic-bezier(0.32, 0.72, 0, 1)",
                "easing_spring": {"mass": 1, "stiffness": 340, "damping": 32},
            },
            "panel": {"menubar_height": 26, "shelf_icon": 52, "shelf_margin": 8, "shelf_hover_scale": 1.35},
        }

        result = render(tokens, mode="light", name="Theme")

        # The backslash and quote in the icon string should be escaped
        assert "radiusIcon:" in result
        # Verify it contains an escaped string (either \" or \\)
        assert "readonly property string radiusIcon:" in result

    def test_render_easing_curve_with_negative_and_large_numbers(self):
        """Test easing curve with negative and >1 numbers (for spring easing)."""
        # Using a cubic-bezier with negative second parameter and >1 fourth parameter
        tokens = {
            "color": {"light": {}, "dark": {}},
            "radius": {"window": 14, "panel": 12, "menu": 10, "card": 12, "button": 8, "field": 8, "tooltip": 8, "icon": "test"},
            "material": {
                "blur_radius": 36,
                "noise": 0.02,
                "bg_opacity": {"panel": 0.62, "menu": 0.70, "sidebar": 0.55, "modal": 0.78},
                "edge_highlight": {"opacity": 0.28, "width": 1.0},
                "inner_shadow": {"opacity": 0.10, "blur": 3},
                "refraction": {"strength": 0.035, "edge_falloff": 12},
            },
            "spacing": {"grid": 4, "gutter": 12, "section": 20},
            "type": {
                "family_ui": "Inter",
                "family_mono": "JetBrains Mono",
                "size": {"caption": 11, "body": 13, "title": 15, "header": 22},
                "weight": {"regular": 400, "medium": 500, "semibold": 600},
                "tracking": {"body": -0.01, "header": -0.02},
            },
            "motion": {
                "duration": {"instant": 100, "fast": 180, "base": 260, "slow": 400},
                # Easing curve with negative second parameter and >1 fourth parameter
                "easing_standard": "cubic-bezier(0.3, -0.2, 0.5, 1.2)",
                "easing_spring": {"mass": 1, "stiffness": 340, "damping": 32},
            },
            "panel": {"menubar_height": 26, "shelf_icon": 52, "shelf_margin": 8, "shelf_hover_scale": 1.35},
        }

        result = render(tokens, mode="light", name="Theme")

        # Verify the easing curve array includes the numbers exactly as written
        # (including -0.2 and 1.2, plus the appended 1, 1)
        assert "[0.3, -0.2, 0.5, 1.2, 1, 1]" in result
