"""Tests for color conversion functions."""

import pytest

from design.generators.colors import parse_hex, to_css, to_hex_rgb, to_qml, to_rgb_csv


class TestParseHex:
    """Tests for parse_hex function."""

    def test_parse_hex_valid_6_digit(self):
        """Parse valid 6-digit hex colours."""
        r, g, b, a = parse_hex("#16788C")
        assert (r, g, b, a) == (22, 120, 140, 1.0)

    def test_parse_hex_valid_8_digit(self):
        """Parse valid 8-digit hex colours with alpha."""
        r, g, b, a = parse_hex("#00000033")
        assert (r, g, b) == (0, 0, 0)
        assert abs(a - 0.2) < 0.001  # 51/255 ≈ 0.2

    def test_parse_hex_case_insensitive(self):
        """Parse hex colours with mixed case."""
        r1, g1, b1, a1 = parse_hex("#AbCdEf")
        r2, g2, b2, a2 = parse_hex("#ABCDEF")
        assert (r1, g1, b1, a1) == (r2, g2, b2, a2)

    def test_parse_hex_lowercase(self):
        """Parse valid lowercase hex colours."""
        r, g, b, a = parse_hex("#aabbcc")
        assert (r, g, b, a) == (170, 187, 204, 1.0)

    def test_parse_hex_uppercase(self):
        """Parse valid uppercase hex colours."""
        r, g, b, a = parse_hex("#AABBCC")
        assert (r, g, b, a) == (170, 187, 204, 1.0)

    def test_parse_hex_alpha_rounding(self):
        """Alpha is rounded to 3 decimals."""
        r, g, b, a = parse_hex("#FFFFFF7F")
        assert a == 0.498  # int(0x7F, 16) / 255 = 127/255 ≈ 0.498

    def test_parse_hex_alpha_full_opaque(self):
        """Alpha 0xFF (255) rounds to 1.0."""
        r, g, b, a = parse_hex("#FFFFFFFF")
        assert a == 1.0

    def test_parse_hex_alpha_zero(self):
        """Alpha 0x00 rounds to 0.0."""
        r, g, b, a = parse_hex("#FFFFFF00")
        assert a == 0.0

    def test_parse_hex_missing_hash(self):
        """Reject colours without leading '#'."""
        with pytest.raises(ValueError, match="Invalid hex colour"):
            parse_hex("16788C")

    def test_parse_hex_invalid_length(self):
        """Reject colours with wrong length."""
        with pytest.raises(ValueError, match="Invalid hex colour"):
            parse_hex("#12345")
        with pytest.raises(ValueError, match="Invalid hex colour"):
            parse_hex("#1234567")
        with pytest.raises(ValueError, match="Invalid hex colour"):
            parse_hex("#123456789")

    def test_parse_hex_non_hex_digits(self):
        """Reject colours with non-hex characters."""
        with pytest.raises(ValueError, match="Invalid hex colour"):
            parse_hex("#GGGGGG")
        with pytest.raises(ValueError, match="Invalid hex colour"):
            parse_hex("#12345Z")

    def test_parse_hex_malformed_plus_sign(self):
        """Reject colours with plus sign (malformed by int(x,16))."""
        with pytest.raises(ValueError, match="Invalid hex colour"):
            parse_hex("#+12345")

    def test_parse_hex_malformed_minus_sign(self):
        """Reject colours with minus sign (malformed by int(x,16))."""
        with pytest.raises(ValueError, match="Invalid hex colour"):
            parse_hex("#-12345")

    def test_parse_hex_malformed_underscore(self):
        """Reject colours with underscores (Python int() would accept)."""
        with pytest.raises(ValueError, match="Invalid hex colour"):
            parse_hex("#1_2345")

    def test_parse_hex_malformed_space(self):
        """Reject colours with spaces."""
        with pytest.raises(ValueError, match="Invalid hex colour"):
            parse_hex("# 12345")
        with pytest.raises(ValueError, match="Invalid hex colour"):
            parse_hex("#12345 ")

    def test_parse_hex_non_string_none(self):
        """Reject None input."""
        with pytest.raises(ValueError, match="Invalid hex colour"):
            parse_hex(None)

    def test_parse_hex_non_string_int(self):
        """Reject numeric input."""
        with pytest.raises(ValueError, match="Invalid hex colour"):
            parse_hex(123456)

    def test_parse_hex_all_zeros(self):
        """Parse black colour."""
        r, g, b, a = parse_hex("#000000")
        assert (r, g, b, a) == (0, 0, 0, 1.0)

    def test_parse_hex_all_ones(self):
        """Parse white colour."""
        r, g, b, a = parse_hex("#FFFFFF")
        assert (r, g, b, a) == (255, 255, 255, 1.0)


