"""
Validation of design/tokens.json against real-world value ranges.

WHY not a JSON Schema file: a schema validator would be a new third-party
dependency. The rules below are table-driven and use only the standard library.
WHY strict ranges: a type check is not enough - a corner radius of -5 or an
opacity of 7 are valid numbers but can never be correct design values.

This file is the LOCKED INTERFACE of the token validator: implement the bodies
without changing signatures, the exception class or the rules listed here.

Rules (path -> constraint). "number" means int or float but never bool.
- radius.window|panel|menu|card|button|field|tooltip: int 0..64
- radius.icon: non-empty str
- material.blur_radius: number 0..200; material.noise: number 0..1
- material.bg_opacity.panel|menu|sidebar|modal: number 0..1
- material.edge_highlight.opacity: 0..1; .width: 0..8
- material.inner_shadow.opacity: 0..1; .blur: 0..50
- material.refraction.strength: 0..0.5; .edge_falloff: 0..100
- spacing.grid: int 1..16; spacing.gutter: int 0..64; spacing.section: int 0..128
- type.family_ui, type.family_mono: non-empty str
- type.size.caption|body|title|header: int 8..72 and caption <= body <= title <= header
- type.weight.regular|medium|semibold: int 100..900, multiple of 100, ascending
- type.tracking.body|header: number -0.1..0.1
- motion.duration.instant|fast|base|slow: int 1..5000 and instant <= fast <= base <= slow
- motion.easing_standard: "cubic-bezier(a, b, c, d)" with four numbers, a and c in 0..1
- motion.easing_spring.mass|stiffness|damping: number > 0
- panel.menubar_height: int 16..64; panel.shelf_icon: int 16..128;
  panel.shelf_margin: int 0..64; panel.shelf_hover_scale: number 1.0..2.5
- color.light and color.dark: both objects with EXACTLY the same 20 keys:
  window, surface, surface_alt, text, text_secondary, text_disabled, accent,
  accent_text, separator, link, link_visited, error, warning, success,
  tooltip_bg, tooltip_text, shadow, button_close, button_minimize,
  button_maximize; every value a string matching #RRGGBB or #RRGGBBAA (hex).
- Top-level key "_meta" is allowed and ignored. ANY other unknown key, at any
  level, is an error (typo protection); every missing key is an error.
"""

from __future__ import annotations

import json
import re
from pathlib import Path


class TokenError(ValueError):
    """Raised when the token file cannot be read or fails validation."""


# WHY: Table-driven schema. Type name maps to (min, max) for ranges or special handling.
_RULES = {
    "radius.window": ("int", 0, 64), "radius.panel": ("int", 0, 64),
    "radius.menu": ("int", 0, 64), "radius.card": ("int", 0, 64),
    "radius.button": ("int", 0, 64), "radius.field": ("int", 0, 64),
    "radius.tooltip": ("int", 0, 64), "radius.icon": ("str",),
    "material.blur_radius": ("number", 0, 200), "material.noise": ("number", 0, 1),
    "material.bg_opacity.panel": ("number", 0, 1), "material.bg_opacity.menu": ("number", 0, 1),
    "material.bg_opacity.sidebar": ("number", 0, 1), "material.bg_opacity.modal": ("number", 0, 1),
    "material.edge_highlight.opacity": ("number", 0, 1), "material.edge_highlight.width": ("number", 0, 8),
    "material.inner_shadow.opacity": ("number", 0, 1), "material.inner_shadow.blur": ("number", 0, 50),
    "material.refraction.strength": ("number", 0, 0.5), "material.refraction.edge_falloff": ("number", 0, 100),
    "spacing.grid": ("int", 1, 16), "spacing.gutter": ("int", 0, 64), "spacing.section": ("int", 0, 128),
    "type.family_ui": ("str",), "type.family_mono": ("str",),
    "type.size.caption": ("int", 8, 72), "type.size.body": ("int", 8, 72),
    "type.size.title": ("int", 8, 72), "type.size.header": ("int", 8, 72),
    "type.weight.regular": ("int", 100, 900), "type.weight.medium": ("int", 100, 900),
    "type.weight.semibold": ("int", 100, 900), "type.tracking.body": ("number", -0.1, 0.1),
    "type.tracking.header": ("number", -0.1, 0.1),
    "motion.duration.instant": ("int", 1, 5000), "motion.duration.fast": ("int", 1, 5000),
    "motion.duration.base": ("int", 1, 5000), "motion.duration.slow": ("int", 1, 5000),
    "motion.easing_standard": ("cubic_bezier",), "motion.easing_spring.mass": ("positive",),
    "motion.easing_spring.stiffness": ("positive",), "motion.easing_spring.damping": ("positive",),
    "panel.menubar_height": ("int", 16, 64), "panel.shelf_icon": ("int", 16, 128),
    "panel.shelf_margin": ("int", 0, 64), "panel.shelf_hover_scale": ("number", 1.0, 2.5),
}

