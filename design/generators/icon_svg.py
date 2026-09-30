"""
Generate one icon's complete SVG document: a superellipse ("squircle") frame, filled
with the icon gradient and traced with the glass-edge highlight, wrapping a caller-
supplied glyph.

This file is the LOCKED INTERFACE: implement the body of render_icon() and
_squircle_path() without changing either signature. Only the standard library may be
used. Never hard code a squircle exponent, gradient colour or glass-edge value here --
those come from design/tokens.json's `icon` section (see design/validate.py's own
_SECTIONS["icon"]/_RULES entries for the exact allowed ranges); this generator is
the one place those numbers are allowed to become SVG literals, the same rule every
other generator in this package already follows for its own section of tokens.json.

WHY this generator exists (Vaihe 5 of the working brief, "Omat assetit"): the brief
requires every icon in the set (file manager, settings, terminal, browser, file-type
icons, systray, folders -- design/icons/glyphs.py enumerates the actual set) to share
"yhtenainen ristikko" (one unified grid) -- the same squircle mask, the same gradient
direction, the same glass-edge mechanism, differing only in the glyph drawn on top.
Hand-drawing that frame once per icon risks exactly the silent drift this project's
generator pattern always exists to prevent (compare design/generators/plasma_layout.py's
own module docstring on the same point for the panel layout). This module is the ONE
place the frame geometry is computed; every icon calls it with its own glyph content.

WHY icons have no light/dark variant (unlike design/generate.py's 4 mode-dependent
generators): an icon set's own gradient/glass-edge appearance is deliberately NOT tied
to the desktop's colour-scheme toggle -- the SAME shape and fill is correct whether the
desktop is currently light or dark (matching how real icon themes, e.g. Papirus, do not
ship separate light/dark variants either). render_icon()'s signature therefore has no
`mode` parameter, the same mode-independent shape design/generators/cpp_header.py's
render(tokens) -> str and plasma_layout.py's render(tokens) -> str already use.

THE SQUIRCLE (superellipse) FORMULA -- the exact, locked geometry every icon shares:

A superellipse centred at (cx, cy) with semi-axis `a` (equal in both directions, since
every icon is square) and exponent `n` satisfies |x-cx|/a|^n + |(y-cy)/a|^n = 1 for
every point (x, y) on its boundary. The standard closed-form PARAMETRIC solution to
that equation -- exact for every real t, not an approximation -- is:

    x(t) = cx + a * sign(cos t) * |cos t|^(2/n)
    y(t) = cy + a * sign(sin t) * |sin t|^(2/n)      for t in [0, 2*pi)

_squircle_path(cx, cy, a, n, point_count) must sample this parametric form at
`point_count` values of t spaced evenly over [0, 2*pi) (t_i = 2*pi*i/point_count for
i in 0..point_count-1, i.e. t_0 = 0 is always included and t = 2*pi is not, since it
would duplicate t_0), connect the samples with straight SVG line segments, and close
the path -- "M x0,y0 L x1,y1 L x2,y2 ... Z" (coordinates formatted with %.2f, matching
every other generator's own float-formatting convention in this package). Every
coordinate MUST be produced by this exact parametric formula; do not substitute a
Bezier-arc approximation or any other rounded-corner technique, even though those look
superficially similar -- this project's DoD is "yhtenainen ristikko", which this exact,
reproducible-by-formula boundary is what makes checkable at all (a hand-tuned Bezier
approximation could not be given a single correct expected value the way this formula
can).

WORKED EXAMPLE, to test _squircle_path() against without needing to render anything
(mirrors packages/kuura-frost/tests/offscreen_shader_test.cpp's own hand-computed-pixel
pattern): for cx=cy=256, a=224, n=5 (design/tokens.json's own icon.squircle_exponent):
  - t=0:        cos=1, sin=0            -> x=256+224*1=480.00, y=256+224*0=256.00
  - t=pi/2:     cos=0, sin=1            -> x=256.00,           y=480.00
  - t=pi:       cos=-1, sin=0           -> x=256-224=32.00,    y=256.00
  - t=3*pi/2:   cos=0, sin=-1           -> x=256.00,           y=32.00
  - t=pi/4:     cos=sin=2**-0.5=0.70711 -> |0.70711|^(2/5) = 0.70711**0.4 = 0.87055
                x = y = 256 + 224*0.87055 = 451.00 (both coordinates equal by symmetry,
                since cos t == sin t at exactly this angle)
These five points must appear, in this exact order (t increasing from 0), among the
sampled points whenever point_count is a multiple of 4 (t=0, pi/2, pi and 3*pi/2 always
land exactly on a sample) -- point_count=128 (render_icon()'s own fixed choice, a
multiple of 4) guarantees all four; t=pi/4 lands exactly on a sample only when
point_count is also a multiple of 8, which 128 also satisfies.

THE ICON CANVAS -- fixed constants render_icon() uses for every icon, never
parameterised (this fixed-ness IS the "unified grid" the brief asks for):
  - CANVAS_SIZE = 512 (the SVG's own viewBox is "0 0 512 512")
  - INSET = 32 (the squircle's own bounding box is inset this many units from every
    edge of the canvas, on all four sides -- matching the common convention across
    desktop icon-grid guidelines of leaving comparable proportional breathing room
    around an icon's own silhouette; this project's own inset is chosen
    independently here, not measured from any real OS vendor's actual assets, per
    this project's anti-copying rule)
  - cx = cy = CANVAS_SIZE / 2 = 256; a = (CANVAS_SIZE - 2 * INSET) / 2 = 224
  - POINT_COUNT = 128 (the sample count _squircle_path() is always called with from
    render_icon() -- see the worked example above for why this exact value was chosen)

render_icon()'s OUTPUT (a complete, standalone SVG document -- every icon is one
self-contained file, not a shared-<defs> sprite sheet, so each can be rasterised
independently by whatever tool consumes the icon theme):
  1. `<svg viewBox="0 0 512 512" xmlns="http://www.w3.org/2000/svg">`
  2. `<defs>` containing one `<linearGradient>` (id="grad", x1=x2=256 i.e. a purely
     VERTICAL gradient -- y1=INSET at the top, y2=CANVAS_SIZE-INSET at the bottom,
     offset="0"/stop-color=icon.gradient.top then offset="1"/stop-color=
     icon.gradient.bottom, gradientUnits="userSpaceOnUse" so the y1/y2 values above are
     real canvas coordinates, not the 0..1 fractions gradientUnits="objectBoundingBox"
     would otherwise require converting to)
  3. The squircle path (`_squircle_path(256, 256, 224, tokens["icon"]["squircle_exponent"],
     128)`), filled with `fill="url(#grad)"`
  4. The SAME squircle path a second time, unfilled (`fill="none"`), stroked with
     `stroke="#FFFFFF"`, `stroke-opacity` = tokens["icon"]["glass_edge"]["opacity"],
     `stroke-width` = tokens["icon"]["glass_edge"]["width"] -- the glass-edge highlight.
     A full-perimeter stroke, not just the top arc, is this generator's own locked,
     simplest-correct mechanism; the exact visual weight (whether a full-perimeter
     highlight or a top-only fade reads better at real icon sizes) is a question for
     this project's own visual-review cycle once real icons exist to look at, the same
     way this project always finalises a perceptual/visual parameter -- by looking at a
     real render, never by guessing it correctly on the first attempt (compare
     packages/kuura-frost's own material.* tokens, tuned the same way).
  5. `glyph_content` (the caller's own already-valid SVG markup for whatever this
     specific icon depicts -- a `<g>`, `<path>`, or similar fragment, assumed to already
     be authored within the 512x512 canvas and clear of the squircle's own INSET margin;
     render_icon() does not itself clip or scale it) inserted verbatim, after the
     squircle/highlight so it draws on top of them
  6. `</svg>`

Args (render_icon):
    tokens: Validated token dictionary (design/validate.py's load_tokens()); only
        tokens["icon"] is read.
    glyph_content: Raw SVG markup for this icon's own glyph, already authored within
        the 512x512 canvas (see point 5 above). Not validated as well-formed XML by
        this function -- an invalid fragment produces an invalid SVG document, exactly
        as if it had been written directly into a hand-authored file.

Returns (render_icon):
    The complete SVG document as a single string, ending with exactly one trailing
    newline (matching every other generator's own output convention in this package).

Args (_squircle_path):
    cx, cy: Centre of the superellipse, in SVG user units.
    a: Semi-axis length (equal in both directions -- every icon is square).
    n: The superellipse exponent (design/tokens.json's icon.squircle_exponent).
    point_count: Number of points to sample around the curve (always 128 from
        render_icon(), see above; exposed as its own parameter so a caller verifying
        this function in isolation, e.g. a unit test, can request a small point_count
        and check exact coordinates without formatting 128 of them by hand).

Returns (_squircle_path):
    An SVG path `d` attribute value: "M x0,y0 L x1,y1 ... Z", coordinates formatted
    with two decimal places, in the exact sampling order the WORKED EXAMPLE above
    demonstrates (t increasing from 0).
"""