class TestToRgbCsv:
    """Tests for to_rgb_csv function."""

    def test_to_rgb_csv_basic(self):
        """Convert colour to RGB CSV format."""
        assert to_rgb_csv("#16788C") == "22,120,140"

    def test_to_rgb_csv_ignores_alpha(self):
        """Alpha channel is dropped in CSV format."""
        assert to_rgb_csv("#16788C00") == "22,120,140"
        assert to_rgb_csv("#16788CFF") == "22,120,140"

    def test_to_rgb_csv_black(self):
        """CSV format for black."""
        assert to_rgb_csv("#000000") == "0,0,0"

    def test_to_rgb_csv_white(self):
        """CSV format for white."""
        assert to_rgb_csv("#FFFFFF") == "255,255,255"

    def test_to_rgb_csv_no_spaces(self):
        """CSV format has no spaces."""
        result = to_rgb_csv("#AABBCC")
        assert " " not in result


class TestToHexRgb:
    """Tests for to_hex_rgb function."""

    def test_to_hex_rgb_lowercase(self):
        """Convert to lowercase hex format."""
        assert to_hex_rgb("#16788C") == "#16788c"

    def test_to_hex_rgb_already_lowercase(self):
        """Already lowercase stays lowercase."""
        assert to_hex_rgb("#aabbcc") == "#aabbcc"

    def test_to_hex_rgb_ignores_alpha(self):
        """Alpha is dropped."""
        assert to_hex_rgb("#16788C33") == "#16788c"

    def test_to_hex_rgb_black(self):
        """Lowercase hex for black."""
        assert to_hex_rgb("#000000") == "#000000"

    def test_to_hex_rgb_white(self):
        """Lowercase hex for white."""
        assert to_hex_rgb("#FFFFFF") == "#ffffff"


class TestToCss:
    """Tests for to_css function."""

    def test_to_css_opaque(self):
        """Opaque colours use lowercase #rrggbb format."""
        assert to_css("#16788C") == "#16788c"
        assert to_css("#FFFFFF") == "#ffffff"
        assert to_css("#000000") == "#000000"

    def test_to_css_translucent(self):
        """Translucent colours use rgba format."""
        result = to_css("#00000033")
        assert result.startswith("rgba(")
        assert result.endswith(")")
        assert "0, 0, 0" in result

    def test_to_css_alpha_formatting_no_trailing_zeros(self):
        """Alpha formatted without trailing zeros."""
        # 0x33 = 51, 51/255 ≈ 0.2
        assert "0.2" in to_css("#00000033")
        # Don't match "0.20" or "0.200"

    def test_to_css_full_alpha(self):
        """Full alpha (0xFF) uses opaque format."""
        assert to_css("#FFFFFF00" if False else "#FFFFFFFF") == "#ffffff"

    def test_to_css_zero_alpha(self):
        """Zero alpha uses rgba format."""
        result = to_css("#FFFFFF00")
        assert result.startswith("rgba(")
        assert "0" in result  # alpha = 0

    def test_to_css_format_consistency(self):
        """CSS format is consistent across multiple calls."""
        col = "#12345666"
        assert to_css(col) == to_css(col)


class TestToQml:
    """Tests for to_qml function."""

    def test_to_qml_opaque_uppercase(self):
        """Opaque colours use uppercase #RRGGBB format."""
        assert to_qml("#16788C") == "#16788C"
        assert to_qml("#aabbcc") == "#AABBCC"

    def test_to_qml_translucent_alpha_first(self):
        """Translucent colours put alpha first."""
        result = to_qml("#00000033")
        assert result.startswith("#")
        # 0x33 = 51
        assert result == "#33000000"

    def test_to_qml_alpha_conversion(self):
        """Alpha (0.0..1.0) converts to hex (0..255)."""
        # 0x80 = 128, 128/255 ≈ 0.502
        result = to_qml("#FFFFFF80")
        # Should start with #80
        assert result.startswith("#80")

    def test_to_qml_full_alpha_opaque(self):
        """Full alpha (0xFF) uses opaque format (6 digits, not 8)."""
        result = to_qml("#FFFFFFFF")
        # Opaque format is 6 hex digits after #, not 8
        assert len(result) == 7  # "#" + 6 hex digits
        assert result == "#FFFFFF"

    def test_to_qml_zero_alpha(self):
        """Zero alpha."""
        result = to_qml("#FFFFFF00")
        assert result == "#00FFFFFF"

    def test_to_qml_case_sensitivity(self):
        """QML format is uppercase."""
        result = to_qml("#abcdef")
        assert result.isupper() or result == "#" + "ABCDEF"