# WHY: Nested dicts: path -> set of expected keys
_NESTED = {
    "material.bg_opacity": {"panel", "menu", "sidebar", "modal"},
    "material.edge_highlight": {"opacity", "width"},
    "material.inner_shadow": {"opacity", "blur"},
    "material.refraction": {"strength", "edge_falloff"},
    "type.size": {"caption", "body", "title", "header"},
    "type.weight": {"regular", "medium", "semibold"},
    "type.tracking": {"body", "header"},
    "motion.duration": {"instant", "fast", "base", "slow"},
    "motion.easing_spring": {"mass", "stiffness", "damping"},
    "color.light": {"window", "surface", "surface_alt", "text", "text_secondary", "text_disabled",
                    "accent", "accent_text", "separator", "link", "link_visited", "error", "warning",
                    "success", "tooltip_bg", "tooltip_text", "shadow", "button_close", "button_minimize",
                    "button_maximize"},
    "color.dark": {"window", "surface", "surface_alt", "text", "text_secondary", "text_disabled",
                   "accent", "accent_text", "separator", "link", "link_visited", "error", "warning",
                   "success", "tooltip_bg", "tooltip_text", "shadow", "button_close", "button_minimize",
                   "button_maximize"},
}

_ORDERING = {
    "type.size": ("caption", "body", "title", "header"),
    "type.weight": ("regular", "medium", "semibold"),
    "motion.duration": ("instant", "fast", "base", "slow"),
}

_SECTIONS = {
    "radius": {"window", "panel", "menu", "card", "button", "field", "tooltip", "icon"},
    "material": {"blur_radius", "noise", "bg_opacity", "edge_highlight", "inner_shadow", "refraction"},
    "spacing": {"grid", "gutter", "section"},
    "type": {"family_ui", "family_mono", "size", "weight", "tracking"},
    "motion": {"duration", "easing_standard", "easing_spring"},
    "panel": {"menubar_height", "shelf_icon", "shelf_margin", "shelf_hover_scale"},
    "color": {"light", "dark"},
}


def _is_number(v: object) -> bool:
    """Check if value is a number but not bool."""
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _validate_value(value: object, rule: tuple, path: str) -> list[str]:
    """
    Validate a single value against a rule.

    Args:
        value: The value to check.
        rule: Tuple (type, *constraints).
        path: Dotted path for error messages.

    Returns:
        List of error messages.
    """
    errors = []
    rule_type = rule[0]

    if rule_type == "int":
        if not isinstance(value, int) or isinstance(value, bool):
            errors.append(f"{path}: must be an integer, got {type(value).__name__}")
        elif len(rule) > 1 and not (rule[1] <= value <= rule[2]):
            errors.append(f"{path}: must be {rule[1]}..{rule[2]}, got {value}")
        elif path in {"type.weight.regular", "type.weight.medium", "type.weight.semibold"} and value % 100 != 0:
            errors.append(f"{path}: must be multiple of 100, got {value}")

    elif rule_type == "number":
        if not _is_number(value):
            errors.append(f"{path}: must be a number, got {type(value).__name__}")
        elif len(rule) > 1 and not (rule[1] <= value <= rule[2]):
            errors.append(f"{path}: must be {rule[1]}..{rule[2]}, got {value}")

    elif rule_type == "str":
        if not isinstance(value, str) or not value:
            errors.append(f"{path}: must be non-empty string, got {value!r}")

    elif rule_type == "hex_color":
        if not isinstance(value, str):
            errors.append(f"{path}: must be a string, got {type(value).__name__}")
        elif not re.fullmatch(r"#[0-9A-Fa-f]{6}([0-9A-Fa-f]{2})?", value):
            errors.append(f"{path}: invalid hex colour {value!r}")

    elif rule_type == "positive":
        if not _is_number(value):
            errors.append(f"{path}: must be a number, got {type(value).__name__}")
        elif value <= 0:
            errors.append(f"{path}: must be > 0, got {value}")

    elif rule_type == "cubic_bezier":
        if not isinstance(value, str):
            errors.append(f"{path}: must be a string, got {type(value).__name__}")
        elif not (value.startswith("cubic-bezier(") and value.endswith(")")):
            errors.append(f"{path}: must be 'cubic-bezier(a, b, c, d)' format, got {value!r}")
        else:
            try:
                parts = [float(p.strip()) for p in value[13:-1].split(",")]
                if len(parts) != 4:
                    errors.append(f"{path}: must have 4 numbers, got {len(parts)}")
                else:
                    a, b, c, d = parts
                    if not (0 <= a <= 1):
                        errors.append(f"{path}: first parameter must be 0..1, got {a}")
                    if not (0 <= c <= 1):
                        errors.append(f"{path}: third parameter must be 0..1, got {c}")
            except (ValueError, IndexError):
                errors.append(f"{path}: must contain 4 valid numbers, got {value!r}")

    return errors


