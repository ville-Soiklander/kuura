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
