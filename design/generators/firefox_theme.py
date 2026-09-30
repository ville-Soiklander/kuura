"""
Generate Firefox's userChrome.css/userContent.css (the browser's own internal
chrome styling, not a normal webpage stylesheet) from design/tokens.json.

This file is the LOCKED INTERFACE: implement the bodies of render_chrome() and
render_content() without changing their signatures. Only the standard library
may be used. Never hard-code a colour, radius or spacing value here - read it
from tokens, the same rule every generator in this package already follows.

WHY two functions, not one: Firefox loads userChrome.css (styles the browser's
own UI chrome - tabs, the address bar, toolbars) and userContent.css (styles
content Firefox itself renders, e.g. about: pages, not arbitrary websites)
as two separate files from <profile>/chrome/, loaded independently. Keeping
them as two functions/two output files mirrors that real, separate loading,
rather than concatenating them into one file Firefox would only partially use.

WHY mode-dependent (tokens, mode, name) -> str, matching design/generators/
gtk_css.py's own shape: Firefox's own chrome DOES need to track the desktop's
light/dark toggle (unlike this project's icon set, which deliberately does not
- see design/generators/icon_svg.py's own docstring for why that one case is
different). Firefox's userChrome.css can react to the browser's own dark-mode
state via the standard `prefers-color-scheme` media feature (Firefox's chrome
UI is itself a web-rendering surface and supports normal CSS media queries),
so render_chrome()/render_content() should emit BOTH palettes guarded by
`@media (prefers-color-scheme: dark)`/`(prefers-color-scheme: light)` in a
SINGLE output file, the same "emit both, let the environment pick" pattern
design/generators/gtk_css.py already uses for GTK4's own light/gtk-dark.css
pair being loaded conditionally.

CONFIRMED (this project's own research pass, cross-checked, not guessed):
Mozilla's own docs (developer.mozilla.org, Mozilla Extensions / -moz-
prefixed CSS reference) document `prefers-color-scheme` as a standard,
supported media feature and chrome-privileged stylesheets (userChrome.css/
userContent.css) as ordinary CSS documents that support standard media
queries the same way a web page does - browser chrome is itself rendered by
Gecko's own layout engine. This is consistent with how every other dark-mode
switch in this project works (follows the OS/toolkit theme) and is the basis
for the "emit both palettes, single file" design below. It was NOT possible to
confirm this by booting a real Firefox 156.0.1 profile in this change (no VM
boot was available in the environment that implemented this file - see
design/generate_firefox.py's own module docstring and this project's PDF/
handback report for the exact state of that check) - flagged here rather than
silently reported as proven live, per this module's own instruction above.

REAL, VERIFIED FACTS TO BUILD ON (from this project's own bounded research
pass into Firefox 156.0.1, not guessed - do not re-derive these, use them):
  - Selectors confirmed current against an actively-maintained (commits days
    old) community userChrome.css reference: `#TabsToolbar` (tab bar),
    `#urlbar`, `.urlbarView`, `#urlbar-background`, `#identity-icon`,
    `.urlbar-input-container` (address bar and its popup), `#nav-bar`,
    `#navigator-toolbox`, `#toolbar-menubar` (surrounding structure).
  - These are INTERNAL, UNDOCUMENTED-BY-MOZILLA UI hooks, not a stable public
    API - unlike every other generator in this package, this one cannot be
    fully verified by reading Firefox's own source/docs alone. It MUST be
    checked against a real, booted Firefox 156.0.1 before being considered
    done - do not report success from code review alone. Only the CONFIRMED
    selectors above are used below; no additional, unconfirmed selector
    (e.g. an individual tab's internal structure) is guessed at.
  - `@-moz-document url-prefix("...")` was restricted to chrome-privileged
    "user and UA sheets" in Firefox 59 (removed from ordinary web content
    stylesheets around the same time for fingerprinting reasons) but remains
    supported for exactly this kind of file - confirmed against MDN's own
    Mozilla CSS extensions reference during this project's research pass.
    render_content() relies on this to scope its rules to about: pages only,
    so they can never leak onto an ordinary website the user visits.

Args (both functions):
    tokens: Validated token dictionary (design/validate.py's load_tokens()).
    mode: "light" or "dark" - which of the two `@media (prefers-color-scheme)`
        blocks strictly needs this project's palette confirmed working in a
        real boot first; both should still be emitted in one file regardless,
        this argument existing for shape-parity with gtk_css.py's own
        render(tokens, mode, name) signature (see WHY above) even though the
        real output is not actually mode-split the way gtk_css.py's two
        SEPARATE files are. Still validated (raises like gtk_css.py) so a
        caller typo is caught the same way it would be for any other
        generator, even though the value itself does not change the output.
    name: Theme name (unused by the chrome/content CSS itself - no visible
        "kuura" branding belongs in browser chrome - kept for CLI/signature
        parity with every other generator's own (tokens, mode, name) shape).

Returns:
    Complete CSS text (both light and dark @media blocks), ending with
    exactly one trailing newline, matching every other generator's own
    output convention in this package.
"""

from __future__ import annotations

from .colors import to_css

