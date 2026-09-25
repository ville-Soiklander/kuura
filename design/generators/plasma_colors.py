"""
Generate a KDE Plasma colour scheme (".colors" INI file) from the design tokens.

This file is the LOCKED INTERFACE: implement the body of render() without
changing its signature or the mapping below. Only the standard library and
`.colors` (the shared conversion helpers) may be used; never parse hex here.

Uses the tokens color.<mode>.* only. Colour notation: `to_rgb_csv` ("R,G,B").

Output layout (exact): sections in this order, each as "[Section]" followed by
its "Key=Value" lines in the key order given below, one blank line between
sections, a single trailing newline. Colour values are `to_rgb_csv(token)`.

1. [ColorEffects:Disabled]  (in this key order)
   Color=<text_disabled>, ColorAmount=0, ColorEffect=0, ContrastAmount=0.65,
   ContrastEffect=1, IntensityAmount=0.1, IntensityEffect=2
2. [ColorEffects:Inactive]
   ChangeSelectionColor=true, Color=<text_secondary>, ColorAmount=0.025,
   ColorEffect=2, ContrastAmount=0.1, ContrastEffect=2, Enable=false,
   IntensityAmount=0, IntensityEffect=0
3. [Colors:Button], [Colors:Complementary], [Colors:Header],
   [Colors:Selection], [Colors:Tooltip], [Colors:View], [Colors:Window]
   Every group has these 12 keys in this order: BackgroundAlternate,
   BackgroundNormal, DecorationFocus, DecorationHover, ForegroundActive,
   ForegroundInactive, ForegroundLink, ForegroundNegative, ForegroundNeutral,
   ForegroundNormal, ForegroundPositive, ForegroundVisited.
   Token per key and group (token names of color.<mode>):

   | key                | View       | Window/Complementary/Header | Button      | Tooltip      | Selection   |
   |--------------------|------------|-----------------------------|-------------|--------------|-------------|
   | BackgroundAlternate| surface_alt| surface_alt                 | surface     | tooltip_bg   | accent      |
   | BackgroundNormal   | surface    | window                      | surface_alt | tooltip_bg   | accent      |
   | DecorationFocus    | accent     | accent                      | accent      | accent       | accent_text |
   | DecorationHover    | accent     | accent                      | accent      | accent       | accent_text |
   | ForegroundActive   | accent     | accent                      | accent      | tooltip_text | accent_text |
   | ForegroundInactive | text_secondary (all of View, Window, Complementary, Header, Button) | tooltip_text | accent_text |
   | ForegroundLink     | link       | link                        | link        | tooltip_text | accent_text |
   | ForegroundNegative | error (all groups)                                                                 |
   | ForegroundNeutral  | warning (all groups)                                                               |
   | ForegroundNormal   | text       | text                        | text        | tooltip_text | accent_text |
   | ForegroundPositive | success (all groups)                                                               |
   | ForegroundVisited  | link_visited (View, Window, Complementary, Header, Button) | tooltip_text | accent_text |

4. [General]: ColorScheme=<name>, Name=<name>
5. [KDE]: contrast=4
6. [WM]: activeBackground=<window>, activeBlend=<text>,
   activeForeground=<text>, inactiveBackground=<window>,
   inactiveBlend=<text_secondary>, inactiveForeground=<text_secondary>

Tokens not used by this generator: separator, shadow, button_close,
button_minimize, button_maximize (the KDE scheme has no key for them).
"""

from __future__ import annotations

from .colors import to_rgb_csv  # noqa: F401  (used by the implementation)

# Token behind every key of the "View" group. All other [Colors:*] groups start
# from this table and override only the keys where they differ, so the dict order
# (alphabetical, as KDE writes it) is also the output key order for every group.
_VIEW = {
    "BackgroundAlternate": "surface_alt",
    "BackgroundNormal": "surface",
    "DecorationFocus": "accent",
    "DecorationHover": "accent",
    "ForegroundActive": "accent",
    "ForegroundInactive": "text_secondary",
    "ForegroundLink": "link",
    "ForegroundNegative": "error",
    "ForegroundNeutral": "warning",
    "ForegroundNormal": "text",
    "ForegroundPositive": "success",
    "ForegroundVisited": "link_visited",
}

