"""Tests for design token validation."""

import copy
import json
from pathlib import Path

import pytest

from design.validate import TokenError, load_tokens, validate


@pytest.fixture
def tokens_real():
    """Load the real tokens.json file."""
    tokens_path = Path(__file__).parent.parent / "tokens.json"
    with tokens_path.open() as f:
        return json.load(f)


class TestValidateRealTokens:
    """Tests for validation of the real tokens.json file."""

    def test_real_tokens_valid(self, tokens_real):
        """Real tokens.json passes validation."""
        errors = validate(tokens_real)
        assert errors == [], f"Real tokens should be valid, but got: {errors}"


class TestValidateMutations:
    """Parametrized tests for mutations that should fail validation."""

    @pytest.mark.parametrize("mutation,expected_error_prefix", [
        # Radius violations
        ({"path": "radius.button", "value": -5}, "radius.button"),
        ({"path": "radius.window", "value": 65}, "radius.window"),
        ({"path": "radius.panel", "value": "string"}, "radius.panel"),
        ({"path": "radius.icon", "value": ""}, "radius.icon"),
        ({"path": "radius.menu", "value": None}, "radius.menu"),

        # Material.noise and blur_radius
        ({"path": "material.noise", "value": 7}, "material.noise"),
        ({"path": "material.noise", "value": -0.1}, "material.noise"),
        ({"path": "material.blur_radius", "value": 201}, "material.blur_radius"),

        # Material.bg_opacity
        ({"path": "material.bg_opacity.menu", "value": 7}, "material.bg_opacity.menu"),
        ({"path": "material.bg_opacity.panel", "value": -0.1}, "material.bg_opacity.panel"),

        # Spacing violations
        ({"path": "spacing.grid", "value": 0}, "spacing.grid"),
        ({"path": "spacing.grid", "value": 17}, "spacing.grid"),
        ({"path": "spacing.gutter", "value": 65}, "spacing.gutter"),
        ({"path": "spacing.section", "value": 129}, "spacing.section"),

        # Type size ordering
        ({"path": "type.size.body", "value": 10}, "type.size"),  # body < caption

        # Type weight ordering and validation
        ({"path": "type.weight.medium", "value": 450}, "type.weight"),  # not multiple of 100
        ({"path": "type.weight.semibold", "value": 500}, "type.weight"),  # < medium

        # Type tracking range
        ({"path": "type.tracking.body", "value": 0.2}, "type.tracking.body"),

        # Motion duration ordering
        ({"path": "motion.duration.base", "value": 100}, "motion.duration"),  # < fast

        # Motion duration range
        ({"path": "motion.duration.slow", "value": 5001}, "motion.duration.slow"),
        ({"path": "motion.duration.instant", "value": 0}, "motion.duration.instant"),

        # Motion easing_standard malformed
        ({"path": "motion.easing_standard", "value": "cubic-bezier(0.5, 0.5, 0.5)"}, "motion.easing_standard"),
        ({"path": "motion.easing_standard", "value": "linear"}, "motion.easing_standard"),
        ({"path": "motion.easing_standard", "value": "cubic-bezier(1.5, 0, 0.5, 1)"}, "motion.easing_standard"),

        # Motion easing_spring
        ({"path": "motion.easing_spring.mass", "value": 0}, "motion.easing_spring.mass"),
        ({"path": "motion.easing_spring.stiffness", "value": -1}, "motion.easing_spring.stiffness"),

        # Panel values
        ({"path": "panel.menubar_height", "value": 15}, "panel.menubar_height"),
        ({"path": "panel.shelf_icon", "value": 256}, "panel.shelf_icon"),
        ({"path": "panel.shelf_hover_scale", "value": 2.6}, "panel.shelf_hover_scale"),

        # Color hex validation
        ({"path": "color.light.window", "value": "#GGG"}, "color.light.window"),
        ({"path": "color.dark.text", "value": "#12345"}, "color.dark.text"),
        ({"path": "color.light.accent", "value": "12345678"}, "color.light.accent"),
        ({"path": "color.light.window", "value": "#12345G"}, "color.light.window"),
    ])
    def test_mutation_produces_error(self, tokens_real, mutation, expected_error_prefix):
        """Apply a mutation and check that it produces an error."""
        mutated = copy.deepcopy(tokens_real)

        # Navigate to the path and set the value
        parts = mutation["path"].split(".")
        obj = mutated
        for part in parts[:-1]:
            obj = obj[part]
        obj[parts[-1]] = mutation["value"]

        errors = validate(mutated)

        # Check that at least one error starts with the expected prefix
        matching_errors = [e for e in errors if e.startswith(expected_error_prefix)]
        assert matching_errors, (
            f"Expected error starting with {expected_error_prefix!r}, "
            f"but got: {errors}"
        )


