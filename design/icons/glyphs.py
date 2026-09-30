"""
Manifest of the icon set's per-icon glyph content (Vaihe 5, "Omat assetit").

WHY a plain dict, not a class hierarchy: `design.generate_icons` only ever needs
"icon_id -> glyph SVG fragment", and every fragment is handed unchanged to
`design.generators.icon_svg.render_icon()`, which wraps it with the ONE shared
squircle frame/gradient/glass-edge (see that module's own docstring for why the
frame itself must never be duplicated here) - a dict is the simplest structure
that expresses that mapping and nothing more.

WHY every glyph is drawn by hand at fixed pixel coordinates, not generated from a
formula the way the squircle frame is: the frame is what "yhtenainen ristikko"
(one unified grid) means and MUST be identical, reproducible geometry across every
icon - the glyph on top of it is deliberately the opposite, one small hand-drawn
composition per icon, same as any other icon theme's per-glyph artwork (e.g.
Papirus ships one hand-authored SVG per icon on top of a shared base grid).

ORIGINALITY / ANTI-COPYING (this project's own load-bearing rule, restated here
because this file is the one place actual glyph geometry is authored): every
shape below is this project's own simple geometric composition - rectangles,
circles, lines and short polylines only, no traced or measured outline from any
other real desktop OS's own icon artwork. The gear for "settings" is drawn as a
plain ring plus radial teeth, the ordinary generic geometric form of a gear/cog
used by countless icon sets (KDE's own Breeze theme, Font Awesome, Material
Symbols, etc.) - it is not modelled on any single vendor's specific gear
artwork.

CANVAS CONTRACT: every glyph below is authored directly in `icon_svg.py`'s
512x512 canvas coordinate space and stays clear of its 32px INSET margin on every
side (i.e. roughly within the 64..448 range, well inside the 32..480 squircle
bounding box) - `render_icon()` inserts this content verbatim, it does not clip
or rescale it (see icon_svg.py's own docstring, point 5).

STYLE CONTRACT: every glyph uses plain white (`#FFFFFF`) fills/strokes only - the
icon set has no light/dark variant (see icon_svg.py's own docstring for why), so
the glyph colour is fixed and relies on contrast against the icon's own
gradient background (design/tokens.json's icon.gradient.top/bottom) rather than
against the desktop's colour scheme.

ICON SELECTION (this module's own judgement call, flagged for the orchestrator):
the working brief's priority list names "a small representative set of file-type
icons" without naming the exact four; "document", "image", "archive" and "code"
were picked here as the four most common file categories a desktop file manager
distinguishes at a glance. Swap or extend this set freely - each is an independent
dict entry with no cross-dependency on the others.
"""

from __future__ import annotations

# WHY a helper instead of 8 hand-written <rect transform="rotate(...)"> lines:
# the teeth are one shape repeated at 8 evenly spaced angles around the same
# centre - computing the repetition once removes the chance of a copy-pasted
# tooth silently drifting from the other seven (the same "don't hand-copy a
# derivable value" reasoning this package's token generators already follow,
# just applied to a glyph's own geometry instead of a token value).
def _gear_teeth(cx: float, cy: float, tooth_count: int, width: float, y_top: float, y_bottom: float) -> str:
    """
    Build `tooth_count` identical rectangular teeth, evenly spaced by rotation.

    Args:
        cx, cy: Centre of the gear (and of every teeth's rotation).
        tooth_count: How many teeth to place around the circle.
        width: Tooth width (the rect's own width, centred on top of the circle).
        y_top: Y coordinate of the tooth's outer (far from centre) edge.
        y_bottom: Y coordinate of the tooth's inner (near centre) edge.

    Returns:
        One `<rect .../>` element per tooth, each rotated by its own share of
        360 degrees around (cx, cy), joined with newlines.
    """
    x = cx - width / 2
    height = y_bottom - y_top
    step = 360 / tooth_count
    return "\n".join(
        f'<rect x="{x:.0f}" y="{y_top:.0f}" width="{width:.0f}" height="{height:.0f}" '
        f'transform="rotate({i * step:.0f} {cx:.0f} {cy:.0f})" fill="#FFFFFF"/>'
        for i in range(tooth_count)
    )


def _settings_glyph() -> str:
    """
    A gear: a stroked ring (its own hollow centre reveals the background gradient
    -- no separate "hole" shape is needed) plus 8 radial teeth. An ordinary,
    vendor-neutral gear silhouette, not modelled on any specific OS's artwork.
    """
    ring = '<circle cx="256" cy="256" r="88" fill="none" stroke="#FFFFFF" stroke-width="32"/>'
    teeth = _gear_teeth(cx=256, cy=256, tooth_count=8, width=32, y_top=112, y_bottom=152)
    return f"<g>\n{ring}\n{teeth}\n</g>"


