"""
Command line tool that renders design/tokens.json's own colour palette into a
small set of wallpaper images: procedurally generated abstract/gradient art,
one light and one dark rendering per composition, no external image assets,
photographs or third-party artwork of any kind (Vaihe 5 of the working
brief, "Omat assetit": "Taustakuvat: 4-6 kpl, light/dark-parit, oma
tuotanto" -- 4-6 designs, each as a light/dark pair, own production).

Mirrors design/generate.py's own CLI conventions (--tokens/--out-dir/--name,
the same path-traversal guard, `python -m design.generate_wallpapers`
invocation) but is NOT part of that file's locked interface -- it is a
separate, standalone generator that happens to share tokens.json and the
same output tree (<out-dir>/wallpapers/, alongside generate.py's own
plasma/, kvantum/, gtk/, qml/, layout/, cpp/ subdirectories under the same
--out-dir).

Usage (from the project root):
    python -m design.generate_wallpapers [--tokens FILE] [--out-dir DIR] [--name NAME]

Output: <out-dir>/wallpapers/<name>-<composition>-<mode>.png, one PNG per
(composition, mode) pair -- 5 compositions x 2 modes (light, dark) = 10
files, each WIDTH x HEIGHT = 1920x1080 (the real deployment resolution is a
later decision, not made here). Every composition reads only
tokens["color"][mode] (see design/validate.py's own docstring for the full,
authoritative list of the 20 colour keys and their meaning) -- no other
token section, and no colour literal not already present in tokens.json, is
ever used as paint.

SHARED MATH -- every composition below is built from these two primitives:

    lerp(a, b, t) = a + (b - a) * t                     (per channel, t in 0..1)
    clamp01(t)    = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)

Every output channel is `round(...)` (Python's round-half-to-even) of the
formula given, clamped into 0..255. Because every t used below is itself
clamp01'd first, and every colour pair comes straight from tokens.json's own
validated 6/8-digit hex channels (already 0..255), the clamp never actually
changes a value in practice -- it exists only as a defensive floor/ceiling,
the same belt-and-suspenders convention design/generators/colors.py's own
helpers use. Alpha (present only on 8-digit tokens) is read via
design.generators.colors.parse_hex and then always discarded: wallpapers are
fully opaque backgrounds, never composited with anything behind them.

Pixel coordinates run x in 0..WIDTH-1, y in 0..HEIGHT-1 (row 0 = the top
row, column 0 = the left column -- standard raster order, matching every
other raster/vector convention already used in this package, e.g.
design/generators/icon_svg.py's SVG canvas).

THE FIVE COMPOSITIONS (each takes exactly one pair or triple of tokens from
color.<mode>; "top"/"left" always means t=0, "bottom"/"right" always means
t=1):

1. "vertical-dawn" -- plain top-to-bottom linear gradient.
   t(x, y) = y / (HEIGHT - 1)                  (constant across every row's x)
   color(x, y) = lerp(window, accent, t(x, y))

2. "diagonal-drift" -- linear gradient along the main diagonal (top-left to
   bottom-right), the "soft diagonal gradient" the brief itself suggests.
   t(x, y) = (x + y) / ((WIDTH - 1) + (HEIGHT - 1))
   color(x, y) = lerp(surface_alt, accent, t(x, y))

3. "radial-glow" -- a single soft radial light, centred on the canvas.
   cx, cy = (WIDTH - 1) / 2, (HEIGHT - 1) / 2                (exact centre)
   radius = sqrt(cx**2 + cy**2)          (centre-to-corner distance; the same
       value for all four corners because the centre is equidistant from
       each by construction, so this is the one radius at which every
       corner reaches t=1)
   d(x, y) = sqrt((x - cx)**2 + (y - cy)**2)
   t(x, y) = clamp01(d(x, y) / radius)
   color(x, y) = lerp(accent, window, t(x, y))     (accent glows at the
       centre, fading out to the window colour by the corners)

4. "corner-glow-dual" -- two independent radial glows, one seated in the
   top-left corner and one in the bottom-right corner, added on top of a
   flat base colour. This is the one genuinely "layered" field the brief
   mentions: two radial terms superposed, not a single gradient.
   radius = sqrt((WIDTH - 1)**2 + (HEIGHT - 1)**2)     (the canvas's own
       corner-to-corner diagonal length -- the falloff radius for BOTH
       glows, chosen so each glow's weight below reaches exactly 0 at the
       opposite corner)
   d1(x, y) = sqrt(x**2 + y**2)                    (distance to (0, 0))
   d2(x, y) = sqrt((x - (WIDTH-1))**2 + (y - (HEIGHT-1))**2)   (distance to
       (WIDTH-1, HEIGHT-1))
   w1(x, y) = clamp01(1 - d1(x, y) / radius)     (1 at the top-left corner,
       0 by the bottom-right corner)
   w2(x, y) = clamp01(1 - d2(x, y) / radius)     (1 at the bottom-right
       corner, 0 by the top-left corner)
   channel_c(x, y) = window_c + w1(x, y) * (accent_c - window_c)
                              + w2(x, y) * (surface_alt_c - window_c)
   (computed independently per channel c in {r, g, b}; round+clamp is
   applied only once, to this final sum -- not to each addend separately)

5. "banded-horizon" -- a left-to-right, three-stop piecewise-linear gradient
   (a colour "band" crossed midway, unlike the plain two-stop gradients
   above), constant down every column's y.
   t(x, y) = x / (WIDTH - 1)
   if t <= 0.5: color(x, y) = lerp(surface_alt, surface, t / 0.5)
   else:        color(x, y) = lerp(surface, accent, (t - 0.5) / 0.5)

Every composition is fully deterministic given tokens.json's current colour
values: the same tokens always produce the exact same PNG pixels.

Defaults, nothing hard coded: --tokens = the tokens.json next to this file;
--out-dir = ".build/generated" relative to the project root (the parent of
this file's directory, same default as design/generate.py); --name =
environment variable DISTRO_NAME, else "theme".
"""

