"""
Render the ISO's BIOS boot menu background (iso/profile/syslinux/splash.png).

WHY this exists: the archiso profile shipped the upstream distribution's logo as
the syslinux menu background. The boot menu must carry this project's own look
only, so the image is generated from design/tokens.json, like every other
generated asset (wallpapers, icons, sounds), with no external artwork.

Format constraints (syslinux vesamenu.c32): the background must be a PNG or JPEG
of exactly 640x480 pixels (the menu is drawn in the 640x480 VESA mode). The
output is a plain 8-bit RGB PNG without alpha or palette, the most widely
decodable form.

Composition (all colours from tokens["color"]["dark"]; the boot menu is dark):
  * vertical gradient from `window` (top) to `surface` (bottom), per-row lerp
    with round() like design/generate_wallpapers.py;
  * the distribution name, capitalised the way the rest of the UI does
    (`name.capitalize()`, see design/generators/calamares_branding.py), drawn in
    `text` in the top band, which the menu box (MENU VSHIFT) leaves free, with a
    short `accent` rule below it.
Text uses Pillow's bundled default font (ImageFont.load_default(size)), so no
system font is needed and the pixels are reproducible for a pinned Pillow.

Usage (from the project root):
    python -m design.generate_bootsplash [--tokens FILE] [--out FILE] [--name NAME]
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from design.generators.colors import parse_hex

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# syslinux vesamenu requires this exact size.
WIDTH = 640
HEIGHT = 480

# Wordmark size in pixels and the vertical position of its top edge. The menu box
# starts below row ~160 (MENU VSHIFT 10 at 16px per line), so the band above is free.
FONT_SIZE = 72
TEXT_TOP = 36
RULE_GAP = 22
RULE_WIDTH = 96
RULE_HEIGHT = 4

DEFAULT_OUT = PROJECT_ROOT / "iso" / "profile" / "syslinux" / "splash.png"


def _rgb(palette: dict, token: str) -> tuple[int, int, int]:
    """Return the RGB channels of a palette token (alpha, if any, is dropped)."""
    r, g, b, _alpha = parse_hex(palette[token])
    return (r, g, b)


def render(tokens: dict, name: str) -> Image.Image:
    """
    Render the boot menu background.

    Args:
        tokens: Validated token dictionary (uses color.dark only).
        name: Lowercase distribution name; displayed capitalised.

    Returns:
        A 640x480 RGB Pillow image.

    Raises:
        ValueError: if name is not lowercase letters, digits, "_" or "-".
    """
    if not re.fullmatch(r"[a-z0-9_-]+", name):
        raise ValueError("name must be lowercase letters, digits, '_' or '-'")

    palette = tokens["color"]["dark"]
    top, bottom = _rgb(palette, "window"), _rgb(palette, "surface")

    # One colour per row, replicated across the width: the gradient does not vary in x.
    rows = []
    for y in range(HEIGHT):
        t = y / (HEIGHT - 1)
        rows.append(bytes(round(top[c] + (bottom[c] - top[c]) * t) for c in range(3)) * WIDTH)
    image = Image.frombytes("RGB", (WIDTH, HEIGHT), b"".join(rows))

    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(FONT_SIZE)
    label = name.capitalize()
    left, _t, right, bottom_edge = draw.textbbox((0, 0), label, font=font)
    x = (WIDTH - (right - left)) // 2 - left
    draw.text((x, TEXT_TOP), label, font=font, fill=_rgb(palette, "text"))

    rule_top = TEXT_TOP + bottom_edge + RULE_GAP
    rule_left = (WIDTH - RULE_WIDTH) // 2
    draw.rectangle(
        (rule_left, rule_top, rule_left + RULE_WIDTH - 1, rule_top + RULE_HEIGHT - 1),
        fill=_rgb(palette, "accent"),
    )
    return image


def generate_bootsplash(tokens: dict, out_file: Path, name: str) -> Path:
    """
    Render and write the splash PNG.

    Args:
        tokens: Validated token dictionary.
        out_file: Destination file (parent directory is created).
        name: Lowercase distribution name.

    Returns:
        out_file.

    Raises:
        ValueError: if name is invalid.
    """
    image = render(tokens, name)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    image.save(out_file, format="PNG")
    return out_file


def main(argv: list[str] | None = None) -> int:
    """
    Entry point.

    Returns:
        0 on success; 1 for invalid tokens; 2 for an invalid --name or an --out
        outside the project directory.
    """
    import argparse

    from design.validate import TokenError, load_tokens

    parser = argparse.ArgumentParser(description="Generate the ISO boot menu splash PNG")
    parser.add_argument("--tokens", type=Path, default=Path(__file__).parent / "tokens.json")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--name", default=os.getenv("DISTRO_NAME", "kuura"))
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    if not re.fullmatch(r"[a-z0-9_-]+", args.name):
        print("error: name must be lowercase letters, digits, '_' or '-'", file=sys.stderr)
        return 2
    # Same traversal guard as the other generators: write only inside the project.
    root = PROJECT_ROOT.resolve()
    out = args.out.resolve()
    if root not in out.parents:
        print("error: --out must stay inside the project directory", file=sys.stderr)
        return 2
    try:
        tokens = load_tokens(args.tokens)
    except TokenError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(generate_bootsplash(tokens, out, args.name))
    return 0


if __name__ == "__main__":
    sys.exit(main())
