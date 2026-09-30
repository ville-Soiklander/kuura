"""
Generate a C++ header ("kuura_tokens.h") exposing every non-colour design token as a
`constexpr` constant.

This file is the LOCKED INTERFACE: implement the body of render() without changing its
signature. Only the standard library may be used; never hard code a token value anywhere
else (this generator is the ONE place tokens.json's numeric/string values are allowed to
turn into C++ literals). Tokens has no light/dark variant here, so there is only one
output, not one per mode -- the SAME mode-independent shape design/generators/
plasma_layout.py's render() uses (tokens: dict) -> str, not the 4 mode-dependent
generators' (tokens, mode, name) -> str shape.

WHY this generator exists (Vaihe 4 of the working brief, packages/kuura-frost): Frost's
real material shader (src/frost.cpp's loadShaders()/apply()) needs the SAME
material.refraction.strength / material.refraction.edge_falloff /
material.edge_highlight.width / material.edge_highlight.opacity / material.noise numbers
already in design/tokens.json, as real per-frame GLSL uniform VALUES set from C++ -- but
frost.h's own class docstring explicitly forbids hand-copying those numbers as a second,
independent set of literals baked into the shader source or into frost.cpp directly
(that copy would silently drift the moment tokens.json changes, exactly the failure mode
every other generator in this package already avoids). This module is the missing link:
a real, compiled C++ header, generated from tokens.json at PACKAGE-BUILD TIME (never at
first login, same rule as design/generators/plasma_layout.py's own appletsrc), that
packages/kuura-frost's CMakeLists.txt adds to its include path so frost.cpp can
`#include "kuura_tokens.h"` and read e.g. `Kuura::Tokens::kMaterialRefractionStrength`
as an ordinary compile-time constant.

WHY every non-colour leaf, not just the five material.* values Frost happens to need
today: this generator is general design-system infrastructure (like qml_singleton.py,
which also exports every leaf), not a Frost-specific script -- a future C++ package
wanting, say, spacing.grid or motion.duration.fast as a real constant should not need a
second, parallel generator invented for it. `color.*` is the one section left out
(module docstring's own convention, mirroring qml_singleton.py's `_collect_leaves`
skip-list): colour tokens are mode-dependent (light/dark), and this generator's locked
signature takes no `mode` argument at all -- there is no single "the" colour for a
mode-independent header to export. `_meta` is metadata, not a design value, and is
skipped for the same reason qml_singleton.py skips it.

Exact output (single trailing newline). Angle brackets mark placeholders, not written:

    #pragma once

    // Design tokens - generated from design/tokens.json, do not edit by hand.
    // Numeric/string values only: colour tokens are mode-dependent and are not
    // exported here (see design/generators/qml_singleton.py for those).
    namespace Kuura::Tokens
    {
    inline constexpr <type> <constName> = <value>;
    ...one such line per leaf, sorted ascending by constName...
    } // namespace Kuura::Tokens

Properties:
- One constant per leaf of `tokens` EXCEPT the top-level keys "_meta" and "color"
  (recursing into every other nested dict exactly like qml_singleton.py's
  `_collect_leaves`). The constant name is "k" followed by the dotted key path with
  "_"/"-" treated as an extra path separator, each resulting segment capitalised and
  concatenated (PascalCase, unlike qml_singleton.py's camelCase, because a lowercase-
  leading identifier reads as a local/member variable in C++, not a constant): e.g.
  material.refraction.strength -> kMaterialRefractionStrength,
  panel.shelf_icon -> kPanelShelfIcon, radius.icon -> kRadiusIcon.
- Type and value by Python type, matching qml_singleton.py's own mapping except for the
  C++ spelling: bool -> `bool` (checked before int, since bool is an int subclass in
  Python), printed "true"/"false"; int -> `int`, printed with str(); float -> `float`,
  printed with repr() plus a trailing `f` (C++ would otherwise parse an unsuffixed
  float literal as `double`, e.g. 0.035 -> "0.035f", 1.0 -> "1.0f"); str -> `const char
  *const`, printed in double quotes with backslash and double quote escaped by a
  backslash (same escaping rule as qml_singleton.py).
- Sorting is by the full constName with Python's default string ordering (so
  "kMaterialBlurRadius" < "kMaterialNoise" < "kPanelMenubarHeight" < "kSpacingGrid").
- Tokens not used: "_meta", every leaf under "color" (mode-dependent, see above).
"""