from __future__ import annotations

import math
import os
import re
import sys
from pathlib import Path

from PIL import Image

from design.generators.colors import parse_hex

# Generated files must stay inside the project tree (path traversal guard),
# exactly like design/generate.py's own PROJECT_ROOT.
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Render resolution for every composition (see module docstring).
WIDTH = 1920
HEIGHT = 1080

# The five composition names, also used as the file name slug. Order here is
# the order generate_wallpapers() writes and returns them in (before the
# final sort, which re-sorts by full path anyway).
COMPOSITIONS = (
    "vertical-dawn",
    "diagonal-drift",
    "radial-glow",
    "corner-glow-dual",
    "banded-horizon",
)


def _rgb(palette: dict, token: str) -> tuple[int, int, int]:
    """Return palette[token]'s RGB channels as ints 0..255, alpha discarded."""
    r, g, b, _alpha = parse_hex(palette[token])
    return (r, g, b)


def _clamp01(t: float) -> float:
    """Clamp t into 0.0..1.0 (see module docstring, SHARED MATH)."""
    if t < 0.0:
        return 0.0
    if t > 1.0:
        return 1.0
    return t


def _clamp_byte(value: float) -> int:
    """round(value) (round-half-to-even) clamped into 0..255."""
    v = round(value)
    if v < 0:
        return 0
    if v > 255:
        return 255
    return v


def _lerp_channel(a: int, b: int, t: float) -> int:
    """lerp(a, b, t) (see module docstring, SHARED MATH), rounded and clamped."""
    return _clamp_byte(a + (b - a) * t)


def _finish(buffer: bytes | bytearray) -> Image.Image:
    """Wrap a WIDTH*HEIGHT*3 RGB byte buffer as a Pillow image."""
    return Image.frombytes("RGB", (WIDTH, HEIGHT), bytes(buffer))


def _render_vertical_dawn(palette: dict) -> Image.Image:
    """Composition 1, "vertical-dawn" -- see module docstring for the formula."""
    top = _rgb(palette, "window")
    bottom = _rgb(palette, "accent")

    # The gradient is constant across every row's x, so each row needs only
    # ONE colour computed, then replicated WIDTH times -- no per-pixel loop.
    rows = []
    for y in range(HEIGHT):
        t = y / (HEIGHT - 1)
        color = bytes(_lerp_channel(top[c], bottom[c], t) for c in range(3))
        rows.append(color * WIDTH)
    return _finish(b"".join(rows))


def _render_banded_horizon(palette: dict) -> Image.Image:
    """Composition 5, "banded-horizon" -- see module docstring for the formula."""
    left = _rgb(palette, "surface_alt")
    mid = _rgb(palette, "surface")
    right = _rgb(palette, "accent")

    # The gradient is constant down every column's y, so ONE row needs to be
    # computed (one colour per column), then that whole row replicated
    # HEIGHT times -- no per-pixel loop.
    row = bytearray(WIDTH * 3)
    idx = 0
    for x in range(WIDTH):
        t = x / (WIDTH - 1)
        if t <= 0.5:
            local = t / 0.5
            color = (
                _lerp_channel(left[0], mid[0], local),
                _lerp_channel(left[1], mid[1], local),
                _lerp_channel(left[2], mid[2], local),
            )
        else:
            local = (t - 0.5) / 0.5
            color = (
                _lerp_channel(mid[0], right[0], local),
                _lerp_channel(mid[1], right[1], local),
                _lerp_channel(mid[2], right[2], local),
            )
        row[idx] = color[0]
        row[idx + 1] = color[1]
        row[idx + 2] = color[2]
        idx += 3
    return _finish(bytes(row) * HEIGHT)


