"""
Tests for the icon SVG generator (design.generators.icon_svg).

The five expected coordinates below are copied by hand from icon_svg.py's own
module docstring ("WORKED EXAMPLE"), not computed with the generator itself - a
wrong exponent, a dropped sign() factor or an off-by-one sample count cannot
hide behind shared code, matching design/tests/test_cpp_header.py's and
design/tests/test_plasma_layout.py's own golden-value convention.
"""

from __future__ import annotations

import math
import re

import pytest

from design.generators.icon_svg import CANVAS_SIZE, INSET, POINT_COUNT, _squircle_path, render_icon

# icon_svg.py's own WORKED EXAMPLE: cx=cy=256, a=224, n=5. Each entry is
# (t, expected_x, expected_y), hand-computed in the module docstring.
_WORKED_EXAMPLE = [
    (0.0, 480.00, 256.00),
    (math.pi / 2, 256.00, 480.00),
    (math.pi, 32.00, 256.00),
    (3 * math.pi / 2, 256.00, 32.00),
    (math.pi / 4, 451.00, 451.00),
]

# A minimal, valid tokens["icon"] section (see design/validate.py's own rules)
# for render_icon() tests that do not care about the real tokens.json values.
_SYNTHETIC_TOKENS = {
    "icon": {
        "squircle_exponent": 5,
        "gradient": {"top": "#3FB4C9", "bottom": "#0E5A6B"},
        "glass_edge": {"opacity": 0.35, "width": 1.5},
    }
}


def _parse_points(d: str) -> list[tuple[float, float]]:
    """
    Parse an "M x0,y0 L x1,y1 ... Z" path `d` attribute into a list of floats.

    Args:
        d: A path string in the exact format icon_svg._squircle_path() returns.

    Returns:
        [(x0, y0), (x1, y1), ...] in the same order as the path.
    """
    # WHY regex over str.split: the leading "M " and trailing " Z" and the "L "
    # separators are all fixed literals in the locked format, so stripping them
    # with a single findall is simpler than manually walking tokens.
    return [(float(x), float(y)) for x, y in re.findall(r"(-?\d+\.\d\d),(-?\d+\.\d\d)", d)]


class TestSquirclePathWorkedExample:
    """_squircle_path() must reproduce the module docstring's 5 hand-computed points."""

    def test_point_count_8_contains_all_five_worked_points(self):
        """
        point_count=8 is a multiple of 8, so (per the module docstring) all four
        axis-aligned angles AND t=pi/4 land exactly on a sample - every one of the
        5 worked-example points must therefore appear, at its documented index
        (t_i = 2*pi*i/8), within a single 8-point call.
        """
        d = _squircle_path(256, 256, 224, 5, 8)
        points = _parse_points(d)
        assert len(points) == 8

        # Index -> (t, expected_x, expected_y): i=0 -> t=0, i=1 -> t=pi/4,
        # i=2 -> t=pi/2, i=4 -> t=pi, i=6 -> t=3*pi/2.
        expected_by_index = {
            0: (480.00, 256.00),
            1: (451.00, 451.00),
            2: (256.00, 480.00),
            4: (32.00, 256.00),
            6: (256.00, 32.00),
        }
        for index, (expected_x, expected_y) in expected_by_index.items():
            actual_x, actual_y = points[index]
            assert actual_x == pytest.approx(expected_x, abs=0.01), f"index {index} x"
            assert actual_y == pytest.approx(expected_y, abs=0.01), f"index {index} y"

    @pytest.mark.parametrize("t,expected_x,expected_y", _WORKED_EXAMPLE)
    def test_each_worked_point_individually(self, t, expected_x, expected_y):
        """
        Re-derive each worked point directly from the parametric formula the
        module docstring gives (not by re-implementing _squircle_path, just its
        one-point special case), independent of sample indexing/point_count.
        """
        cos_t, sin_t = math.cos(t), math.sin(t)
        x = 256 + 224 * math.copysign(abs(cos_t) ** (2 / 5), cos_t)
        y = 256 + 224 * math.copysign(abs(sin_t) ** (2 / 5), sin_t)
        assert x == pytest.approx(expected_x, abs=0.01)
        assert y == pytest.approx(expected_y, abs=0.01)

    def test_output_format_is_m_l_star_z(self):
        """The path string is exactly "M x0,y0 L x1,y1 ... Z", coordinates to 2dp."""
        d = _squircle_path(256, 256, 224, 5, 4)
        assert re.fullmatch(r"M (-?\d+\.\d\d,-?\d+\.\d\d)( L -?\d+\.\d\d,-?\d+\.\d\d)* Z", d)

    def test_point_count_controls_sample_count(self):
        """point_count samples are produced, t_0 = 0 included, t = 2*pi never duplicated."""
        for point_count in (4, 8, 16, 128):
            d = _squircle_path(256, 256, 224, 5, point_count)
            points = _parse_points(d)
            assert len(points) == point_count
            # t_0 = 0 -> (cx + a, cy) = (480, 256) for this cx/a.
            assert points[0] == pytest.approx((480.00, 256.00), abs=0.01)


