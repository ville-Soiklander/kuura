"""
Generate a QML singleton ("Tokens.qml") with every design token as a property.

This file is the LOCKED INTERFACE: implement the body of render() without
changing its signature or the exact output below. Only the standard library and
`.colors` may be used; never parse hex here. Colour notation: `to_qml`.

Exact output (single trailing newline). Angle brackets in this template mark placeholders and are not written.

pragma Singleton
import QtQuick

// {name} {mode} - generated from design tokens, do not edit.
QtObject {
    readonly property <type> <propertyName>: <value>
    ...one such line per property, sorted ascending by propertyName...
}

Properties (each line is indented by exactly 4 spaces):
1. `mode`: type `string`, value "{mode}".
2. One property per leaf of `tokens` EXCEPT the top-level keys "_meta" and
   "color". The propertyName is the dotted key path camel-cased: split the
   path on "." and "_", lowercase the first part, capitalise the first letter of
   every following part. Example: material.bg_opacity.panel -> materialBgOpacityPanel,
   panel.shelf_icon -> panelShelfIcon.
   Type and value by Python type: int -> `int`, printed with str(); float ->
   `real`, printed with repr() (1.0 stays "1.0"); str -> `string`, printed in
   double quotes with backslash and double quote escaped by a backslash.
3. One property per key of tokens["color"][mode]: propertyName is "color" +
   the key camel-cased with the same rule and first letter capitalised
   (accent -> colorAccent, text_secondary -> colorTextSecondary); type `color`;
   value in double quotes, `to_qml(value)`.
4. One extra property for the easing string: `motionEasingStandardCurve`, type
   `var`, value the four numbers of tokens["motion"]["easing_standard"]
   ("cubic-bezier(0.32, 0.72, 0, 1)") followed by 1 and 1, written as they appear
   in the string, as a QML array: `[0.32, 0.72, 0, 1, 1, 1]`.

Sorting is by the full propertyName with Python's default string ordering
(so "colorAccent" < "materialBlurRadius" < "mode" < "motionDuration..." ).
Tokens not used: none (every non-colour leaf is exported).
"""

from __future__ import annotations

import re

from .colors import to_qml


def render(tokens: dict, mode: str = "light", name: str = "Theme") -> str:
    """
    Render the QML singleton for one mode.

    Args:
        tokens: Validated token dictionary (see design/validate.py).
        mode: "light" or "dark".
        name: Theme name used in the header comment.

    Returns:
        The complete QML file content, exactly as specified above.

    Raises:
        ValueError: if mode is neither "light" nor "dark".
    """
    if mode not in ("light", "dark"):
        raise ValueError("mode must be 'light' or 'dark'")

    lines = []

    # QML header
    lines.append("pragma Singleton")
    lines.append("import QtQuick")
    lines.append("")
    lines.append(f"// {name} {mode} - generated from design tokens, do not edit.")
    lines.append("QtObject {")

    # Collect all properties as {name: (type, value)} dict
    properties = {}

    # Add mode property
    properties["mode"] = ("string", f'"{mode}"')

    # Recursively collect leaves from tokens, skipping _meta and color
    def _collect_leaves(obj: dict, path: str = "") -> None:
        """Recursively walk dict and collect leaf (non-dict) values."""
        for key, value in obj.items():
            # Skip top-level _meta and color keys
            if (not path) and key in ("_meta", "color"):
                continue

            new_path = f"{path}.{key}" if path else key

            if isinstance(value, dict):
                # Recurse into nested dicts
                _collect_leaves(value, new_path)
            else:
                # This is a leaf - add to properties
                prop_name = _to_camel_case(new_path)
                qml_type, qml_value = _python_to_qml(value)
                properties[prop_name] = (qml_type, qml_value)

    _collect_leaves(tokens)

    # Add color properties from tokens["color"][mode]
    color_tokens = tokens["color"][mode]
    for key in sorted(color_tokens.keys()):
        value = color_tokens[key]
        # Camel-case the key, then capitalize first letter, then prepend "color"
        key_camel = _to_camel_case(key)
        # Capitalize first letter: "accent" -> "Accent", "textSecondary" -> "TextSecondary"
        key_camel_cap = key_camel[0].upper() + key_camel[1:] if key_camel else ""
        prop_name = "color" + key_camel_cap
        properties[prop_name] = ("color", f'"{to_qml(value)}"')

    # Add motion easing array from tokens["motion"]["easing_standard"]
    easing_str = tokens["motion"]["easing_standard"]
    # WHY: Extract numbers preserving minus signs for negative bezier values (e.g. "cubic-bezier(0.3, -0.2, 0.5, 1.2)")
    # Pattern captures optional minus, optional digits before decimal, optional decimal point, then digits
    numbers = re.findall(r"-?\d*\.?\d+", easing_str)
    # Append 1 and 1 to the extracted numbers
    easing_array = f"[{', '.join(numbers)}, 1, 1]"
    properties["motionEasingStandardCurve"] = ("var", easing_array)

    # Sort properties by name and add to output (4-space indentation)
    for prop_name in sorted(properties.keys()):
        qml_type, qml_value = properties[prop_name]
        lines.append(f"    readonly property {qml_type} {prop_name}: {qml_value}")

    lines.append("}")

    return "\n".join(lines) + "\n"


def _to_camel_case(path: str) -> str:
    """
    Convert dot/underscore-separated path to camelCase.

    Args:
        path: A string like "material.bg_opacity.panel" or "text_secondary".

    Returns:
        Camel-cased string where first part is lowercase and subsequent parts
        are capitalized: "material.bg_opacity.panel" -> "materialBgOpacityPanel".
    """
    # WHY: Replace both underscores and dots with dots to normalize separators
    normalized = path.replace("_", ".").replace("-", ".")
    parts = normalized.split(".")

    if not parts:
        return ""

    # First part lowercase, rest capitalized
    result = parts[0].lower()
    for part in parts[1:]:
        result += part.capitalize()

    return result


def _python_to_qml(value) -> tuple[str, str]:
    """
    Convert a Python value to QML type and string representation.

    Args:
        value: A Python value (int, float, str, bool, etc.).

    Returns:
        A tuple (type, value_string) where type is a QML type name
        ("int", "real", "string", "color", "var") and value_string is the
        properly formatted QML representation.
    """
    if isinstance(value, bool):
        # WHY: Check bool before int because bool is a subclass of int in Python
        return "var", str(value).lower()
    elif isinstance(value, int):
        return "int", str(value)
    elif isinstance(value, float):
        # WHY: Use repr() to preserve precision and maintain float format (e.g. 1.0)
        return "real", repr(value)
    elif isinstance(value, str):
        # WHY: Escape backslashes first, then double quotes to avoid double-escaping
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return "string", f'"{escaped}"'
    else:
        # Fallback for unknown types (should not occur with valid tokens)
        return "var", str(value)