def _render_diagonal_drift(palette: dict) -> Image.Image:
    """Composition 2, "diagonal-drift" -- see module docstring for the formula."""
    top_left = _rgb(palette, "surface_alt")
    bottom_right = _rgb(palette, "accent")
    denom = (WIDTH - 1) + (HEIGHT - 1)

    buffer = bytearray(WIDTH * HEIGHT * 3)
    idx = 0
    for y in range(HEIGHT):
        for x in range(WIDTH):
            t = (x + y) / denom
            buffer[idx] = _lerp_channel(top_left[0], bottom_right[0], t)
            buffer[idx + 1] = _lerp_channel(top_left[1], bottom_right[1], t)
            buffer[idx + 2] = _lerp_channel(top_left[2], bottom_right[2], t)
            idx += 3
    return _finish(buffer)


def _render_radial_glow(palette: dict) -> Image.Image:
    """Composition 3, "radial-glow" -- see module docstring for the formula."""
    center = _rgb(palette, "accent")
    edge = _rgb(palette, "window")
    cx = (WIDTH - 1) / 2.0
    cy = (HEIGHT - 1) / 2.0
    radius = math.sqrt(cx * cx + cy * cy)

    # WHY precompute per-column dx^2: d(x, y) = sqrt(dx(x)^2 + dy(y)^2), and
    # dx(x)^2 does not depend on y, so computing it once per column (WIDTH
    # times) instead of once per pixel (WIDTH*HEIGHT times) avoids redundant
    # work in the inner loop below.
    dx2 = [(x - cx) ** 2 for x in range(WIDTH)]

    buffer = bytearray(WIDTH * HEIGHT * 3)
    idx = 0
    for y in range(HEIGHT):
        dy2 = (y - cy) ** 2
        for x in range(WIDTH):
            t = _clamp01(math.sqrt(dx2[x] + dy2) / radius)
            buffer[idx] = _lerp_channel(center[0], edge[0], t)
            buffer[idx + 1] = _lerp_channel(center[1], edge[1], t)
            buffer[idx + 2] = _lerp_channel(center[2], edge[2], t)
            idx += 3
    return _finish(buffer)


def _render_corner_glow_dual(palette: dict) -> Image.Image:
    """Composition 4, "corner-glow-dual" -- see module docstring for the formula."""
    base = _rgb(palette, "window")
    glow_top_left = _rgb(palette, "accent")
    glow_bottom_right = _rgb(palette, "surface_alt")
    radius = math.sqrt((WIDTH - 1) ** 2 + (HEIGHT - 1) ** 2)

    # Same precomputation idea as _render_radial_glow, but for both corners'
    # squared-distance terms at once (dx^2 to (0,0) and dx^2 to (WIDTH-1,*)).
    dx2_tl = [x * x for x in range(WIDTH)]
    dx2_br = [(x - (WIDTH - 1)) ** 2 for x in range(WIDTH)]

    buffer = bytearray(WIDTH * HEIGHT * 3)
    idx = 0
    for y in range(HEIGHT):
        dy2_tl = y * y
        dy2_br = (y - (HEIGHT - 1)) ** 2
        for x in range(WIDTH):
            w1 = _clamp01(1.0 - math.sqrt(dx2_tl[x] + dy2_tl) / radius)
            w2 = _clamp01(1.0 - math.sqrt(dx2_br[x] + dy2_br) / radius)
            for c in range(3):
                value = base[c] + w1 * (glow_top_left[c] - base[c]) + w2 * (glow_bottom_right[c] - base[c])
                buffer[idx + c] = _clamp_byte(value)
            idx += 3
    return _finish(buffer)


# composition name -> render function, in the same order as COMPOSITIONS.
_RENDERERS = {
    "vertical-dawn": _render_vertical_dawn,
    "diagonal-drift": _render_diagonal_drift,
    "radial-glow": _render_radial_glow,
    "corner-glow-dual": _render_corner_glow_dual,
    "banded-horizon": _render_banded_horizon,
}