class TestValidateMissingKeys:
    """Tests for missing required keys."""

    def test_missing_radius_button(self, tokens_real):
        """Missing radius.button key produces error."""
        mutated = copy.deepcopy(tokens_real)
        del mutated["radius"]["button"]
        errors = validate(mutated)
        assert any(e.startswith("radius.button") for e in errors)

    def test_missing_color_light_key(self, tokens_real):
        """Missing color.light key produces error."""
        mutated = copy.deepcopy(tokens_real)
        del mutated["color"]["light"]["window"]
        errors = validate(mutated)
        assert any(e.startswith("color.light.window") for e in errors)

    def test_missing_color_dark_key(self, tokens_real):
        """Missing color.dark key produces error."""
        mutated = copy.deepcopy(tokens_real)
        del mutated["color"]["dark"]["text"]
        errors = validate(mutated)
        assert any(e.startswith("color.dark.text") for e in errors)

    def test_missing_color_section(self, tokens_real):
        """Missing color section produces error."""
        mutated = copy.deepcopy(tokens_real)
        del mutated["color"]
        errors = validate(mutated)
        assert any(e.startswith("color") for e in errors)

    def test_missing_type_section(self, tokens_real):
        """Missing type section produces error."""
        mutated = copy.deepcopy(tokens_real)
        del mutated["type"]
        errors = validate(mutated)
        assert any(e.startswith("type") for e in errors)


class TestValidateUnknownKeys:
    """Tests for unknown keys at any level."""

    def test_unknown_radius_key(self, tokens_real):
        """Unknown key in radius section produces error."""
        mutated = copy.deepcopy(tokens_real)
        mutated["radius"]["unknown_key"] = 42
        errors = validate(mutated)
        assert any(e.startswith("radius.unknown_key") for e in errors)

    def test_unknown_top_level_key(self, tokens_real):
        """Unknown top-level key produces error."""
        mutated = copy.deepcopy(tokens_real)
        mutated["unknown"] = {}
        errors = validate(mutated)
        assert any(e.startswith("unknown") for e in errors)

    def test_meta_allowed(self, tokens_real):
        """_meta top-level key is allowed."""
        mutated = copy.deepcopy(tokens_real)
        # _meta already exists in real tokens, check it doesn't cause error
        errors = validate(mutated)
        assert not any(e.startswith("_meta") for e in errors)

    def test_unknown_color_light_key(self, tokens_real):
        """Unknown key in color.light produces error."""
        mutated = copy.deepcopy(tokens_real)
        mutated["color"]["light"]["unknown"] = "#FFFFFF"
        errors = validate(mutated)
        assert any(e.startswith("color.light.unknown") for e in errors)


class TestValidateTypeConstraints:
    """Tests for type-based constraints."""

    def test_bool_not_accepted_as_number(self, tokens_real):
        """Boolean values rejected where number expected."""
        mutated = copy.deepcopy(tokens_real)
        mutated["material"]["blur_radius"] = True
        errors = validate(mutated)
        assert any(e.startswith("material.blur_radius") for e in errors)
        matching = [e for e in errors if e.startswith("material.blur_radius")]
        assert matching
        assert "number" in matching[0].lower() or "bool" in matching[0].lower()

    def test_bool_not_accepted_as_int(self, tokens_real):
        """Boolean values rejected where int expected."""
        mutated = copy.deepcopy(tokens_real)
        mutated["radius.button"] = False
        errors = validate(mutated)
        assert any(e.startswith("radius.button") for e in errors)

    def test_string_not_accepted_as_number(self, tokens_real):
        """String values rejected where number expected."""
        mutated = copy.deepcopy(tokens_real)
        mutated["material.noise"] = "0.5"
        errors = validate(mutated)
        assert any(e.startswith("material.noise") for e in errors)

    def test_number_not_accepted_as_string(self, tokens_real):
        """Number values rejected where string expected."""
        mutated = copy.deepcopy(tokens_real)
        mutated["radius.icon"] = 42
        errors = validate(mutated)
        assert any(e.startswith("radius.icon") for e in errors)


