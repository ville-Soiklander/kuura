"""
Generate a GTK4 CSS file from the design tokens.

This file is the LOCKED INTERFACE: implement the body of render() without
changing its signature or the exact output below. Only the standard library and
`.colors` may be used; never parse hex here. Colour notation: `to_css`.

Exact output (nothing else, single trailing newline). Placeholders in {braces}
are replaced by the value named; "<key>" lines repeat for every key of
tokens["color"][mode] in ascending alphabetical key order.

/* {name} {mode} - generated from design tokens, do not edit. */
@define-color token_<key> <to_css(value)>;
* {
  font-family: "{type.family_ui}";
  font-size: {type.size.body}px;
  font-weight: {type.weight.regular};
}
window, .csd {
  border-radius: {radius.window}px;
}
button {
  border-radius: {radius.button}px;
  padding: {spacing.grid}px {spacing.grid * 3}px;
  transition: all {motion.duration.fast}ms {motion.easing_standard};
}
entry, spinbutton {
  border-radius: {radius.field}px;
}
tooltip {
  border-radius: {radius.tooltip}px;
}
popover > contents, menu {
  border-radius: {radius.menu}px;
}
.card {
  border-radius: {radius.card}px;
}

Numbers are printed with `str()`. Tokens not used by this generator: material.*,
panel.*, spacing.gutter, spacing.section, type.family_mono, type.size (except
body), type.weight (except regular), type.tracking, radius.icon,
motion.duration (except fast), motion.easing_spring.
"""

from __future__ import annotations

from .colors import to_css  # noqa: F401  (used by the implementation)


def render(tokens: dict, mode: str = "light", name: str = "Theme") -> str:
    """
    Render the GTK4 CSS for one mode.

    Args:
        tokens: Validated token dictionary (see design/validate.py).
        mode: "light" or "dark".
        name: Theme name used in the header comment.

    Returns:
        The complete CSS file content, exactly as specified above.

    Raises:
        ValueError: if mode is neither "light" nor "dark".
    """
    if mode not in ("light", "dark"):
        raise ValueError("mode must be 'light' or 'dark'")

    lines = []

    # Header comment
    lines.append(f"/* {name} {mode} - generated from design tokens, do not edit. */")

    # Color definitions, sorted by key in ascending alphabetical order
    color_tokens = tokens["color"][mode]
    for key in sorted(color_tokens.keys()):
        value = color_tokens[key]
        lines.append(f"@define-color token_{key} {to_css(value)};")

    # CSS rules with 2-space indentation
    lines.append("* {")
    lines.append(f'  font-family: "{tokens["type"]["family_ui"]}";')
    lines.append(f'  font-size: {tokens["type"]["size"]["body"]}px;')
    lines.append(f'  font-weight: {tokens["type"]["weight"]["regular"]};')
    lines.append("}")
    lines.append("window, .csd {")
    lines.append(f'  border-radius: {tokens["radius"]["window"]}px;')
    lines.append("}")
    lines.append("button {")
    lines.append(f'  border-radius: {tokens["radius"]["button"]}px;')
    grid = tokens["spacing"]["grid"]
    lines.append(f"  padding: {grid}px {grid * 3}px;")
    lines.append(
        f'  transition: all {tokens["motion"]["duration"]["fast"]}ms {tokens["motion"]["easing_standard"]};'
    )
    lines.append("}")
    lines.append("entry, spinbutton {")
    lines.append(f'  border-radius: {tokens["radius"]["field"]}px;')
    lines.append("}")
    lines.append("tooltip {")
    lines.append(f'  border-radius: {tokens["radius"]["tooltip"]}px;')
    lines.append("}")
    lines.append("popover > contents, menu {")
    lines.append(f'  border-radius: {tokens["radius"]["menu"]}px;')
    lines.append("}")
    lines.append(".card {")
    lines.append(f'  border-radius: {tokens["radius"]["card"]}px;')
    lines.append("}")

    return "\n".join(lines) + "\n"