def render(tokens: dict, composition: str, mode: str) -> Image.Image:
    """
    Render one (composition, mode) pair.

    Args:
        tokens: Validated token dictionary (design/validate.py's load_tokens()).
        composition: One of COMPOSITIONS.
        mode: "light" or "dark".

    Returns:
        A WIDTH x HEIGHT (1920x1080) RGB Pillow image, computed exactly as
        this module's own docstring specifies for `composition`, using
        tokens["color"][mode] as the only source of colour.

    Raises:
        ValueError: if composition is not one of COMPOSITIONS, or mode is
            neither "light" nor "dark".
    """
    if mode not in ("light", "dark"):
        raise ValueError(f"mode must be 'light' or 'dark', got {mode!r}")
    if composition not in _RENDERERS:
        raise ValueError(f"composition must be one of {COMPOSITIONS}, got {composition!r}")

    palette = tokens["color"][mode]
    return _RENDERERS[composition](palette)


def generate_wallpapers(tokens: dict, out_dir: Path, name: str) -> list[Path]:
    """
    Render every composition in both modes and write them as PNG files.

    Args:
        tokens: Validated token dictionary.
        out_dir: Directory that receives the wallpapers/ subdirectory
            (created as needed, mirroring design/generate.py's own
            per-target subdirectories under the same out_dir). Existing
            files are overwritten.
        name: Theme name, used as the file name prefix (mirrors
            design/generate.py's own --name convention, and lets more than
            one theme's wallpapers coexist under the same --out-dir).

    Returns:
        The paths of all written files, sorted. Always
        len(COMPOSITIONS) * 2 entries: one light and one dark PNG per
        composition.

    Raises:
        ValueError: if name is not lowercase letters, digits, "_" or "-".
    """
    # WHY: Validate name before creating any files (matches generate.py's own check).
    if not re.fullmatch(r"[a-z0-9_-]+", name):
        raise ValueError("name must be lowercase letters, digits, '_' or '-'")

    wallpapers_dir = out_dir / "wallpapers"
    wallpapers_dir.mkdir(parents=True, exist_ok=True)

    written_paths = []
    for composition in COMPOSITIONS:
        for mode in ("light", "dark"):
            image = render(tokens, composition, mode)
            file_path = wallpapers_dir / f"{name}-{composition}-{mode}.png"
            image.save(file_path, format="PNG")
            written_paths.append(file_path)

    return sorted(written_paths)


def main(argv: list[str] | None = None) -> int:
    """
    Entry point.

    Args:
        argv: Command line arguments, defaults to sys.argv[1:].

    Returns:
        0 on success; 1 when the tokens are invalid (all problems printed to
        stderr, nothing written); 2 when --out-dir would be outside
        PROJECT_ROOT or --name is invalid.
    """
    import argparse

    from design.validate import TokenError, load_tokens

    if argv is None:
        argv = sys.argv[1:]

    parser = argparse.ArgumentParser(description="Generate wallpaper PNGs from design tokens")
    parser.add_argument(
        "--tokens",
        type=Path,
        default=Path(__file__).parent / "tokens.json",
        help="Path to tokens.json (default: design/tokens.json)",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=PROJECT_ROOT / ".build" / "generated",
        help="Output directory (default: .build/generated)",
    )
    parser.add_argument(
        "--name",
        default=os.getenv("DISTRO_NAME", "theme"),
        help="Theme name (default: DISTRO_NAME env var or 'theme')",
    )

    args = parser.parse_args(argv)

    # Validate name
    if not re.fullmatch(r"[a-z0-9_-]+", args.name):
        print(f"error: name must be lowercase letters, digits, '_' or '-', got {args.name!r}", file=sys.stderr)
        return 2

    # Validate out_dir is within PROJECT_ROOT using strict path component check
    try:
        out_dir_resolved = args.out_dir.resolve()
        project_root_resolved = PROJECT_ROOT.resolve()
        # WHY: Use parents check instead of string prefix to prevent sibling directory
        # attacks (e.g. /proj and /proj_evil would both match with startswith, but not
        # with parents check). Mirrors design/generate.py's own guard exactly.
        if out_dir_resolved != project_root_resolved and project_root_resolved not in out_dir_resolved.parents:
            print("error: --out-dir must stay inside the project directory", file=sys.stderr)
            return 2
    except (ValueError, RuntimeError):
        print("error: invalid out-dir path", file=sys.stderr)
        return 2

    # Load and validate tokens
    try:
        tokens = load_tokens(args.tokens)
    except TokenError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    # Generate files
    try:
        generate_wallpapers(tokens, args.out_dir, args.name)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
