"""
Generate a Kvantum theme configuration (".kvconfig") from the design tokens.

This file is the LOCKED INTERFACE: implement the body of render() without
changing its signature or the mapping below. Only the standard library and
`.colors` may be used; never parse hex here.

Uses color.<mode>.* and material.bg_opacity.*. Colour notation: `to_hex_rgb`
(lowercase "#rrggbb").

Output layout (exact): the sections "[%General]" then "[GeneralColors]", each
followed by its "key=value" lines in the order given, one blank line between the
sections, a single trailing newline.

[%General]  (in this order)
  author=design tokens generator
  comment=<name> - generated from design tokens, do not edit
  composite=true
  translucent_windows=true
  blurring=true
  popup_blurring=true
  animate_states=true
  reduce_window_opacity=<round((1 - material.bg_opacity.sidebar) * 100)>
  reduce_menu_opacity=<round((1 - material.bg_opacity.menu) * 100)>
  (integers; use Python's round on the float product, e.g. 0.55 -> 45)

[GeneralColors]  (in this order; token names of color.<mode>)
  window.color=window
  inactive.window.color=window
  base.color=surface
  inactive.base.color=surface
  alt.base.color=surface_alt
  inactive.alt.base.color=surface_alt
  button.color=surface_alt
  light.color=surface
  mid.light.color=surface_alt
  dark.color=separator
  mid.color=separator
  highlight.color=accent
  inactive.highlight.color=accent
  text.color=text
  inactive.text.color=text
  window.text.color=text
  inactive.window.text.color=text
  button.text.color=text
  disabled.text.color=text_disabled
  tooltip.base.color=tooltip_bg
  tooltip.text.color=tooltip_text
  highlight.text.color=accent_text
  link.color=link
  link.visited.color=link_visited

If you KNOW from Kvantum's documentation that one of the keys above does not
exist, omit that single key and say so in your report - do not invent others.

Tokens not used by this generator: error, warning, success, shadow,
button_close, button_minimize, button_maximize, and everything outside
color and material.bg_opacity.
"""

from __future__ import annotations

from .colors import to_hex_rgb  # noqa: F401  (used by the implementation)

# [GeneralColors] key -> token name of color.<mode>, in output order.
_COLOR_KEYS = (
    ("window.color", "window"),
    ("inactive.window.color", "window"),
    ("base.color", "surface"),
    ("inactive.base.color", "surface"),
    ("alt.base.color", "surface_alt"),
    ("inactive.alt.base.color", "surface_alt"),
    ("button.color", "surface_alt"),
    ("light.color", "surface"),
    ("mid.light.color", "surface_alt"),
    ("dark.color", "separator"),
    ("mid.color", "separator"),
    ("highlight.color", "accent"),
    ("inactive.highlight.color", "accent"),
    ("text.color", "text"),
    ("inactive.text.color", "text"),
    ("window.text.color", "text"),
    ("inactive.window.text.color", "text"),
    ("button.text.color", "text"),
    ("disabled.text.color", "text_disabled"),
    ("tooltip.base.color", "tooltip_bg"),
    ("tooltip.text.color", "tooltip_text"),
    ("highlight.text.color", "accent_text"),
    ("link.color", "link"),
    ("link.visited.color", "link_visited"),
)


def _reduction(opacity: float) -> str:
    """
    Convert a background opacity (0..1) into Kvantum's "reduce opacity" percent.

    Kvantum expresses translucency as how much opacity is REMOVED, so it is the
    complement of the token value: 0.55 -> "45".

    Args:
        opacity: Background opacity token, 0.0 (invisible) to 1.0 (opaque).

    Returns:
        The rounded whole percentage as a string.
    """
    # WHY round(): the float product is inexact ((1 - 0.55) * 100 is
    # 44.99999999999999), and a plain int() cast would truncate it to 44, not 45.
    return str(round((1 - opacity) * 100))


def render(tokens: dict, mode: str = "light", name: str = "Theme") -> str:
    """
    Render the Kvantum configuration for one mode.

    Args:
        tokens: Validated token dictionary (see design/validate.py).
        mode: "light" or "dark".
        name: Theme name used in the comment line.

    Returns:
        The complete ".kvconfig" file content, exactly as specified above.

    Raises:
        ValueError: if mode is neither "light" nor "dark".
    """
    if mode not in ("light", "dark"):
        raise ValueError(f"mode must be 'light' or 'dark', got {mode!r}")
    palette = tokens["color"][mode]
    opacity = tokens["material"]["bg_opacity"]

    # The flags are fixed literals from the module docstring, not design values.
    general = [
        ("author", "design tokens generator"),
        ("comment", f"{name} - generated from design tokens, do not edit"),
        ("composite", "true"),
        ("translucent_windows", "true"),
        ("blurring", "true"),
        ("popup_blurring", "true"),
        ("animate_states", "true"),
        ("reduce_window_opacity", _reduction(opacity["sidebar"])),
        ("reduce_menu_opacity", _reduction(opacity["menu"])),
    ]
    colors = [(key, to_hex_rgb(palette[token])) for key, token in _COLOR_KEYS]

    # Blank line between sections, exactly one trailing newline (INI convention).
    sections = (("%General", general), ("GeneralColors", colors))
    blocks = (
        f"[{header}]\n" + "\n".join(f"{key}={value}" for key, value in pairs)
        for header, pairs in sections
    )
    return "\n\n".join(blocks) + "\n"