ICONS: dict[str, str] = {
    # File manager: a browser-style window (frame + sidebar divider + a small
    # grid of "file tile" rectangles), distinct from the plain folder glyph below.
    "file_manager": (
        "<g>\n"
        '<rect x="88" y="128" width="336" height="256" rx="24" fill="none" stroke="#FFFFFF" stroke-width="16"/>\n'
        '<line x1="180" y1="128" x2="180" y2="384" stroke="#FFFFFF" stroke-width="16"/>\n'
        '<circle cx="132" cy="176" r="14" fill="#FFFFFF"/>\n'
        '<rect x="224" y="160" width="136" height="48" rx="10" fill="#FFFFFF"/>\n'
        '<rect x="224" y="224" width="136" height="48" rx="10" fill="#FFFFFF"/>\n'
        '<rect x="224" y="288" width="88" height="48" rx="10" fill="#FFFFFF"/>\n'
        "</g>"
    ),
    # Settings: the gear built by _settings_glyph() above.
    "settings": _settings_glyph(),
    # Terminal: a window outline with a ">" prompt chevron and an underscore
    # cursor -- exactly the ">_" composition the working brief itself suggests.
    "terminal": (
        "<g>\n"
        '<rect x="104" y="152" width="304" height="208" rx="24" fill="none" stroke="#FFFFFF" stroke-width="16"/>\n'
        '<path d="M 176,208 L 224,256 L 176,304" fill="none" stroke="#FFFFFF" stroke-width="22" '
        'stroke-linecap="round" stroke-linejoin="round"/>\n'
        '<rect x="248" y="296" width="56" height="20" rx="4" fill="#FFFFFF"/>\n'
        "</g>"
    ),
    # Browser: a globe (outer circle, one vertical meridian ellipse, one
    # horizontal equator line) -- the generic, vendor-neutral globe symbol.
    "browser": (
        "<g>\n"
        '<circle cx="256" cy="256" r="144" fill="none" stroke="#FFFFFF" stroke-width="18"/>\n'
        '<ellipse cx="256" cy="256" rx="56" ry="144" fill="none" stroke="#FFFFFF" stroke-width="14"/>\n'
        '<line x1="112" y1="256" x2="400" y2="256" stroke="#FFFFFF" stroke-width="14"/>\n'
        "</g>"
    ),
    # File type: document/text -- a page with a folded top-right corner and
    # three text lines of decreasing width.
    "file_document": (
        "<g>\n"
        '<path d="M 176,112 L 336,112 L 400,176 L 400,400 L 176,400 Z" fill="none" stroke="#FFFFFF" '
        'stroke-width="14" stroke-linejoin="round"/>\n'
        '<path d="M 336,112 L 336,176 L 400,176" fill="none" stroke="#FFFFFF" stroke-width="14" '
        'stroke-linejoin="round" stroke-linecap="round"/>\n'
        '<rect x="208" y="232" width="160" height="16" rx="8" fill="#FFFFFF"/>\n'
        '<rect x="208" y="268" width="120" height="16" rx="8" fill="#FFFFFF"/>\n'
        '<rect x="208" y="304" width="140" height="16" rx="8" fill="#FFFFFF"/>\n'
        "</g>"
    ),
    # File type: image -- a picture frame with a small sun disc and a simple
    # mountain-range silhouette, the classic generic "picture" pictogram.
    "file_image": (
        "<g>\n"
        '<rect x="160" y="144" width="272" height="224" rx="16" fill="none" stroke="#FFFFFF" stroke-width="16"/>\n'
        '<circle cx="232" cy="208" r="24" fill="#FFFFFF"/>\n'
        '<path d="M 176,344 L 248,272 L 296,312 L 344,256 L 400,344 Z" fill="#FFFFFF"/>\n'
        "</g>"
    ),
    # File type: archive -- a box with a dashed vertical "zip" line and a small
    # pull tab, the classic generic archive/zip pictogram.
    "file_archive": (
        "<g>\n"
        '<rect x="176" y="128" width="224" height="256" rx="16" fill="none" stroke="#FFFFFF" stroke-width="16"/>\n'
        '<line x1="288" y1="128" x2="288" y2="384" stroke="#FFFFFF" stroke-width="10" stroke-dasharray="24 16"/>\n'
        '<rect x="272" y="104" width="32" height="32" rx="6" fill="#FFFFFF"/>\n'
        "</g>"
    ),
    # File type: code/source -- a document outline with an "<>" angle-bracket
    # glyph, the generic, vendor-neutral "this is code" pictogram.
    "file_code": (
        "<g>\n"
        '<rect x="176" y="128" width="224" height="256" rx="20" fill="none" stroke="#FFFFFF" stroke-width="16"/>\n'
        '<path d="M 248,220 L 212,256 L 248,292" fill="none" stroke="#FFFFFF" stroke-width="16" '
        'stroke-linecap="round" stroke-linejoin="round"/>\n'
        '<path d="M 264,220 L 300,256 L 264,292" fill="none" stroke="#FFFFFF" stroke-width="16" '
        'stroke-linecap="round" stroke-linejoin="round"/>\n'
        "</g>"
    ),
    # Systray: a plain ring + filled dot, deliberately generic/simple so the SAME
    # glyph is reusable across small status icons (the working brief's own
    # requirement) rather than depicting one specific status.
    "systray": (
        "<g>\n"
        '<circle cx="256" cy="256" r="100" fill="none" stroke="#FFFFFF" stroke-width="16"/>\n'
        '<circle cx="256" cy="256" r="44" fill="#FFFFFF"/>\n'
        "</g>"
    ),
    # Folder: a small rounded tab sitting on a larger rounded body -- the
    # ordinary, vendor-neutral two-rectangle folder silhouette.
    "folder": (
        "<g>\n"
        '<rect x="144" y="152" width="96" height="40" rx="12" fill="#FFFFFF"/>\n'
        '<rect x="104" y="176" width="304" height="192" rx="20" fill="#FFFFFF"/>\n'
        "</g>"
    ),
}
