"""WCAG 2.x contrast ratio tests for design tokens.

Guards the palette against becoming unreadable. Tests real token pairs
and ensures contrast ratios meet WCAG AA (4.5:1) and UI component (3.0:1)
thresholds without requiring code changes when colours are edited.
"""

import copy
import json
from pathlib import Path

import pytest


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """
    Convert "#RRGGBB" or "#RRGGBBAA" to (R, G, B) tuple.

    Args:
        hex_color: Hex colour string, case-insensitive.

    Returns:
        Tuple of (red, green, blue) values in range 0-255.

    Raises:
        ValueError: If hex_color is not valid format.
    """
    hex_color = hex_color.lstrip("#").upper()
    if len(hex_color) not in (6, 8):
        raise ValueError(f"Invalid hex colour: {hex_color}")
    if not all(c in "0123456789ABCDEF" for c in hex_color):
        raise ValueError(f"Invalid hex colour: {hex_color}")

    # Extract RGB; ignore alpha if present
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)
    return (r, g, b)


def _relative_luminance(hex_color: str) -> float:
    """
    Calculate sRGB relative luminance per WCAG 2.x definition.

    WHY: Linearised sRGB with gamma correction best matches human
    perception of brightness contrast.

    Args:
        hex_color: Hex colour string "#RRGGBB" or "#RRGGBBAA".

    Returns:
        Relative luminance in range [0, 1].
    """
    r, g, b = _hex_to_rgb(hex_color)

    # Normalise to 0-1 range
    r_norm = r / 255.0
    g_norm = g / 255.0
    b_norm = b / 255.0

    # Linearise each channel: apply inverse gamma correction
    # WHY: sRGB uses different curves for dark and bright regions
    def linearise(c: float) -> float:
        if c <= 0.03928:
            return c / 12.92
        return ((c + 0.055) / 1.055) ** 2.4

    r_lin = linearise(r_norm)
    g_lin = linearise(g_norm)
    b_lin = linearise(b_norm)

    # Weighted sum: human eye is more sensitive to green
    luminance = 0.2126 * r_lin + 0.7152 * g_lin + 0.0722 * b_lin
    return luminance


def contrast_ratio(fg_hex: str, bg_hex: str) -> float:
    """
    Calculate contrast ratio (L1 + 0.05) / (L2 + 0.05) where L1 is lighter.

    Args:
        fg_hex: Foreground colour as hex string.
        bg_hex: Background colour as hex string.

    Returns:
        Contrast ratio, always >= 1.0.
    """
    l_fg = _relative_luminance(fg_hex)
    l_bg = _relative_luminance(bg_hex)

    # Ensure L1 is the lighter one
    l1 = max(l_fg, l_bg)
    l2 = min(l_fg, l_bg)

    return (l1 + 0.05) / (l2 + 0.05)


@pytest.fixture
def tokens_real():
    """Load the real tokens.json file."""
    tokens_path = Path(__file__).parent.parent / "tokens.json"
    with tokens_path.open() as f:
        return json.load(f)


# Module-level constants for parametrize (must be defined before class)
_TEXT_COLOURS = ["text", "text_secondary", "link", "link_visited", "error", "warning", "success"]
_BACKGROUNDS = ["window", "surface", "surface_alt"]
_SPECIAL_PAIRS = [
    ("accent_text", "accent", 4.5),
    ("tooltip_text", "tooltip_bg", 4.5),
]
_UI_COMPONENT_PAIRS = [
    ("accent", "window", 3.0),
    ("accent", "surface", 3.0),
]


class TestContrastRatioFunction:
    """Sanity tests for the contrast ratio calculation itself."""

    def test_ratio_black_on_white(self):
        """Black (#000000) on white (#FFFFFF) = 21.0:1 exactly."""
        ratio = contrast_ratio("#FFFFFF", "#000000")
        # L(white) = 1.0, L(black) = 0.0
        # (1.0 + 0.05) / (0.0 + 0.05) = 1.05 / 0.05 = 21.0
        assert ratio == 21.0

    def test_ratio_identical_colours(self):
        """Two identical colours = 1.0:1."""
        ratio = contrast_ratio("#808080", "#808080")
        assert ratio == 1.0

    def test_ratio_mid_grey_pair(self):
        """Mid-grey pair with hand-computed expected value.

        WHY: #CCCCCC (light grey) on #333333 (dark grey) should yield
        a known ratio within 0.01 to verify the algorithm.
        """
        # #CCCCCC: R=204, G=204, B=204 → norm 0.8 → lin ≈ 0.6045
        # → L ≈ 0.6045
        # #333333: R=51, G=51, B=51 → norm 0.2 → lin ≈ 0.0331
        # → L ≈ 0.0331
        # ratio = (0.6045 + 0.05) / (0.0331 + 0.05) ≈ 0.6545 / 0.0831 ≈ 7.87
        ratio = contrast_ratio("#CCCCCC", "#333333")
        assert 7.80 < ratio < 7.95, f"Expected ~7.87, got {ratio}"