from __future__ import annotations

import math

CANVAS_SIZE = 512
INSET = 32
POINT_COUNT = 128

# Centre and semi-axis of the squircle frame every icon shares (see this module's
# own docstring, "THE ICON CANVAS"). Computed once, as ints, so both users of these
# numbers - _squircle_path()'s own cx/cy/a arguments below and the gradient's
# userSpaceOnUse coordinates - agree on exactly "256"/"224", never a drifted float
# like "256.0" from an unguarded CANVAS_SIZE / 2.
_CX = CANVAS_SIZE // 2
_CY = _CX
_A = (CANVAS_SIZE - 2 * INSET) // 2


def _squircle_path(cx: float, cy: float, a: float, n: float, point_count: int) -> str:
    """See this module's own docstring (THE SQUIRCLE FORMULA) for the exact spec."""
    points = []
    for i in range(point_count):
        # t_i = 2*pi*i/point_count: t_0 = 0 is always included, t = 2*pi is never
        # sampled (it would duplicate t_0) - exactly the spacing the module
        # docstring's WORKED EXAMPLE demands.
        t = 2 * math.pi * i / point_count
        cos_t = math.cos(t)
        sin_t = math.sin(t)

        # x(t) = cx + a*sign(cos t)*|cos t|^(2/n), y(t) analogous with sin. A
        # negative base raised to a fractional exponent is not a real number in
        # Python (it would raise or silently return complex) - factoring the sign
        # out via abs()/copysign() is what keeps every quadrant of the curve real,
        # exactly as the parametric formula in this module's own docstring states.
        x = cx + a * math.copysign(abs(cos_t) ** (2 / n), cos_t)
        y = cy + a * math.copysign(abs(sin_t) ** (2 / n), sin_t)
        points.append(f"{x:.2f},{y:.2f}")

    # "M x0,y0 L x1,y1 L x2,y2 ... Z" - a single M, every remaining sample
    # joined by " L ", then " Z" to close the path back to the first point.
    return "M " + " L ".join(points) + " Z"


