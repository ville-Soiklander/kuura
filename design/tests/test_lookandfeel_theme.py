"""Tests for the Look-and-Feel logout dialog generator (mirrors design/tests/test_sddm_theme.py)."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from design.generators.lookandfeel_theme import render_logout_qml, render_metadata_json

# Synthetic tokens containing every colour key and all required non-colour keys
# this generator reads, mirroring design/tests/test_sddm_theme.py's own
# fixture shape.
_TOKENS = {
    "color": {
        "light": {
            "window": "#010203", "surface": "#020304", "surface_alt": "#030405",
            "text": "#040506", "text_secondary": "#050607", "text_disabled": "#060708",
            "accent": "#070809", "accent_text": "#08090A", "separator": "#090A0B",
            "link": "#0A0B0C", "link_visited": "#0B0C0D",
            "error": "#0C0D0E", "warning": "#0D0E0F", "success": "#0E0F10",
            "tooltip_bg": "#0F1011", "tooltip_text": "#101112", "shadow": "#00000033",
            "button_close": "#111213", "button_minimize": "#121314", "button_maximize": "#131415",
        },
        "dark": {
            "window": "#201202", "surface": "#212223", "surface_alt": "#222324",
            "text": "#232425", "text_secondary": "#242526", "text_disabled": "#252627",
            "accent": "#262728", "accent_text": "#272829", "separator": "#28292A",
            "link": "#292A2B", "link_visited": "#2A2B2C",
            "error": "#2B2C2D", "warning": "#2C2D2E", "success": "#2D2E2F",
            "tooltip_bg": "#2E2F30", "tooltip_text": "#2F3031", "shadow": "#00000066",
            "button_close": "#303132", "button_minimize": "#313233", "button_maximize": "#323334",
        },
    },
    "radius": {"window": 14, "panel": 12, "menu": 10, "card": 12, "button": 8, "field": 8, "tooltip": 8, "icon": "squircle-n5"},
    "type": {"family_ui": "TestFont", "family_mono": "TestMono", "size": {"caption": 11, "body": 13, "title": 15, "header": 22}, "weight": {"regular": 400, "medium": 500, "semibold": 600}, "tracking": {"body": -0.01, "header": -0.02}},
    "motion": {"duration": {"instant": 100, "fast": 180, "base": 260, "slow": 400}, "easing_standard": "cubic-bezier(0.32, 0.72, 0, 1)", "easing_spring": {"mass": 1, "stiffness": 340, "damping": 32}},
    "spacing": {"grid": 4, "gutter": 12, "section": 20},
}


class TestRenderMetadataJson:
    """Tests for render_metadata_json()."""

    def test_returns_valid_json(self):
        result = render_metadata_json(name="theme")
        json.loads(result)  # must not raise

    def test_real_schema_keys_present(self):
        """KPackageStructure/KPlugin.{Id,Name,Description,License} - the real,
        confirmed shape (module docstring)."""
        data = json.loads(render_metadata_json(name="theme"))
        assert data["KPackageStructure"] == "Plasma/LookAndFeel"
        assert set(("Id", "Name", "Description", "License")) <= set(data["KPlugin"].keys())

    def test_id_is_fixed_literal_kuura_regardless_of_name(self):
        """Module docstring, point 5: KPlugin.Id MUST be the literal "kuura" -
        it must match kdeglobals' own already-shipped LookAndFeelPackage key,
        and must NOT track the `name` argument the way every other
        ${DISTRO_NAME}-templated identifier in this project does."""
        for name in ("theme", "my-distro-name", "something-else"):
            data = json.loads(render_metadata_json(name=name))
            assert data["KPlugin"]["Id"] == "kuura"

    def test_name_feeds_display_name(self):
        data = json.loads(render_metadata_json(name="my-distro-name"))
        assert data["KPlugin"]["Name"] == "my-distro-name"
        assert "my-distro-name" in data["KPlugin"]["Description"]

    def test_license_is_project_license(self):
        data = json.loads(render_metadata_json(name="theme"))
        assert data["KPlugin"]["License"] == "GPL-3.0-or-later"

    def test_ends_with_exactly_one_newline(self):
        result = render_metadata_json(name="theme")
        assert result.endswith("\n")
        assert not result.endswith("\n\n")

    def test_deterministic(self):
        assert render_metadata_json(name="theme") == render_metadata_json(name="theme")


class TestRenderLogoutQml:
    """Tests for render_logout_qml()."""

    def test_bad_mode_raises_valueerror(self):
        with pytest.raises(ValueError, match="light.*dark"):
            render_logout_qml(_TOKENS, mode="invalid", name="theme")

    def test_confirmed_imports_present(self):
        """Only the plain-QtQuick import surface named in the module docstring."""
        result = render_logout_qml(_TOKENS, mode="dark", name="theme")
        import_lines = [line for line in result.splitlines() if line.startswith("import ")]
        assert import_lines == [
            "import QtQuick",
            "import QtQuick.Controls as QQC2",
            "import QtQuick.Layouts",
        ]
        assert not any("kirigami" in line.lower() or "plasma" in line.lower() for line in import_lines)

    def test_confirmed_signals_declared(self):
        """Every real signal shutdowndlg.cpp's own connect() calls wire up
        (module docstring) must actually be declared on the root item."""
        result = render_logout_qml(_TOKENS, mode="dark", name="theme")
        for signal in (
            "signal logoutRequested()",
            "signal haltRequested()",
            "signal rebootRequested()",
            "signal suspendRequested(int spdMethod)",
            "signal cancelRequested()",
            "signal lockScreenRequested()",
        ):
            assert signal in result, f"Missing confirmed signal declaration: {signal}"

    def test_every_declared_signal_is_also_emitted(self):
        """A signal that is declared but never emitted from a button is a real gap."""
        result = render_logout_qml(_TOKENS, mode="dark", name="theme")
        for emission in (
            "root.logoutRequested()",
            "root.haltRequested()",
            "root.rebootRequested()",
            "root.suspendRequested(2)",
            "root.cancelRequested()",
            "root.lockScreenRequested()",
        ):
            assert emission in result, f"Declared signal never emitted: {emission}"

    def test_confirmed_context_properties_used(self):
        """maysd/canLogout/spdMethods - the real context properties
        shutdowndlg.cpp's own init() injects (module docstring)."""
        result = render_logout_qml(_TOKENS, mode="dark", name="theme")
        assert "maysd" in result
        assert "canLogout" in result
        # Real sub-key is SuspendState, not "Suspend" - see module docstring's
        # own correction note (confirmed directly against shutdowndlg.cpp's
        # QQmlPropertyMap construction, not the originally supplied name).
        assert "spdMethods.SuspendState" in result

    def test_sdtype_never_referenced_in_code(self):
        """This generator's own fixed button set passes sdtype through
        unexamined - it is never read as an actual QML binding (module
        docstring). "sdtype" may still appear in prose comments explaining
        this choice, so only non-comment lines are checked."""
        result = render_logout_qml(_TOKENS, mode="dark", name="theme")
        code_lines = [line for line in result.splitlines() if not line.strip().startswith("//")]
        assert not any("sdtype" in line for line in code_lines)

    def test_literal_colors_baked_for_the_selected_mode(self):
        """Every colour token is baked as a literal (no runtime override
        surface exists for this package - module docstring), and changes
        with mode."""
        dark = render_logout_qml(_TOKENS, mode="dark", name="theme")
        light = render_logout_qml(_TOKENS, mode="light", name="theme")
        assert "#201202" in dark  # tokens.color.dark.window via to_qml()
        assert "#010203" in light  # tokens.color.light.window via to_qml()
        assert dark != light

    def test_radius_and_type_tokens_used(self):
        result = render_logout_qml(_TOKENS, mode="dark", name="theme")
        assert "radiusWindow: 14" in result
        assert "radiusButton: 8" in result
        assert '"TestFont"' in result
        assert "fontSizeTitle: 15" in result
        assert "transitionMs: 180" in result

    def test_name_not_leaked_into_output(self):
        result = render_logout_qml(_TOKENS, mode="dark", name="my-distro-name")
        assert "my-distro-name" not in result

    def test_ends_with_exactly_one_newline(self):
        result = render_logout_qml(_TOKENS, mode="dark", name="theme")
        assert result.endswith("\n")
        assert not result.endswith("\n\n")

    def test_deterministic(self):
        assert render_logout_qml(_TOKENS, mode="dark", name="theme") == render_logout_qml(_TOKENS, mode="dark", name="theme")

    def test_balanced_braces(self):
        """A gross but cheap syntax sanity check before qmllint ever runs."""
        result = render_logout_qml(_TOKENS, mode="dark", name="theme")
        assert result.count("{") == result.count("}")

    def test_changing_accent_token_changes_output(self):
        """Regression: a changed colour token must actually reach Logout.qml."""
        modified = copy.deepcopy(_TOKENS)
        modified["color"]["dark"]["accent_text"] = "#ff00ff"

        original = render_logout_qml(_TOKENS, mode="dark", name="theme")
        changed = render_logout_qml(modified, mode="dark", name="theme")

        assert original != changed
        assert "#FF00FF" in changed

    def test_real_tokens_json_renders_without_error(self):
        """End-to-end smoke test against the real, checked-in tokens.json."""
        from design.validate import load_tokens

        tokens = load_tokens(Path(__file__).parent.parent / "tokens.json")
        result = render_logout_qml(tokens, mode="dark", name="theme")
        assert result.endswith("\n")
        assert result.count("{") == result.count("}")