from __future__ import annotations

# Leaf collection intentionally mirrors design/generators/qml_singleton.py's own
# _collect_leaves rather than importing it: that function is a private (leading
# underscore) implementation detail of a different generator module, not a shared
# public helper, and this file's own docstring/locked interface promises "only the
# standard library" the same way plasma_layout.py's does.


def _to_pascal_case(path: str) -> str:
    """
    Convert a dotted/underscore/hyphen-separated token path to PascalCase.

    Args:
        path: A string like "material.refraction.strength" or "panel.shelf_icon".

    Returns:
        PascalCase string with every segment capitalised, e.g.
        "material.refraction.strength" -> "MaterialRefractionStrength".
    """
    # WHY normalize "_"/"-" to "." first: a token path can mix a dict-nesting
    # separator (".") with a snake_case key ("shelf_icon") - both must become
    # segment boundaries for the constant name, exactly like qml_singleton.py's
    # own _to_camel_case does for its camelCase names.
    normalized = path.replace("_", ".").replace("-", ".")
    return "".join(part.capitalize() for part in normalized.split("."))


def _python_to_cpp(value: object) -> tuple[str, str]:
    """
    Convert a Python leaf value to a C++ type and literal.

    Args:
        value: A leaf value from tokens.json (bool, int, float or str - tokens.json
            never contains any other JSON leaf type).

    Returns:
        A tuple (cpp_type, literal) such as ("float", "0.035f").
    """
    if isinstance(value, bool):
        # WHY checked first: bool is a subclass of int in Python, so an int check
        # alone would misclassify True/False as int constants.
        return "bool", "true" if value else "false"
    if isinstance(value, int):
        return "int", str(value)
    if isinstance(value, float):
        # WHY repr() + "f": repr() preserves precision (1.0 stays "1.0", not "1"),
        # and C++ parses an unsuffixed decimal literal as `double` - "f" keeps the
        # constant's declared `float` type and its literal in agreement.
        return "float", f"{value!r}f"
    # str is the only remaining tokens.json leaf type (see this module's own
    # docstring: bool/int/float/str only).
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return "const char *const", f'"{escaped}"'


def _collect_leaves(tokens: dict) -> dict[str, object]:
    """
    Walk `tokens`, skipping "_meta" and "color", and collect every leaf value.

    Args:
        tokens: Validated token dictionary (see design/validate.py).

    Returns:
        A dict of {dotted.path: leaf_value}, one entry per non-dict value found
        anywhere under a top-level key other than "_meta"/"color".
    """
    leaves: dict[str, object] = {}

    def _walk(obj: dict, path: str) -> None:
        for key, value in obj.items():
            if not path and key in ("_meta", "color"):
                continue
            new_path = f"{path}.{key}" if path else key
            if isinstance(value, dict):
                _walk(value, new_path)
            else:
                leaves[new_path] = value

    _walk(tokens, "")
    return leaves


def render(tokens: dict) -> str:
    """
    Render a complete, ready-to-compile C++ header of `constexpr` token constants.

    Args:
        tokens: Validated token dictionary (see design/validate.py). Every leaf under
            a top-level key other than "_meta"/"color" becomes one constant; see this
            module's own docstring for the exact naming/type/output rules.

    Returns:
        The complete header content, exactly as specified in this module's docstring.
    """
    leaves = _collect_leaves(tokens)

    # constName -> (cpp_type, literal), built before sorting so the sort key is the
    # real emitted constant name, not the dotted tokens.json path.
    constants: dict[str, tuple[str, str]] = {}
    for path, value in leaves.items():
        const_name = "k" + _to_pascal_case(path)
        constants[const_name] = _python_to_cpp(value)

    lines: list[str] = []
    lines.append("#pragma once")
    lines.append("")
    lines.append("// Design tokens - generated from design/tokens.json, do not edit by hand.")
    lines.append("// Numeric/string values only: colour tokens are mode-dependent and are not")
    lines.append("// exported here (see design/generators/qml_singleton.py for those).")
    lines.append("namespace Kuura::Tokens")
    lines.append("{")
    for const_name in sorted(constants.keys()):
        cpp_type, literal = constants[const_name]
        lines.append(f"inline constexpr {cpp_type} {const_name} = {literal};")
    lines.append("} // namespace Kuura::Tokens")

    return "\n".join(lines) + "\n"
