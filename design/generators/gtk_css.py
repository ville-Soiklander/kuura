"""
Generate a GTK4 CSS file from the design tokens.

This file is the LOCKED INTERFACE: implement the body of render() without
changing its signature or the exact output below. Only the standard library and
`.colors` may be used; never parse hex here. Colour notation: `to_css`.

REVISED (2026-10): the previous version of this spec defined `@define-color
token_<key>` custom properties but never referenced a single one of them from
any rule below - confirmed live (packages/kuura-shell, Vaihe 6 GTK3/4 work)
that switching gtk.css/gtk-dark.css therefore never changed any visible colour
for any GTK app, only border-radius/font/transition. This revision fixes
exactly that, using ONLY tokens that were already defined and already unused -
no new colour tokens, no new selectors, no scope beyond "make the colours this
file already declares actually apply to something":
- `window, .csd` (the app's own background) now also sets
  `background-color: @token_window;` - the base surface every other element
  sits on top of.
- `*` now also sets `color: @token_text;` - the default text colour, inherited
  by every element below unless overridden (CSS `color` inherits by default;
  `background-color` does not, which is why every surface-like rule below
  needs its own explicit background-color line).
- `button`, `entry`/`spinbutton`, `popover > contents`/`menu`, and `.card` each
  now also set `background-color: @token_surface;` - these are the "raised
  above the window background" surfaces token_surface was always meant for.
- `tooltip` now also sets `background-color: @token_tooltip_bg;` and
  `color: @token_tooltip_text;` - its own dedicated, mode-INDEPENDENT-looking
  pair (tooltip_bg is dark and tooltip_text is light in both light and dark
  mode in the shipped tokens, by design: a tooltip is always a small dark
  flyout), overriding the inherited `color: @token_text;` from `*` above.

`@token_<key>` is the correct GTK CSS reference syntax for a name declared
with `@define-color token_<key> ...;` above (both GTK3 and GTK4 support this -
confirmed against the real pinned source for both, same investigation that
found this gap in the first place).

REVISED AGAIN (2026-10-07): live re-verification of the colour fix above (once
a real activation-level blocker unrelated to this file was separately worked
around, see packages/kuura-shell/skel/.config/plasma-workspace/env/'s own new
GTK-theme script) found a second, pre-existing gap it made visible for the
first time: `button`, `entry`/`spinbutton`, `popover > contents`/`menu` and
`.card` all sit directly on the `window`/`surface` background with NO border
at all, because this file has never emitted one - invisible before only
because no real theme of this file's shape had ever actually been the active
GTK stylesheet to compare against. Fixed the same minimal way as the colour
gap: one more already-declared, already-unused token put to use,
`color.*.separator` (a real token, already used by Kvantum/Plasma colour
schemes elsewhere in this project, just never here) - semantically exactly
what a GTK `separator` CSS node and a subtle UI border are both for. Added
`border: 1px solid @token_separator;` to the same four rule blocks that
already gained `background-color: @token_surface;` above (not to `window,
.csd`, which is the outermost chrome and was never bordered, and not to
`tooltip`, which keeps its own distinct background/text pair without needing
a border to read as a separate surface).

Exact output (nothing else, single trailing newline). Placeholders in {braces}
are replaced by the value named; "<key>" lines repeat for every key of
tokens["color"][mode] in ascending alphabetical key order.

/* {name} {mode} - generated from design tokens, do not edit. */
@define-color token_<key> <to_css(value)>;
* {
  font-family: "{type.family_ui}";
  font-size: {type.size.body}px;
  font-weight: {type.weight.regular};
  color: @token_text;
}
window, .csd {
  background-color: @token_window;
  border-radius: {radius.window}px;
}
button {
  background-color: @token_surface;
  border: 1px solid @token_separator;
  border-radius: {radius.button}px;
  padding: {spacing.grid}px {spacing.grid * 3}px;
  transition: all {motion.duration.fast}ms {motion.easing_standard};
}
entry, spinbutton {
  background-color: @token_surface;
  border: 1px solid @token_separator;
  border-radius: {radius.field}px;
}
tooltip {
  background-color: @token_tooltip_bg;
  color: @token_tooltip_text;
  border-radius: {radius.tooltip}px;
}
popover > contents, menu {
  background-color: @token_surface;
  border: 1px solid @token_separator;
  border-radius: {radius.menu}px;
}
.card {
  background-color: @token_surface;
  border: 1px solid @token_separator;
  border-radius: {radius.card}px;
}

Numbers are printed with `str()`. Tokens not used by this generator: material.*,
panel.*, spacing.gutter, spacing.section, type.family_mono, type.size (except
body), type.weight (except regular), type.tracking, radius.icon,
motion.duration (except fast), motion.easing_spring, color.* keys other than
window/surface/text/tooltip_bg/tooltip_text/separator (surface_alt,
text_secondary, text_disabled, accent, accent_text, link, link_visited,
error, warning, success, shadow, button_close/minimize/maximize - all real,
all already used elsewhere in this project, e.g. Kvantum/Plasma colour
schemes; deliberately out of scope for this minimal fix, not another
oversight).
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

    # CSS rules with 2-space indentation.
    # `*` sets the default text colour; `color` inherits by default in CSS so
    # every other element below gets this unless it overrides it (tooltip does).
    lines.append("* {")
    lines.append(f'  font-family: "{tokens["type"]["family_ui"]}";')
    lines.append(f'  font-size: {tokens["type"]["size"]["body"]}px;')
    lines.append(f'  font-weight: {tokens["type"]["weight"]["regular"]};')
    lines.append("  color: @token_text;")
    lines.append("}")
    # The app's own background - the base surface every other element sits on.
    lines.append("window, .csd {")
    lines.append("  background-color: @token_window;")
    lines.append(f'  border-radius: {tokens["radius"]["window"]}px;')
    lines.append("}")
    # `background-color` does NOT inherit, so every surface-like rule below
    # needs its own explicit line even though they all use the same token.
    # `border` is added here (and to entry/popover/.card below) because the
    # confirmatory GTK_THEME-forced capture showed these surfaces rendering
    # with NO border at all once a real theme actually became the active
    # stylesheet - this file never emitted one. `color.*.separator` is an
    # already-declared, already-unused-by-this-file token, semantically
    # exactly what a subtle UI border is for (see module docstring, "REVISED
    # AGAIN" section). Not added to `window, .csd` (outermost chrome, never
    # bordered) or `tooltip` (keeps its own distinct background/text pair).
    lines.append("button {")
    lines.append("  background-color: @token_surface;")
    lines.append("  border: 1px solid @token_separator;")
    lines.append(f'  border-radius: {tokens["radius"]["button"]}px;')
    grid = tokens["spacing"]["grid"]
    lines.append(f"  padding: {grid}px {grid * 3}px;")
    lines.append(
        f'  transition: all {tokens["motion"]["duration"]["fast"]}ms {tokens["motion"]["easing_standard"]};'
    )
    lines.append("}")
    lines.append("entry, spinbutton {")
    lines.append("  background-color: @token_surface;")
    lines.append("  border: 1px solid @token_separator;")
    lines.append(f'  border-radius: {tokens["radius"]["field"]}px;')
    lines.append("}")
    # Tooltip gets its own dedicated background/text pair - always a small
    # dark flyout in both light and dark mode by design - overriding the
    # inherited `color: @token_text;` from `*` above.
    lines.append("tooltip {")
    lines.append("  background-color: @token_tooltip_bg;")
    lines.append("  color: @token_tooltip_text;")
    lines.append(f'  border-radius: {tokens["radius"]["tooltip"]}px;')
    lines.append("}")
    lines.append("popover > contents, menu {")
    lines.append("  background-color: @token_surface;")
    lines.append("  border: 1px solid @token_separator;")
    lines.append(f'  border-radius: {tokens["radius"]["menu"]}px;')
    lines.append("}")
    lines.append(".card {")
    lines.append("  background-color: @token_surface;")
    lines.append("  border: 1px solid @token_separator;")
    lines.append(f'  border-radius: {tokens["radius"]["card"]}px;')
    lines.append("}")

    return "\n".join(lines) + "\n"
