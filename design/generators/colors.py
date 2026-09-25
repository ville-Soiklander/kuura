"""
Colour conversion helpers shared by all generators.

Design tokens store colours as "#RRGGBB" or "#RRGGBBAA" strings. Every target
format wants a different notation, so the conversions live in ONE place; a
generator never parses hex itself.

This file is the LOCKED INTERFACE: implement the bodies without changing the
signatures or the exact output formats documented here. Standard library only.
"""

from __future__ import annotations

import re


def parse_hex(value: str) -> tuple[int, int, int, float]:
    """
    Parse a hex colour string.

    Args:
        value: "#RRGGBB" or "#RRGGBBAA" (hex digits in either case). The
            leading "#" is required.

    Returns:
        (red, green, blue, alpha): the channels as ints 0..255 and alpha as a
        float 0.0..1.0 (AA / 255 rounded to 3 decimals, 1.0 when absent).

    Raises:
        ValueError: if the value is not a string of exactly 7 or 9 characters
            in that form, or contains non-hex digits.
    """
    # WHY: Validate the entire string with regex first to reject malformed inputs
    # like "#+12345", "#-12345", "#1_2345", etc. which int(x, 16) would accept.
    # Also check type to reject non-string inputs like None or int.
    if not isinstance(value, str) or not re.fullmatch(r"#[0-9A-Fa-f]{6}([0-9A-Fa-f]{2})?", value):
        raise ValueError(f"Invalid hex colour: {value!r}")

    hex_digits = value[1:]
    # WHY: Now conversion is safe; regex already validated format
    r = int(hex_digits[0:2], 16)
    g = int(hex_digits[2:4], 16)
    b = int(hex_digits[4:6], 16)

    # Parse alpha if present (8 characters total = 9 with "#")
    if len(value) == 9:
        alpha = round(int(hex_digits[6:8], 16) / 255.0, 3)
    else:
        alpha = 1.0

    return (r, g, b, alpha)


def to_rgb_csv(value: str) -> str:
    """
    Format a colour as "R,G,B" (decimal, no spaces, alpha dropped), the notation
    of KDE colour scheme files. Example: "#16788C" -> "22,120,140".

    Args:
        value: Hex colour as accepted by parse_hex.

    Returns:
        The comma separated decimal channels.

    Raises:
        ValueError: as parse_hex.
    """
    r, g, b, _ = parse_hex(value)
    return f"{r},{g},{b}"


def to_hex_rgb(value: str) -> str:
    """
    Format a colour as lowercase "#rrggbb" with alpha dropped, the notation of
    Kvantum configuration files. Example: "#16788C" -> "#16788c".

    Args:
        value: Hex colour as accepted by parse_hex.

    Returns:
        Lowercase six digit hex string with a leading "#".

    Raises:
        ValueError: as parse_hex.
    """
    r, g, b, _ = parse_hex(value)
    return f"#{r:02x}{g:02x}{b:02x}"


def to_css(value: str) -> str:
    """
    Format a colour for GTK CSS.

    Args:
        value: Hex colour as accepted by parse_hex.

    Returns:
        Opaque colours (alpha 1.0): lowercase "#rrggbb". Translucent colours:
        "rgba(R, G, B, A)" with A written with at most 3 decimals and no
        trailing zeros ("0.2", "0.4", never "0.200"). Example: "#00000033" ->
        "rgba(0, 0, 0, 0.2)".

    Raises:
        ValueError: as parse_hex.
    """
    r, g, b, alpha = parse_hex(value)

    if alpha == 1.0:
        return f"#{r:02x}{g:02x}{b:02x}"

    # WHY: Format alpha to 3 decimals, then strip trailing zeros and decimal point if needed
    # E.g., "0.200" -> "0.2", "0.100" -> "0.1", "1.000" -> "1"
    alpha_str = f"{alpha:.3f}".rstrip("0").rstrip(".")
    return f"rgba({r}, {g}, {b}, {alpha_str})"


def to_qml(value: str) -> str:
    """
    Format a colour for QML, which puts alpha FIRST.

    Args:
        value: Hex colour as accepted by parse_hex.

    Returns:
        Opaque colours: uppercase "#RRGGBB". Translucent colours: uppercase
        "#AARRGGBB". Example: "#00000033" -> "#33000000".

    Raises:
        ValueError: as parse_hex.
    """
    r, g, b, alpha = parse_hex(value)

    if alpha == 1.0:
        return f"#{r:02X}{g:02X}{b:02X}"

    # WHY: Convert alpha (0.0..1.0) to hex (0..255) and place it first
    alpha_hex = int(round(alpha * 255))
    return f"#{alpha_hex:02X}{r:02X}{g:02X}{b:02X}"