def render_icon(tokens: dict, glyph_content: str) -> str:
    """See this module's own docstring (render_icon's OUTPUT) for the exact spec."""
    icon = tokens["icon"]
    squircle_d = _squircle_path(_CX, _CY, _A, icon["squircle_exponent"], POINT_COUNT)

    lines = [
        f'<svg viewBox="0 0 {CANVAS_SIZE} {CANVAS_SIZE}" xmlns="http://www.w3.org/2000/svg">',
        "<defs>",
        # Purely vertical gradient: x1 == x2 == cx, y1 = INSET (top of the
        # squircle's own bounding box), y2 = CANVAS_SIZE - INSET (bottom).
        # gradientUnits="userSpaceOnUse" so these are real canvas coordinates,
        # not the 0..1 fractions objectBoundingBox would require.
        f'<linearGradient id="grad" x1="{_CX}" y1="{INSET}" x2="{_CX}" y2="{CANVAS_SIZE - INSET}" '
        'gradientUnits="userSpaceOnUse">',
        f'<stop offset="0" stop-color="{icon["gradient"]["top"]}"/>',
        f'<stop offset="1" stop-color="{icon["gradient"]["bottom"]}"/>',
        "</linearGradient>",
        "</defs>",
        # The squircle, filled with the gradient just defined.
        f'<path d="{squircle_d}" fill="url(#grad)"/>',
        # The SAME path a second time, unfilled, stroked as the glass-edge
        # highlight - a full-perimeter stroke is this generator's own locked,
        # simplest-correct mechanism (see the module docstring for why).
        f'<path d="{squircle_d}" fill="none" stroke="#FFFFFF" '
        f'stroke-opacity="{icon["glass_edge"]["opacity"]}" stroke-width="{icon["glass_edge"]["width"]}"/>',
        # The caller's own glyph, inserted verbatim so it draws on top of the
        # frame/highlight above it.
        glyph_content,
        "</svg>",
    ]
    return "\n".join(lines) + "\n"