class TestValidateHexColorFormat:
    """Tests for strict hex colour validation."""

    def test_hex_color_malformed_plus(self, tokens_real):
        """Reject colors with plus sign."""
        mutated = copy.deepcopy(tokens_real)
        mutated["color"]["light"]["window"] = "#+GGGGGG"
        errors = validate(mutated)
        assert any(e.startswith("color.light.window") for e in errors)

    def test_hex_color_malformed_minus(self, tokens_real):
        """Reject colors with minus sign."""
        mutated = copy.deepcopy(tokens_real)
        mutated["color"]["dark"]["text"] = "#-123456"
        errors = validate(mutated)
        assert any(e.startswith("color.dark.text") for e in errors)

    def test_hex_color_malformed_underscore(self, tokens_real):
        """Reject colors with underscores."""
        mutated = copy.deepcopy(tokens_real)
        mutated["color"]["light"]["accent"] = "#1_2345"
        errors = validate(mutated)
        assert any(e.startswith("color.light.accent") for e in errors)

    def test_hex_color_valid_uppercase(self, tokens_real):
        """Uppercase hex colours are valid."""
        mutated = copy.deepcopy(tokens_real)
        mutated["color"]["light"]["window"] = "#FFFFFF"
        errors = validate(mutated)
        assert not any(e.startswith("color.light.window") for e in errors)

    def test_hex_color_valid_lowercase(self, tokens_real):
        """Lowercase hex colours are valid."""
        mutated = copy.deepcopy(tokens_real)
        mutated["color"]["light"]["window"] = "#ffffff"
        errors = validate(mutated)
        assert not any(e.startswith("color.light.window") for e in errors)

    def test_hex_color_valid_mixed_case(self, tokens_real):
        """Mixed case hex colours are valid."""
        mutated = copy.deepcopy(tokens_real)
        mutated["color"]["light"]["window"] = "#FfFfFf"
        errors = validate(mutated)
        assert not any(e.startswith("color.light.window") for e in errors)

    def test_hex_color_valid_with_alpha(self, tokens_real):
        """8-digit hex colours with alpha are valid."""
        mutated = copy.deepcopy(tokens_real)
        mutated["color"]["light"]["window"] = "#FFFFFF80"
        errors = validate(mutated)
        assert not any(e.startswith("color.light.window") for e in errors)


class TestLoadTokens:
    """Tests for load_tokens function."""

    def test_load_tokens_real_file(self):
        """Load and validate real tokens.json."""
        tokens_path = Path(__file__).parent.parent / "tokens.json"
        tokens = load_tokens(tokens_path)
        assert isinstance(tokens, dict)
        assert "radius" in tokens
        assert "color" in tokens

    def test_load_tokens_missing_file(self, tmp_path):
        """Raise TokenError for missing file."""
        missing_path = tmp_path / "missing.json"
        with pytest.raises(TokenError, match="not found"):
            load_tokens(missing_path)

    def test_load_tokens_invalid_json(self, tmp_path):
        """Raise TokenError for invalid JSON."""
        bad_json = tmp_path / "bad.json"
        bad_json.write_text("{invalid json}", encoding="utf-8")
        with pytest.raises(TokenError, match="not valid JSON"):
            load_tokens(bad_json)

    def test_load_tokens_validation_error(self, tokens_real, tmp_path):
        """Raise TokenError if validation fails."""
        # Create invalid tokens file
        bad_tokens = copy.deepcopy(tokens_real)
        bad_tokens["radius"]["button"] = -5
        bad_file = tmp_path / "invalid.json"
        bad_file.write_text(json.dumps(bad_tokens), encoding="utf-8")

        with pytest.raises(TokenError, match="validation failed"):
            load_tokens(bad_file)

    def test_load_tokens_returns_dict(self, tokens_real, tmp_path):
        """Successful load returns the token dict."""
        good_file = tmp_path / "valid.json"
        good_file.write_text(json.dumps(tokens_real), encoding="utf-8")
        result = load_tokens(good_file)
        assert result == tokens_real


class TestValidateComprehensive:
    """Comprehensive validation tests."""

    def test_all_errors_reported(self, tokens_real):
        """All validation problems are reported, not just first."""
        mutated = copy.deepcopy(tokens_real)
        # Introduce multiple errors
        mutated["radius"]["button"] = -5
        mutated["spacing"]["grid"] = 0
        mutated["type"]["size"]["body"] = 5
        mutated["motion"]["duration"]["base"] = 50

        errors = validate(mutated)

        # Should have errors for all mutations
        assert len(errors) >= 4
        assert any(e.startswith("radius.button") for e in errors)
        assert any(e.startswith("spacing.grid") for e in errors)
        assert any(e.startswith("type.size") for e in errors)
        assert any(e.startswith("motion.duration") for e in errors)

    def test_no_errors_for_valid_input(self, tokens_real):
        """Valid tokens produce no errors."""
        errors = validate(tokens_real)
        assert errors == []

    def test_handles_non_dict_input(self):
        """Gracefully handle non-dict input."""
        errors = validate(None)
        assert errors
        assert any("dict" in e.lower() for e in errors)

    def test_handles_empty_dict(self):
        """Empty dict produces errors for missing sections."""
        errors = validate({})
        assert errors
        # Should complain about all missing top-level sections
        assert any("radius" in e for e in errors)
        assert any("color" in e for e in errors)


