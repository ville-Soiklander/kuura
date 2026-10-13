"""
Generate the Calamares installer's branding.desc (YAML) from the design tokens.

This file is the LOCKED INTERFACE: implement the body of render() without
changing its signature. Only the standard library may be used. Never hand
write a token colour value anywhere else in this project's Calamares config --
this generator is the one place design/tokens.json's colour values are
allowed to become Calamares `style:` literals, the same rule every other
generator in this package already follows for its own target format.

WHY this generator exists (Vaihe 7 of the working brief, packages/
kuura-installer-config -- see docs/ISO_CONTRACT.md's "Calamares
configuration" section for the full, already-locked product decisions this
module implements): Calamares' own real branding mechanism (confirmed from
its real `src/branding/README.md` and `src/branding/default/branding.desc`,
fetched from https://codeberg.org/Calamares/calamares at the pinned tag
v3.4.2, not guessed) is a YAML descriptor, `branding.desc`, inside a named
directory under `/etc/calamares/branding/<componentName>/` -- and
`componentName` must equal that directory's own name exactly, or Calamares
refuses to start (confirmed from `src/libcalamaresui/Branding.cpp`'s
constructor: `if (m_componentName != componentDir.dirName()) { bail(...); }`).
This module renders that descriptor's content from real token values, the
same "generate at package-build time, never hand-author the branded file"
rule every other generator in this package already follows (compare
fontconfig.py's alias file or gtk_css.py's stylesheet).

WHY no `mode` parameter (mirrors fontconfig.py's own `render(tokens, name)`
shape, not the 4 mode-dependent generators' `render(tokens, mode, name)`
shape): Calamares' installer UI has no light/dark toggle of its own to
switch with -- it runs once, during install, with no desktop session or
user-configurable appearance setting behind it (confirmed: the real
branding.desc schema above has exactly ONE `style:` section, not a pair).
`name` IS still a parameter, for the same reason fontconfig.py's own
docstring gives: the branded strings and the installed component's own
directory name are per-distro, even though nothing else here varies per
invocation the way a colour generator varies per mode.

WHY the dark palette specifically for `style:` (tokens.json has no
"calamares"/"installer" section of its own -- color.dark/color.light are the
only palettes that exist, and this generator picks one, deliberately): the
real upstream `default` branding sample ships a FIXED dark sidebar
(`SidebarBackground: "#292F34"`, white text) regardless of whatever the
installed system's own eventual light/dark choice will be -- this is
Calamares' own sidebar-chrome convention, not an OS appearance toggle
(common across real installers: Calamares, Ubiquity and Anaconda all use a
fixed dark navigation sidebar). `color.dark.window`/`color.dark.text`
reproduce that same fixed-dark-chrome look from this project's own real
tokens rather than a hand-picked literal.

WHY `color.dark.window`/`color.dark.accent`/`color.dark.accent_text` are the
exact four tokens picked (not `surface_alt`, not the light palette): this
project's own design/generators/plasma_colors.py already establishes the
convention that a fixed, header-like chrome panel (its `[Colors:Header]`/
`[Colors:Complementary]` groups, both defined as `_WINDOW = {**_VIEW,
"BackgroundNormal": "window"}`) uses the `window` token for its normal
background, not `surface_alt` -- see that module's own docstring, the
Window/Complementary/Header column. Calamares' sidebar is architecturally
the same kind of thing, a fixed navigational chrome panel, so this generator
reuses the identical token for the identical role instead of inventing a new
mapping. The "current step" highlight (`SidebarBackgroundCurrent`/
`SidebarTextCurrent`) is exactly the same concept as plasma_colors.py's own
`[Colors:Selection]` group (`BackgroundNormal: accent`, every foreground key
collapsed onto `accent_text`) -- the currently active item gets an accent
background with its own pre-paired, guaranteed-legible foreground token, so
this generator reuses that exact pairing rather than guessing a contrasting
colour of its own.

WHY `productIcon`/`productLogo` reuse the systray glyph as an SVG, and
`productWelcome` reuses one specific existing wallpaper PNG (docs/
ISO_CONTRACT.md's own locked decision -- "no new artwork, no slideshow"):
this project's own icon set (design/icons/glyphs.py, rendered by
design/generators/icon_svg.py exactly like packages/kuura-assets already
does) has no dedicated wordmark/logo glyph, and the systray glyph (a plain
ring + dot) is the closest existing asset to a square, generic brand mark.
SVG is a real, confirmed-supported format for these three image keys, not a
guess: `src/libcalamaresui/utils/ImageRegistry.cpp` explicitly branches on
`image.toLower().endsWith(".svg")` and renders it with `QSvgRenderer` at
whatever pixel size is requested -- and Calamares' own real `depends` array
already includes `qt6-svg` for exactly this (see packages/calamares/
PKGBUILD, vendored from the same real AUR/upstream source). `productWelcome`
picks "<name>-vertical-dawn-light.png", ONE specific, fixed
composition/mode pair out of design/generate_wallpapers.py's own 5
compositions x 2 modes = 10 files (see that module's own docstring for the
full list) -- "vertical-dawn" is its simplest, plainest two-stop gradient
(fitting for a first-impression welcome image), "light" because the welcome
page's own default styling (a white main content area) reads better against
a bright image than a dark one. This is a fixed, deliberate choice made
HERE, not derived from any token -- the PKGBUILD that calls this generator
must stage files under the EXACT names this function emits (see
packages/kuura-installer-config/PKGBUILD's own build()/package(), which
separately runs design.generate_icons/design.generate_wallpapers for exactly
this reason, and installs both images flat, alongside branding.desc, inside
the same component directory -- confirmed from Branding.cpp's own image
loader, which resolves a bare filename with `componentDir.absoluteFilePath
(imageName)`, i.e. relative to branding.desc's own directory, not a
subdirectory).

REVISED 2026-10-08 (real live-boot testing, not just reading docs, caught a
real research error): `slideshow:` is emitted as an EMPTY sequence,
`slideshow: []` -- NOT omitted. The original research (branding.desc's own
documentation text) said this key was optional; that was wrong. Calamares
3.4.2's real `Branding.cpp` (`src/libcalamaresui/Branding.cpp`, confirmed by
reading the pinned tag v3.4.2 source directly) retrieves this key with a
`get()` helper that throws `YAML::KeyNotFound` -- a fatal `bail()` -- if the
key is missing at all, with no fallback. This was only discovered because
launching Calamares on a real booted ISO (the first time this project ever
did so) failed immediately with `FATAL in ".../branding.desc": key not
found: slideshow`, contradicting the earlier, docs-only research. Re-reading
the same real source confirmed the fix: when `slideshow` IS present and is a
YAML sequence, the code loops over its items with no validation that the
count is nonzero (`for (int i = 0; i < slideShowPictures.count(); ++i)` --
zero iterations for an empty list is accepted silently, no bail()). An empty
sequence therefore satisfies Calamares' real hard requirement while still
meaning exactly "no slideshow," honouring docs/ISO_CONTRACT.md's own locked
decision ("no new artwork, no slideshow") precisely -- only the YAML
*mechanism* for expressing that was wrong, not the decision itself, so this
did not need to go back to the project owner as a new choice. (The
scalar/QML-path alternative `Branding.cpp` also supports was not used: it
requires a real, existing .qml file, which is exactly the "new artwork/new
scope" the locked decision already ruled out.)

Exact output (single trailing newline, matching every other generator's own
convention in this package). Angle brackets mark placeholders, not written
verbatim; `<Name>` is `name.capitalize()` (the same "already validated
[a-z0-9_-]+ by design/generate.py's own CLI" assumption fontconfig.py's
docstring makes, so this is always exactly one leading uppercase letter
followed by the rest unchanged):

    # Calamares branding - generated from design/tokens.json, do not edit.
    componentName: <name>
    welcomeStyleCalamares: true
    welcomeExpandingLogo: true
    strings:
      productName: "<Name>"
      shortProductName: "<Name>"
      version: "0.1.0"
      versionedName: "<Name> 0.1.0"
    images:
      productIcon: "systray.svg"
      productLogo: "systray.svg"
      productWelcome: "<name>-vertical-dawn-light.png"
    style:
      SidebarBackground: "<color.dark.window>"
      SidebarText: "<color.dark.text>"
      SidebarBackgroundCurrent: "<color.dark.accent>"
      SidebarTextCurrent: "<color.dark.accent_text>"
    slideshow: []

Args:
    tokens: Validated token dictionary (design/validate.py's load_tokens());
        only tokens["color"]["dark"]["window"/"text"/"accent"/"accent_text"]
        are read (see this module's own docstring for why the dark palette
        and these four specific keys).
    name: The distro name (design/generate.py's own CLI already validates
        this against `[a-z0-9_-]+` before any generator sees it -- see that
        module's own main(), not re-validated here, matching fontconfig.py's
        own precedent).

Returns:
    The complete branding.desc YAML content as a single string, exactly as
    shown above.
"""