class TestRenderIcon:
    """render_icon() output structure (see icon_svg.py's own docstring, OUTPUT)."""

    def test_output_is_a_complete_svg_document(self):
        """Starts with the exact viewBox/xmlns svg tag and ends with </svg>."""
        text = render_icon(_SYNTHETIC_TOKENS, "<circle cx='256' cy='256' r='10'/>")
        assert text.startswith(f'<svg viewBox="0 0 {CANVAS_SIZE} {CANVAS_SIZE}" xmlns="http://www.w3.org/2000/svg">')
        assert text.rstrip("\n").endswith("</svg>")
        assert text.endswith("\n") and not text.endswith("\n\n")

    def test_output_contains_the_gradient(self):
        """A vertical (x1==x2) userSpaceOnUse gradient using the icon.gradient tokens."""
        text = render_icon(_SYNTHETIC_TOKENS, "<circle/>")
        assert '<linearGradient id="grad"' in text
        assert 'gradientUnits="userSpaceOnUse"' in text
        assert f'y1="{INSET}"' in text
        assert f'y2="{CANVAS_SIZE - INSET}"' in text
        assert 'stop-color="#3FB4C9"' in text
        assert 'stop-color="#0E5A6B"' in text

    def test_squircle_path_appears_filled_and_stroked(self):
        """The SAME squircle `d` value appears twice: once filled, once stroked."""
        text = render_icon(_SYNTHETIC_TOKENS, "<circle/>")
        squircle_d = _squircle_path(256, 256, 224, 5, POINT_COUNT)
        assert text.count(f'd="{squircle_d}"') == 2
        assert f'd="{squircle_d}" fill="url(#grad)"' in text
        assert 'fill="none" stroke="#FFFFFF"' in text
        assert 'stroke-opacity="0.35"' in text
        assert 'stroke-width="1.5"' in text

    def test_glyph_content_inserted_verbatim(self):
        """The caller's glyph markup appears, unmodified, in the output."""
        glyph = '<g><rect x="200" y="200" width="112" height="112"/></g>'
        text = render_icon(_SYNTHETIC_TOKENS, glyph)
        assert glyph in text

    def test_glyph_drawn_after_frame_so_it_is_on_top(self):
        """The glyph content appears strictly after both squircle paths in the document."""
        glyph = "<GLYPH_MARKER/>"
        text = render_icon(_SYNTHETIC_TOKENS, glyph)
        squircle_d = _squircle_path(256, 256, 224, 5, POINT_COUNT)
        last_path_index = text.rindex(f'd="{squircle_d}"')
        assert text.index(glyph) > last_path_index

    def test_uses_squircle_exponent_from_tokens(self):
        """A different squircle_exponent changes the emitted path (no hard-coded n)."""
        tokens_n5 = _SYNTHETIC_TOKENS
        tokens_n3 = {
            "icon": {
                "squircle_exponent": 3,
                "gradient": {"top": "#3FB4C9", "bottom": "#0E5A6B"},
                "glass_edge": {"opacity": 0.35, "width": 1.5},
            }
        }
        text_n5 = render_icon(tokens_n5, "<g/>")
        text_n3 = render_icon(tokens_n3, "<g/>")
        assert text_n5 != text_n3

    def test_output_ends_with_single_trailing_newline(self):
        """Exactly one trailing newline, no CR."""
        text = render_icon(_SYNTHETIC_TOKENS, "<g/>")
        assert text.endswith("\n")
        assert not text.endswith("\n\n")
        assert "\r" not in text