class TestStrokeTokens:
    """stroke.* are UI line widths, independent of the Frost glass material.*."""

    @pytest.mark.parametrize("path,value", [
        ("hairline", -1), ("hairline", 0.4), ("hairline", 4.5), ("hairline", "1"),
        ("hairline", True), ("focus", -2), ("focus", 0.4), ("focus", 8.5), ("focus", None),
    ])
    def test_out_of_range_or_wrong_type_is_rejected(self, tokens_real, path, value):
        """Values outside the real-world range or of the wrong type are reported."""
        mutated = copy.deepcopy(tokens_real)
        mutated["stroke"][path] = value
        assert any(e.startswith(f"stroke.{path}") for e in validate(mutated))

    @pytest.mark.parametrize("path,value", [
        ("hairline", 0.5), ("hairline", 4), ("focus", 0.5), ("focus", 8),
    ])
    def test_range_boundaries_are_accepted(self, tokens_real, path, value):
        """Both edges of each range are valid."""
        mutated = copy.deepcopy(tokens_real)
        mutated["stroke"][path] = value
        assert validate(mutated) == []

    def test_missing_and_unknown_keys_are_reported(self, tokens_real):
        """The stroke section is closed: missing and extra keys are errors."""
        mutated = copy.deepcopy(tokens_real)
        del mutated["stroke"]["focus"]
        mutated["stroke"]["bogus"] = 1
        errors = validate(mutated)
        assert any("stroke.focus" in e and "missing" in e for e in errors)
        assert any("stroke.bogus" in e for e in errors)

    def test_missing_section_is_reported(self, tokens_real):
        """Dropping the whole section fails validation."""
        mutated = copy.deepcopy(tokens_real)
        del mutated["stroke"]
        assert any(e.startswith("stroke") for e in validate(mutated))

    def test_real_values_are_independent_of_the_glass_edge(self, tokens_real):
        """Hairline and focus keep 1 and 2 px whatever the Frost edge width is."""
        assert tokens_real["stroke"] == {"hairline": 1.0, "focus": 2.0}


class TestDecorationTokens:
    """decoration.* drives the window title-bar theme; every limit is tested on both sides."""

    @pytest.mark.parametrize("key,value", [
        ("titlebar_height", 23), ("titlebar_height", 65), ("titlebar_height", "36"), ("titlebar_height", True),
        ("titlebar_height", 36.5),
        ("button_diameter", 7), ("button_diameter", 21), ("button_diameter", None), ("button_diameter", 12.5),
        ("button_spacing", -1), ("button_spacing", 25), ("button_spacing", "8"),
        ("button_inset", -1), ("button_inset", 33), ("button_inset", False),
        ("glyph_stroke", 0.4), ("glyph_stroke", 3.1), ("glyph_stroke", "1.2"), ("glyph_stroke", True),
        ("shadow_size", -1), ("shadow_size", 33), ("shadow_size", 8.5), ("shadow_size", "16"),
    ])
    def test_out_of_range_or_wrong_type_is_rejected(self, tokens_real, key, value):
        """Values just outside the limits, and values of the wrong type, are reported."""
        mutated = copy.deepcopy(tokens_real)
        mutated["decoration"][key] = value
        assert any(e.startswith(f"decoration.{key}") for e in validate(mutated))

    @pytest.mark.parametrize("key,value", [
        ("titlebar_height", 24), ("titlebar_height", 64),
        ("button_diameter", 8), ("button_diameter", 20),
        ("button_spacing", 0), ("button_spacing", 24),
        ("button_inset", 0), ("button_inset", 32),
        ("glyph_stroke", 0.5), ("glyph_stroke", 3),
        ("shadow_size", 0), ("shadow_size", 32),
    ])
    def test_range_boundaries_are_accepted(self, tokens_real, key, value):
        """Both edges of every range are valid."""
        mutated = copy.deepcopy(tokens_real)
        mutated["decoration"][key] = value
        assert validate(mutated) == []

    def test_missing_and_unknown_keys_are_reported(self, tokens_real):
        """The decoration section is closed: missing and extra keys are errors."""
        mutated = copy.deepcopy(tokens_real)
        del mutated["decoration"]["button_spacing"]
        mutated["decoration"]["bogus"] = 1
        errors = validate(mutated)
        assert any("decoration.button_spacing" in e and "missing" in e for e in errors)
        assert any("decoration.bogus" in e for e in errors)

    def test_missing_section_is_reported(self, tokens_real):
        """Dropping the whole section fails validation."""
        mutated = copy.deepcopy(tokens_real)
        del mutated["decoration"]
        assert any(e.startswith("decoration") for e in validate(mutated))

    def test_corner_radius_may_equal_but_not_exceed_the_title_bar(self, tokens_real):
        """radius.window == titlebar_height passes; one more pixel of radius fails."""
        mutated = copy.deepcopy(tokens_real)
        mutated["decoration"]["titlebar_height"] = 24
        mutated["radius"]["window"] = 24
        assert validate(mutated) == []
        mutated["radius"]["window"] = 25
        assert any(e.startswith("radius.window") for e in validate(mutated))

    def test_cross_check_does_not_crash_on_malformed_values(self, tokens_real):
        """A non-numeric bar height yields only the per-value error, never an exception."""
        mutated = copy.deepcopy(tokens_real)
        mutated["decoration"]["titlebar_height"] = "tall"
        errors = validate(mutated)
        assert any(e.startswith("decoration.titlebar_height") for e in errors)
        assert not any(e.startswith("radius.window") for e in errors)