# The five text keys that Tooltip and Selection each collapse onto ONE token
# (their background is a single fixed colour, so no other text colour is legible).
_TEXT_KEYS = (
    "ForegroundActive",
    "ForegroundInactive",
    "ForegroundLink",
    "ForegroundNormal",
    "ForegroundVisited",
)

# Window, Complementary and Header share one mapping: View with the window colour.
_WINDOW = {**_VIEW, "BackgroundNormal": "window"}

# [Colors:*] groups in output order (alphabetical, as KDE writes them).
_GROUPS = {
    "Button": {
        **_VIEW,
        "BackgroundAlternate": "surface",
        "BackgroundNormal": "surface_alt",
    },
    "Complementary": _WINDOW,
    "Header": _WINDOW,
    "Selection": {
        **_VIEW,
        "BackgroundAlternate": "accent",
        "BackgroundNormal": "accent",
        "DecorationFocus": "accent_text",
        "DecorationHover": "accent_text",
        **dict.fromkeys(_TEXT_KEYS, "accent_text"),
    },
    "Tooltip": {
        **_VIEW,
        "BackgroundAlternate": "tooltip_bg",
        "BackgroundNormal": "tooltip_bg",
        **dict.fromkeys(_TEXT_KEYS, "tooltip_text"),
    },
    "View": _VIEW,
    "Window": _WINDOW,
}

# [WM] key -> token, in output order.
_WM = (
    ("activeBackground", "window"),
    ("activeBlend", "text"),
    ("activeForeground", "text"),
    ("inactiveBackground", "window"),
    ("inactiveBlend", "text_secondary"),
    ("inactiveForeground", "text_secondary"),
)


def render(tokens: dict, mode: str = "light", name: str = "Theme") -> str:
    """
    Render the colour scheme for one mode.

    Args:
        tokens: Validated token dictionary (see design/validate.py).
        mode: "light" or "dark".
        name: Scheme name written to the [General] section.

    Returns:
        The complete ".colors" file content, exactly as specified above.

    Raises:
        ValueError: if mode is neither "light" nor "dark".
    """
    if mode not in ("light", "dark"):
        raise ValueError(f"mode must be 'light' or 'dark', got {mode!r}")
    palette = tokens["color"][mode]

    def rgb(token: str) -> str:
        """Return the palette colour called `token` as "R,G,B"."""
        return to_rgb_csv(palette[token])

    # Each section is (header, [(key, value), ...]); the literals below are the
    # fixed effect constants listed in the module docstring (not design values).
    sections = [
        (
            "ColorEffects:Disabled",
            [
                ("Color", rgb("text_disabled")),
                ("ColorAmount", "0"),
                ("ColorEffect", "0"),
                ("ContrastAmount", "0.65"),
                ("ContrastEffect", "1"),
                ("IntensityAmount", "0.1"),
                ("IntensityEffect", "2"),
            ],
        ),
        (
            "ColorEffects:Inactive",
            [
                ("ChangeSelectionColor", "true"),
                ("Color", rgb("text_secondary")),
                ("ColorAmount", "0.025"),
                ("ColorEffect", "2"),
                ("ContrastAmount", "0.1"),
                ("ContrastEffect", "2"),
                ("Enable", "false"),
                ("IntensityAmount", "0"),
                ("IntensityEffect", "0"),
            ],
        ),
    ]
    sections += [
        (f"Colors:{group}", [(key, rgb(token)) for key, token in mapping.items()])
        for group, mapping in _GROUPS.items()
    ]
    sections += [
        ("General", [("ColorScheme", name), ("Name", name)]),
        ("KDE", [("contrast", "4")]),
        ("WM", [(key, rgb(token)) for key, token in _WM]),
    ]

    # Blank line between sections, exactly one trailing newline (INI convention).
    blocks = (
        f"[{header}]\n" + "\n".join(f"{key}={value}" for key, value in pairs)
        for header, pairs in sections
    )
    return "\n\n".join(blocks) + "\n"