# The CSS custom-property names shared between the light and dark palette
# blocks in userChrome.css. Kept as one ordered tuple so both @media blocks
# are guaranteed to define exactly the same set of variables in the same
# order - a drifted set (e.g. dark missing a key light defines) would silently
# leave a variable unset in dark mode instead of failing loudly, so both
# blocks below are built from this single source of truth.
_CHROME_COLOR_KEYS = (
    "window",
    "surface",
    "surface_alt",
    "text",
    "text_secondary",
    "separator",
    "accent",
    "accent_text",
    "shadow",
)


def _mode_block(color_tokens: dict) -> list[str]:
    """
    Build the `:root { --kuura-chrome-<key>: <css colour>; }` lines for one
    palette (light or dark), reading only the keys in _CHROME_COLOR_KEYS.

    WHY a helper: render_chrome() needs this exact block twice (once per
    `prefers-color-scheme` branch) with only the source dict differing: a
    plain loop shared between both call sites is safer than writing the same
    eleven lines out twice by hand, which would be easy to let drift.

    Args:
        color_tokens: One of tokens["color"]["light"] / tokens["color"]["dark"].

    Returns:
        Indented CSS custom-property declaration lines (no braces).
    """
    return [
        f"    --kuura-chrome-{key.replace('_', '-')}: {to_css(color_tokens[key])};"
        for key in _CHROME_COLOR_KEYS
    ]


def render_chrome(tokens: dict, mode: str, name: str) -> str:
    """userChrome.css content: tab bar + address bar styling. See module docstring."""
    if mode not in ("light", "dark"):
        raise ValueError("mode must be 'light' or 'dark'")

    radius = tokens["radius"]
    spacing = tokens["spacing"]
    type_tokens = tokens["type"]
    motion = tokens["motion"]

    lines = [
        "/* userChrome.css - generated from design tokens, do not edit.",
        " * Pinned target: Firefox 156.0.1.",
        " *",
        " * Requires the pref toolkit.legacyUserProfileCustomizations.stylesheets = true",
        " * (default false) for ANY file in <profile>/chrome/ to load at all - shipped by",
        " * this project's policies.json, see design/generate_firefox.py's own docstring",
        " * for why that pref specifically needs Status \"user\", not \"default\".",
        " *",
        " * Selectors used below - #navigator-toolbox, #toolbar-menubar, #nav-bar,",
        " * #TabsToolbar, #urlbar, #urlbar-background, .urlbarView, #identity-icon,",
        " * .urlbar-input-container - are Mozilla-internal, UNDOCUMENTED UI hooks, not a",
        " * stable public API. Confirmed current against an actively-maintained community",
        " * reference (github.com/MrOtherGuy/firefox-csshacks, files marked compatible with",
        " * Firefox 133+) during this project's own research pass - not guessed, but also",
        " * not guaranteed byte-identical in exactly 156.0.1 without a real boot check.",
        " * No selector beyond this confirmed set is used (e.g. nothing reaches inside an",
        " * individual tab's internal structure), to avoid guessing an unverified hook.",
        " *",
        " * prefers-color-scheme: documented by Mozilla (developer.mozilla.org) as a",
        " * standard media feature that chrome-privileged stylesheets support like any",
        " * other CSS document Gecko renders - both palettes are emitted below in one",
        " * file, mirroring design/generators/gtk_css.py's light/gtk-dark.css pattern,",
        " * rather than being split by the `mode` argument. This specific behaviour was",
        " * NOT independently confirmed against a live, booted 156.0.1 profile by this",
        " * change - report this alongside the file rather than assuming it silently. */",
        "",
        ":root {",
        f"  --kuura-chrome-radius-field: {radius['field']}px;",
        f"  --kuura-chrome-radius-menu: {radius['menu']}px;",
        f"  --kuura-chrome-font-family: \"{type_tokens['family_ui']}\";",
        f"  --kuura-chrome-font-size: {type_tokens['size']['body']}px;",
        f"  --kuura-chrome-spacing: {spacing['grid']}px;",
        f"  --kuura-chrome-transition: {motion['duration']['fast']}ms {motion['easing_standard']};",
        "}",
        "",
        "@media (prefers-color-scheme: light) {",
        "  :root {",
        *_mode_block(tokens["color"]["light"]),
        "  }",
        "}",
        "",
        "@media (prefers-color-scheme: dark) {",
        "  :root {",
        *_mode_block(tokens["color"]["dark"]),
        "  }",
        "}",
        "",
        "/* Toolbox / menu bar / nav bar: the chrome's main background and text colour.",
        " * !important matches this project's research reference's own convention -",
        " * Firefox's built-in chrome stylesheet is loaded after userChrome.css with",
        " * selectors of comparable specificity, so an unqualified declaration here is",
        " * routinely overridden without it. */",
        "#navigator-toolbox,",
        "#toolbar-menubar,",
        "#nav-bar {",
        "  background-color: var(--kuura-chrome-surface) !important;",
        "  color: var(--kuura-chrome-text) !important;",
        "  font-family: var(--kuura-chrome-font-family);",
        "  font-size: var(--kuura-chrome-font-size);",
        "  border-color: var(--kuura-chrome-separator) !important;",
        "}",
        "",
        "/* Tab strip: a slightly different tone from the toolbar so the tab row still",
        " * reads as a distinct band (tokens.color.window vs. tokens.color.surface). */",
        "#TabsToolbar {",
        "  background-color: var(--kuura-chrome-window) !important;",
        "  border-bottom: 1px solid var(--kuura-chrome-separator);",
        "}",
        "",
        "/* Address bar field: radius.field (an input, styled like every other text field",
        " * in this project's tokens) and a border that turns to the accent colour while",
        " * focused - #urlbar itself is a confirmed selector; :focus-within is standard",
        " * CSS, not a Firefox-internal hook, so combining them here does not introduce a",
        " * new, unconfirmed selector of its own. */",
        "#urlbar-background {",
        "  background-color: var(--kuura-chrome-surface-alt) !important;",
        "  border: 1px solid var(--kuura-chrome-separator);",
        "  border-radius: var(--kuura-chrome-radius-field) !important;",
        "  transition: border-color var(--kuura-chrome-transition),",
        "    background-color var(--kuura-chrome-transition);",
        "}",
        "#urlbar:focus-within #urlbar-background {",
        "  border-color: var(--kuura-chrome-accent);",
        "}",
        "",
        "/* Address bar results popup (search suggestions, history, bookmarks): a",
        " * slightly lighter/darker surface than the field itself, radius.menu because",
        " * it behaves like a dropdown menu, and a shadow so it reads as elevated above",
        " * the page - matches this project's own material language for popups. */",
        ".urlbarView {",
        "  background-color: var(--kuura-chrome-surface) !important;",
        "  color: var(--kuura-chrome-text) !important;",
        "  border-radius: var(--kuura-chrome-radius-menu) !important;",
        "  box-shadow: 0 4px 16px var(--kuura-chrome-shadow);",
        "  font-family: var(--kuura-chrome-font-family);",
        "  font-size: var(--kuura-chrome-font-size);",
        "}",
        "",
        "/* Address bar text + the site identity (padlock/info) icon in front of it. */",
        ".urlbar-input-container {",
        "  color: var(--kuura-chrome-text) !important;",
        "}",
        "#identity-icon {",
        "  fill: var(--kuura-chrome-text-secondary);",
        "}",
    ]

    return "\n".join(lines) + "\n"