class TestLightHairlineTokens:
    """Tests for the Frost light-surface rim tokens under material.edge_highlight."""

    @staticmethod
    def _errors_with(tokens_real, key, value):
        """
        Validate a copy of the real tokens with one edge_highlight key replaced.

        Args:
            tokens_real: The real token dictionary (fixture).
            key: Key inside material.edge_highlight.
            value: Replacement value.

        Returns:
            The list of validation errors.
        """
        mutated = copy.deepcopy(tokens_real)
        mutated["material"]["edge_highlight"][key] = value
        return validate(mutated)

    @pytest.mark.parametrize("key,value", [
        ("light_hairline_opacity", 0),
        ("light_hairline_opacity", 1),
        ("light_hairline_width", 0.5),
        ("light_hairline_width", 4),
        ("light_luma_low", 0),
        ("light_luma_high", 1),
    ])
    def test_values_on_the_limit_pass(self, tokens_real, key, value):
        """Each limit value itself is accepted."""
        assert self._errors_with(tokens_real, key, value) == []

    @pytest.mark.parametrize("key,value", [
        ("light_hairline_opacity", -0.01),
        ("light_hairline_opacity", 1.01),
        ("light_hairline_width", 0.49),
        ("light_hairline_width", 4.01),
        ("light_luma_low", -0.01),
        ("light_luma_high", 1.01),
        ("light_hairline_opacity", True),
        ("light_hairline_width", "1.0"),
    ])
    def test_values_beyond_the_limit_fail(self, tokens_real, key, value):
        """Values just outside each limit (and wrong types) are reported by path."""
        errors = self._errors_with(tokens_real, key, value)
        assert any(e.startswith(f"material.edge_highlight.{key}") for e in errors)

    def test_luma_ramp_must_be_strictly_ascending(self, tokens_real):
        """low < high passes; low == high and low > high fail."""
        mutated = copy.deepcopy(tokens_real)
        edge = mutated["material"]["edge_highlight"]
        edge["light_luma_low"], edge["light_luma_high"] = 0.84, 0.85
        assert validate(mutated) == []
        edge["light_luma_low"] = 0.85
        assert any("light_luma_low" in e for e in validate(mutated))
        edge["light_luma_low"] = 0.9
        assert any("light_luma_low" in e for e in validate(mutated))

    def test_missing_key_is_reported(self, tokens_real):
        """Dropping one of the new keys fails validation."""
        mutated = copy.deepcopy(tokens_real)
        del mutated["material"]["edge_highlight"]["light_luma_high"]
        errors = validate(mutated)
        assert any("light_luma_high" in e and "missing" in e for e in errors)

    def test_ramp_check_does_not_crash_on_malformed_values(self, tokens_real):
        """A non-numeric ramp bound yields only the per-value error, never an exception."""
        errors = self._errors_with(tokens_real, "light_luma_low", "dark")
        assert any(e.startswith("material.edge_highlight.light_luma_low") for e in errors)
        assert not any("must be <" in e for e in errors)