def validate(tokens: dict) -> list[str]:
    """
    Check a parsed token dictionary.

    Args:
        tokens: Parsed content of tokens.json.

    Returns:
        A list of human readable problems, each starting with the dotted path
        of the offending value, e.g. "radius.button: must be 0..64, got -5".
        An empty list means the tokens are valid. Never raises for bad data.
    """
    errors = []

    if not isinstance(tokens, dict):
        return ["tokens must be a dictionary"]

    # Validate non-color sections
    for section in ["radius", "material", "spacing", "type", "motion", "panel"]:
        if section not in tokens:
            errors.append(f"{section}: missing or not a dict")
            continue

        obj = tokens[section]
        if not isinstance(obj, dict):
            errors.append(f"{section}: missing or not a dict")
            continue

        # Check required keys
        required = _SECTIONS[section]
        for key in required:
            if key not in obj:
                errors.append(f"{section}.{key}: missing key")

        # Check all keys and values
        for key, value in obj.items():
            path = f"{section}.{key}"
            if key not in required:
                errors.append(f"{path}: unknown key")
                continue

            # Nested dict handling
            if path in _NESTED:
                if not isinstance(value, dict):
                    errors.append(f"{path}: missing or not a dict")
                    continue

                nested_req = _NESTED[path]
                for nkey in nested_req:
                    if nkey not in value:
                        errors.append(f"{path}.{nkey}: missing key")

                for nkey, nval in value.items():
                    npath = f"{path}.{nkey}"
                    if nkey not in nested_req:
                        errors.append(f"{npath}: unknown key")
                    elif npath in _RULES:
                        errors.extend(_validate_value(nval, _RULES[npath], npath))

                # Check ordering constraints
                if path in _ORDERING:
                    vals = {k: v for k, v in value.items() if k in _ORDERING[path] and _is_number(v)}
                    for i, (k1, k2) in enumerate(zip(_ORDERING[path], _ORDERING[path][1:])):
                        if k1 in vals and k2 in vals:
                            cmp = "<=" if section != "type" or key != "weight" else "<"
                            if (vals[k1] <= vals[k2] if cmp == "<=" else vals[k1] < vals[k2]):
                                continue
                            errors.append(f"{path}: {k1} ({vals[k1]}) must be {cmp} {k2} ({vals[k2]})")

            elif path in _RULES:
                errors.extend(_validate_value(value, _RULES[path], path))

    # Validate color section
    if "color" not in tokens:
        errors.append("color: missing or not a dict")
    elif not isinstance(tokens["color"], dict):
        errors.append("color: missing or not a dict")
    else:
        for mode in ["light", "dark"]:
            mode_path = f"color.{mode}"
            if mode not in tokens["color"]:
                errors.append(f"{mode_path}: missing or not a dict")
                continue

            color_dict = tokens["color"][mode]
            if not isinstance(color_dict, dict):
                errors.append(f"{mode_path}: missing or not a dict")
                continue

            color_keys = _NESTED["color.light"]
            for key in color_keys:
                if key not in color_dict:
                    errors.append(f"{mode_path}.{key}: missing key")

            for key, val in color_dict.items():
                cpath = f"{mode_path}.{key}"
                if key not in color_keys:
                    errors.append(f"{cpath}: unknown key")
                elif not isinstance(val, str):
                    errors.append(f"{cpath}: must be a string, got {type(val).__name__}")
                elif not re.fullmatch(r"#[0-9A-Fa-f]{6}([0-9A-Fa-f]{2})?", val):
                    errors.append(f"{cpath}: invalid hex colour {val!r}")

    # Check for unknown top-level keys
    for key in tokens:
        if key not in _SECTIONS and key != "_meta":
            errors.append(f"{key}: unknown top-level key")

    return errors


def load_tokens(path: Path) -> dict:
    """
    Read and validate the token file.

    Args:
        path: Path to tokens.json.

    Returns:
        The parsed and validated tokens.

    Raises:
        TokenError: if the file is missing, is not valid JSON, or validate()
            reports any problem (the message lists all problems).
    """
    try:
        tokens = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise TokenError(f"Token file not found: {path}") from e
    except json.JSONDecodeError as e:
        raise TokenError(f"Token file is not valid JSON: {path}: {e}") from e

    problems = validate(tokens)
    if problems:
        raise TokenError("Token validation failed:\n" + "\n".join(problems))

    return tokens