from __future__ import annotations

# Fixed, deliberate choices -- see this module's own docstring ("WHY
# productIcon/productLogo .../productWelcome ...") for why these are
# literals here rather than derived from a token. A PKGBUILD consuming this
# generator's output must stage files under these EXACT names (see
# packages/kuura-installer-config/PKGBUILD).
_PRODUCT_ICON_FILE = "systray.svg"
_WALLPAPER_COMPOSITION = "vertical-dawn"
_WALLPAPER_MODE = "light"

# Project-wide product version literal. No dedicated project-version file
# exists: docs/VERSIONS.md only records pinned UPSTREAM dependency versions
# (plasma-desktop, kwin, ...), never kuura's own, and .env.example has no
# version variable either. Every first-party PKGBUILD in this monorepo
# already hardcodes its own pkgver=0.1.0 the same way (packages/kuura-shell,
# packages/kuura-assets), so this mirrors that existing convention rather
# than inventing a new one or guessing a "real" version that does not exist.
_VERSION = "0.1.0"


def render(tokens: dict, name: str) -> str:
    """See this module's own docstring (EXACT OUTPUT) for the exact spec."""
    # WHY name.capitalize(): design/generate.py's CLI already validates `name`
    # against [a-z0-9_-]+ before any generator sees it, so this always yields
    # exactly one leading uppercase letter followed by the rest unchanged
    # ("kuura" -> "Kuura") - same reasoning as fontconfig.py's own render().
    display_name = name.capitalize()

    # WHY read color.dark.* instead of color.light.*: see this module's own
    # docstring, "WHY the dark palette specifically for style:" - Calamares'
    # sidebar is a fixed chrome element, not an OS light/dark toggle.
    dark = tokens["color"]["dark"]

    wallpaper_file = f"{name}-{_WALLPAPER_COMPOSITION}-{_WALLPAPER_MODE}.png"

    lines = [
        "# Calamares branding - generated from design/tokens.json, do not edit.",
        f"componentName: {name}",
        "welcomeStyleCalamares: true",
        "welcomeExpandingLogo: true",
        "strings:",
        f'  productName: "{display_name}"',
        f'  shortProductName: "{display_name}"',
        f'  version: "{_VERSION}"',
        f'  versionedName: "{display_name} {_VERSION}"',
        "images:",
        f'  productIcon: "{_PRODUCT_ICON_FILE}"',
        f'  productLogo: "{_PRODUCT_ICON_FILE}"',
        f'  productWelcome: "{wallpaper_file}"',
        "style:",
        f'  SidebarBackground: "{dark["window"]}"',
        f'  SidebarText: "{dark["text"]}"',
        f'  SidebarBackgroundCurrent: "{dark["accent"]}"',
        f'  SidebarTextCurrent: "{dark["accent_text"]}"',
        "slideshow: []",
    ]
    return "\n".join(lines) + "\n"