def render_content(tokens: dict, mode: str, name: str) -> str:
    """userContent.css content: Firefox-rendered internal pages. See module docstring."""
    if mode not in ("light", "dark"):
        raise ValueError("mode must be 'light' or 'dark'")

    type_tokens = tokens["type"]
    light = tokens["color"]["light"]
    dark = tokens["color"]["dark"]

    lines = [
        "/* userContent.css - generated from design tokens, do not edit.",
        " * Pinned target: Firefox 156.0.1. Gated by the same",
        " * toolkit.legacyUserProfileCustomizations.stylesheets pref as userChrome.css -",
        " * see that file's own header comment.",
        " *",
        " * Wrapped in @-moz-document url-prefix(\"about:\") so these rules apply ONLY to",
        " * Firefox's own about: pages (e.g. about:blank, about:newtab), never to an",
        " * ordinary website the user visits - userContent.css with no such scoping would",
        " * leak into every page loaded, which is not this file's job (that is a normal",
        " * webpage's own CSS). @-moz-document was removed from ordinary web-page",
        " * stylesheets in Firefox 59 (fingerprinting concerns) but remains supported in",
        " * chrome-privileged user sheets like this one - confirmed against MDN's own",
        " * Mozilla CSS extensions reference during this project's research pass, not",
        " * guessed; still worth a real boot check, which was not available when this",
        " * file was implemented (see design/generate_firefox.py's own docstring).",
        " *",
        " * Only broad, safe page-wide properties are set (background/text/link colours,",
        " * base font). about: pages' internal DOM (about:newtab's own React app, etc.)",
        " * was outside this project's confirmed-selector research pass, so no deeper,",
        " * page-specific selector is guessed at here. */",
        "",
        "@-moz-document url-prefix(\"about:\") {",
        "  :root {",
        f"    font-family: \"{type_tokens['family_ui']}\";",
        f"    font-size: {type_tokens['size']['body']}px;",
        "  }",
        "",
        "  @media (prefers-color-scheme: light) {",
        "    :root {",
        f"      background-color: {to_css(light['window'])} !important;",
        f"      color: {to_css(light['text'])} !important;",
        "    }",
        f"    a {{ color: {to_css(light['link'])}; }}",
        f"    a:visited {{ color: {to_css(light['link_visited'])}; }}",
        "  }",
        "",
        "  @media (prefers-color-scheme: dark) {",
        "    :root {",
        f"      background-color: {to_css(dark['window'])} !important;",
        f"      color: {to_css(dark['text'])} !important;",
        "    }",
        f"    a {{ color: {to_css(dark['link'])}; }}",
        f"    a:visited {{ color: {to_css(dark['link_visited'])}; }}",
        "  }",
        "}",
    ]

    return "\n".join(lines) + "\n"