class TestContrastRealPalette:
    """Tests for real token pairs from light and dark modes."""

    @pytest.mark.parametrize("mode,text_colour,bg_colour", [
        (mode, text, bg)
        for mode in ["light", "dark"]
        for text in _TEXT_COLOURS
        for bg in _BACKGROUNDS
    ], ids=lambda x: f"{x[0]}-{x[1]}-on-{x[2]}")
    def test_text_on_background_contrast(self, tokens_real, mode, text_colour, bg_colour):
        """Text-like colours must have >= 4.5:1 contrast on backgrounds (WCAG AA)."""
        palette = tokens_real["color"][mode]
        fg = palette[text_colour]
        bg = palette[bg_colour]

        ratio = contrast_ratio(fg, bg)
        assert ratio >= 4.5, f"{mode} {text_colour} on {bg_colour}: {ratio:.2f}:1 < 4.5:1"

    @pytest.mark.parametrize("text_colour,bg_colour,min_ratio", _SPECIAL_PAIRS)
    def test_special_pairs_light(self, tokens_real, text_colour, bg_colour, min_ratio):
        """Special text-on-background pairs must meet minimum contrast in light mode."""
        palette = tokens_real["color"]["light"]
        fg = palette[text_colour]
        bg = palette[bg_colour]

        ratio = contrast_ratio(fg, bg)
        assert ratio >= min_ratio, f"light {text_colour} on {bg_colour}: {ratio:.2f}:1 < {min_ratio}:1"

    @pytest.mark.parametrize("text_colour,bg_colour,min_ratio", _SPECIAL_PAIRS)
    def test_special_pairs_dark(self, tokens_real, text_colour, bg_colour, min_ratio):
        """Special text-on-background pairs must meet minimum contrast in dark mode."""
        palette = tokens_real["color"]["dark"]
        fg = palette[text_colour]
        bg = palette[bg_colour]

        ratio = contrast_ratio(fg, bg)
        assert ratio >= min_ratio, f"dark {text_colour} on {bg_colour}: {ratio:.2f}:1 < {min_ratio}:1"

    @pytest.mark.parametrize("ui_colour,bg_colour,min_ratio", _UI_COMPONENT_PAIRS)
    def test_ui_component_contrast_light(self, tokens_real, ui_colour, bg_colour, min_ratio):
        """UI component colours must have >= 3.0:1 contrast on backgrounds (WCAG AA)."""
        palette = tokens_real["color"]["light"]
        fg = palette[ui_colour]
        bg = palette[bg_colour]

        ratio = contrast_ratio(fg, bg)
        assert ratio >= min_ratio, f"light {ui_colour} on {bg_colour}: {ratio:.2f}:1 < {min_ratio}:1"

    @pytest.mark.parametrize("ui_colour,bg_colour,min_ratio", _UI_COMPONENT_PAIRS)
    def test_ui_component_contrast_dark(self, tokens_real, ui_colour, bg_colour, min_ratio):
        """UI component colours must have >= 3.0:1 contrast on backgrounds (WCAG AA)."""
        palette = tokens_real["color"]["dark"]
        fg = palette[ui_colour]
        bg = palette[bg_colour]

        ratio = contrast_ratio(fg, bg)
        assert ratio >= min_ratio, f"dark {ui_colour} on {bg_colour}: {ratio:.2f}:1 < {min_ratio}:1"


class TestFailingPalette:
    """Test that the checker catches an obviously bad palette."""

    def test_bad_palette_yellow_warning_light(self, tokens_real):
        """Bright yellow (#FFFF00) on white background fails 4.5:1 check."""
        # WHY: Yellow on white has terrible contrast; luminance barely differs
        bad_tokens = copy.deepcopy(tokens_real)
        bad_tokens["color"]["light"]["warning"] = "#FFFF00"

        palette = bad_tokens["color"]["light"]
        fg = palette["warning"]  # #FFFF00
        bg = palette["window"]   # #F2F4F7 (off-white)

        ratio = contrast_ratio(fg, bg)
        # Yellow (#FFFF00) has luminance ~0.9278; off-white ~0.93
        # Ratio will be very close to 1.0, definitely < 4.5
        assert ratio < 4.5, f"Expected bad palette to fail, but got {ratio:.2f}:1 >= 4.5:1"
