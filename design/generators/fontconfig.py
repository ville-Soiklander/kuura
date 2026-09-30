"""
Generate a fontconfig alias file mapping "<Name> Sans" / "<Name> Mono" onto the
project's real UI/monospace font families.

This file is the LOCKED INTERFACE: implement the body of render() without changing
its signature. Only the standard library may be used. Never hard code "Inter" or
"JetBrains Mono" as literals here -- read them from tokens["type"]["family_ui"] /
tokens["type"]["family_mono"] (design/tokens.json's own source of truth, already
validated by design/validate.py's type.family_ui/family_mono: non-empty str rule),
the same "one place a token value is allowed to become a literal in someone else's
format" convention every generator in this package already follows for its own
section.

WHY this generator exists (Vaihe 5 of the working brief, "Omat assetit" - font
packaging): Inter and JetBrains Mono are already real runtime dependencies of the
distro (docs/ASSETS.md, packages/kuura-desktop's own `depends`, pulled in as the Arch
packages `inter-font` / `ttf-jetbrains-mono` - their font FILES are never vendored
into this repository). What is still missing is a friendly, distro-branded alias: an
application asking fontconfig for "<Name> Sans" (e.g. "Kuura Sans") should
transparently receive Inter, without every config file across the desktop needing to
spell out "Inter" by name. This is the standard, real fontconfig mechanism for exactly
that: a `<match>`-free `<alias>` block with a `<prefer>` clause (NOT `<default>` or
`<accept>` - `<prefer>` is fontconfig's own real semantic for "if this alias family is
requested, substitute this real family first", the correct one for a pure rename; the
other two elements mean something subtly different and are not what this generator
needs).

WHY name is a parameter here (unlike design/generators/plasma_colors.py's own
render(tokens, mode, name), this generator has no `mode` - font aliasing is not a
light/dark-dependent concept, the same reasoning design/generators/cpp_header.py's own
docstring gives for skipping `mode` entirely): the alias family name itself
("<Name> Sans") is branded per distro, so `name` (the same value design/generate.py's
own CLI already threads through to every mode-dependent generator, sourced from
DISTRO_NAME) must reach this generator too, even though nothing else about its output
varies per invocation the way colour generators vary per mode.

EXACT OUTPUT (single trailing newline, matching every other generator's own
convention in this package). Angle brackets mark placeholders, not written verbatim;
`<Name>` is `name.capitalize()` (`design/generate.py`'s own CLI already validates name
against `[a-z0-9_-]+`, so this is always exactly one leading uppercase letter followed
by the rest of the string unchanged - "kuura" -> "Kuura", never requiring any further
normalisation):

    <?xml version="1.0"?>
    <!DOCTYPE fontconfig SYSTEM "fonts.dtd">
    <fontconfig>
      <alias>
        <family><Name> Sans</family>
        <prefer><family><family_ui></family></prefer>
      </alias>
      <alias>
        <family><Name> Mono</family>
        <prefer><family><family_mono></family></prefer>
      </alias>
    </fontconfig>

Args:
    tokens: Validated token dictionary (design/validate.py's load_tokens()); only
        tokens["type"]["family_ui"] and tokens["type"]["family_mono"] are read.
    name: The distro name (design/generate.py's own CLI already validates this
        against `[a-z0-9_-]+` before any generator sees it - see that module's own
        main(), not re-validated here).

Returns:
    The complete fontconfig XML document as a single string, exactly as shown above
    (2-space indentation, matching the layout shown - this is a real, standard
    fontconfig file format, not this project's own invention, so match it exactly
    rather than reformatting it to this project's own taste).
"""

from __future__ import annotations


def render(tokens: dict, name: str) -> str:
    """See this module's own docstring (EXACT OUTPUT) for the exact spec."""
    # WHY name.capitalize(): design/generate.py's CLI already validates `name`
    # against [a-z0-9_-]+ before any generator sees it, so this always yields
    # exactly one leading uppercase letter followed by the rest unchanged
    # ("kuura" -> "Kuura") - no further normalisation is needed here.
    display_name = name.capitalize()

    # WHY read from tokens instead of hard coding "Inter"/"JetBrains Mono": these
    # are the project's real UI/monospace fonts (design/tokens.json's own source
    # of truth, already validated by design/validate.py), and every generator in
    # this package keeps token values out of its own literals for exactly this
    # reason - so a tokens.json change propagates here without editing this file.
    family_ui = tokens["type"]["family_ui"]
    family_mono = tokens["type"]["family_mono"]

    lines = [
        '<?xml version="1.0"?>',
        '<!DOCTYPE fontconfig SYSTEM "fonts.dtd">',
        "<fontconfig>",
        "  <alias>",
        f"    <family>{display_name} Sans</family>",
        f"    <prefer><family>{family_ui}</family></prefer>",
        "  </alias>",
        "  <alias>",
        f"    <family>{display_name} Mono</family>",
        f"    <prefer><family>{family_mono}</family></prefer>",
        "  </alias>",
        "</fontconfig>",
    ]
    return "\n".join(lines) + "\n"
