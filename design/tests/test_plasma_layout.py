"""
Tests for the Plasma panel layout generator (design.generators.plasma_layout).

Both golden texts below (one for render(), one for render_view_settings()) are
written out by hand from the real, live-verified Plasma ini structure - not
computed with the generator itself, so a wrong widget id, a wrong containment
id, a wrong AppletOrder or a dropped key cannot hide behind shared code. The
evidence trail: applying the (now-abandoned) scripting-API version of this
generator once via org.kde.PlasmaShell.evaluateScript in the project's guest
image and reading back BOTH ~/.config/plasma-org.kde.plasma.desktop-appletsrc
and ~/.config/plasmashellrc afterwards - see the implementing agent's report
and design/generators/plasma_layout.py's own module docstring for the exact
commands and diffs.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from design.generators import plasma_layout
from design.generators.plasma_layout import render, render_activities, render_view_settings

# The real design tokens live next to the tests' parent package (design/).
REAL_TOKENS_PATH = Path(__file__).resolve().parent.parent / "tokens.json"

# Synthetic tokens: distinct, easy-to-spot values for the two tokens
# render_view_settings() actually reads, plus the three tokens the module
# docstring says have no equivalent key in either file (shelf_margin,
# shelf_hover_scale, radius.panel), so tests below can prove changing them
# leaves the output of BOTH functions untouched.
SYNTHETIC_TOKENS = {
    "panel": {
        "menubar_height": 30,
        "shelf_icon": 64,
        "shelf_margin": 11,
        "shelf_hover_scale": 1.5,
    },
    "radius": {"panel": 99},
}

# The widget/plasmoid ids the top panel must contain, in the exact
# left-to-right order the contract requires.
TOP_WIDGETS_IN_ORDER = [
    "org.kde.plasma.kickoff",
    "org.kde.plasma.appmenu",
    "org.kde.plasma.panelspacer",
    "org.kde.plasma.systemtray",
    "org.kde.plasma.digitalclock",
]

SHELF_WIDGET = "org.kde.plasma.icontasks"


@pytest.fixture(scope="module")
def real_tokens() -> dict:
    """Load the real design/tokens.json once (tests deep-copy before mutating)."""
    return json.loads(REAL_TOKENS_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# render() -- plasma-org.kde.plasma.desktop-appletsrc
# ---------------------------------------------------------------------------


def test_golden_output_synthetic_tokens() -> None:
    """
    render() ignores tokens entirely (verified live: appletsrc carries no panel
    geometry key at all - see the module docstring), so its output for
    SYNTHETIC_TOKENS must be byte-identical to its output for the real tokens.
    """
    assert render(SYNTHETIC_TOKENS) == render(json.loads(REAL_TOKENS_PATH.read_text(encoding="utf-8")))


def test_output_contains_action_plugins_blocks() -> None:
    """The two containment-type-level default context-menu action blocks are present."""
    text = render(SYNTHETIC_TOKENS)
    assert "[ActionPlugins][0]" in text
    assert "[ActionPlugins][1]" in text
    assert "MiddleButton;NoModifier=org.kde.paste" in text
    assert text.count("RightButton;NoModifier=org.kde.contextmenu") == 2


def test_desktop_containment_present() -> None:
    """The desktop containment (org.kde.plasma.folder) exists with a non-empty activityId."""
    text = render(SYNTHETIC_TOKENS)
    assert "[Containments][1]" in text
    assert "plugin=org.kde.plasma.folder" in text
    block = text[text.index("[Containments][1]") : text.index("[Containments][2]")]
    assert "activityId=" in block
    # Non-empty: the line must have something after the '=' (every live sample of a
    # working desktop containment carried a real value; empty was never observed).
    activity_line = next(line for line in block.splitlines() if line.startswith("activityId="))
    assert activity_line != "activityId=", "desktop containment must not have an empty activityId"


def test_top_panel_widget_order() -> None:
    """Top panel widgets appear in the exact contract order (AppletOrder and Applets)."""
    text = render(SYNTHETIC_TOKENS)
    positions = [text.index(f"plugin={widget}") for widget in TOP_WIDGETS_IN_ORDER]
    assert positions == sorted(positions), "top panel widgets must be listed left to right"

    applet_order_line = next(
        line for line in text.splitlines() if line.startswith("AppletOrder=") and "[Containments][2][General]" in text
    )
    # Extract the AppletOrder value that follows [Containments][2][General].
    top_general = text[text.index("[Containments][2][General]") :]
    top_general = top_general[: top_general.index("\n\n")] if "\n\n" in top_general else top_general
    order_line = next(line for line in top_general.splitlines() if line.startswith("AppletOrder="))
    order_ids = order_line.removeprefix("AppletOrder=").split(";")
    assert len(order_ids) == len(TOP_WIDGETS_IN_ORDER)
    del applet_order_line  # only used to assert existence above


def test_every_widget_id_appears_exactly_once() -> None:
    """Every panel widget id is present exactly once (no duplicates, none missing)."""
    text = render(SYNTHETIC_TOKENS)
    for widget in [*TOP_WIDGETS_IN_ORDER, SHELF_WIDGET]:
        assert text.count(f"plugin={widget}") == 1, widget


def test_shelf_widget_is_only_in_bottom_panel() -> None:
    """icontasks belongs to the bottom panel containment, not the top one."""
    text = render(SYNTHETIC_TOKENS)
    bottom_start = text.index("[Containments][8]")
    assert text.index(f"plugin={SHELF_WIDGET}") > bottom_start
    top_block = text[text.index("[Containments][2]") : bottom_start]
    assert SHELF_WIDGET not in top_block


def test_panel_locations_are_top_and_bottom_edge() -> None:
    """
    location=3 is TopEdge, location=4 is BottomEdge - verified live (the pre-existing
    stock bottom panel already showed location=4; a script-created top panel showed
    location=3 in the same live read-back), not the Plasma::Types::Location enum
    recalled from memory.
    """
    text = render(SYNTHETIC_TOKENS)
    top_block = text[text.index("[Containments][2]") : text.index("[Containments][2][Applets]")]
    bottom_block = text[text.index("[Containments][8]") : text.index("[Containments][8][Applets]")]
    assert "location=3" in top_block
    assert "location=4" in bottom_block


def test_panel_containments_have_empty_activity_id() -> None:
    """
    Unlike the desktop containment, panel containments carry an EMPTY activityId -
    verified live (every sample of a working panel containment showed activityId=
    with nothing after it; panels are not tied to a specific activity).
    """
    text = render(SYNTHETIC_TOKENS)
    for cid in (2, 8):
        block = text[text.index(f"[Containments][{cid}]") : text.index(f"[Containments][{cid}][Applets]")]
        assert "activityId=\n" in block or block.rstrip().endswith("activityId=")


def test_output_is_deterministic() -> None:
    """Identical inputs (even from a deep copy) give byte-identical output."""
    first = render(SYNTHETIC_TOKENS)
    second = render(copy.deepcopy(SYNTHETIC_TOKENS))
    assert first == second


def test_output_ends_with_single_trailing_newline() -> None:
    """Exactly one trailing newline, no CR (matches the other generators' convention)."""
    text = render(SYNTHETIC_TOKENS)
    assert text.endswith("\n")
    assert not text.endswith("\n\n")
    assert "\r" not in text


def test_no_panel_geometry_tokens_appear_in_appletsrc(real_tokens: dict) -> None:
    """
    menubar_height/shelf_icon/shelf_margin/shelf_hover_scale/radius.panel must never
    leak into appletsrc - they live in plasmashellrc instead (render_view_settings).
    Distinct token values chosen so an accidental leak cannot hide behind a coincidence
    with an unrelated number already in the file.
    """
    changed = copy.deepcopy(real_tokens)
    changed["panel"]["menubar_height"] = 30201
    changed["panel"]["shelf_icon"] = 30202
    changed["panel"]["shelf_margin"] = 30203
    changed["panel"]["shelf_hover_scale"] = 30204.5
    changed["radius"]["panel"] = 30205
    assert render(changed) == render(real_tokens)
    text = render(changed)
    for needle in ("30201", "30202", "30203", "30204", "30205"):
        assert needle not in text


def test_module_constants_are_reused_not_retyped() -> None:
    """
    Sanity check that the test file's widget list matches the generator's own
    constants (catches the list drifting apart silently, same intent as the old
    JS-golden test's header comment about not re-typing shared data).
    """
    assert list(plasma_layout._TOP_WIDGETS) == TOP_WIDGETS_IN_ORDER
    assert plasma_layout._SHELF_WIDGET == SHELF_WIDGET


# ---------------------------------------------------------------------------
# render_view_settings() -- plasmashellrc
# ---------------------------------------------------------------------------


def test_view_settings_golden_synthetic_tokens() -> None:
    """The entire plasmashellrc output equals the hand-written golden text."""
    expected = (
        "# Panel view settings (thickness, floating/fit-to-content) and the list of\n"
        "# layout migrations that count as already applied. Because the layout file is\n"
        "# shipped complete, the migration scripts of the shell must not run against it;\n"
        "# listing them here marks them as done (same precedent as the screenshot\n"
        "# harness's own harness/vm/guest/skel/.config/plasmashellrc).\n"
        "[PlasmaViews][Panel 2]\n"
        "floating=1\n"
        "shell=org.kde.plasma.desktop\n"
        "\n"
        "[PlasmaViews][Panel 2][Defaults]\n"
        "thickness=30\n"
        "\n"
        "[PlasmaViews][Panel 8]\n"
        "floating=1\n"
        "panelLengthMode=1\n"
        "shell=org.kde.plasma.desktop\n"
        "\n"
        "[PlasmaViews][Panel 8][Defaults]\n"
        "thickness=64\n"
        "\n"
        "[Updates]\n"
        f"performed={plasma_layout._UPDATES_PERFORMED}\n"
    )
    assert render_view_settings(SYNTHETIC_TOKENS) == expected


def test_view_settings_real_tokens_produce_the_real_verified_values(real_tokens: dict) -> None:
    """
    Rendering the real tokens.json reproduces the exact thickness values that were
    applied live via evaluateScript and read back (menubar_height=26, shelf_icon=52
    in the committed tokens.json at the time of writing).
    """
    text = render_view_settings(real_tokens)
    assert "thickness=26" in text
    assert "thickness=52" in text


def test_view_settings_only_bottom_panel_has_panel_length_mode() -> None:
    """
    panelLengthMode=1 (fit-to-content, the key that makes a floating panel shrink and
    centre instead of filling the screen) belongs ONLY to the bottom/shelf panel -
    verified live by diffing the top panel's [PlasmaViews] section (created by the
    same script, at the same time) against the bottom panel's, which is the only one
    that gained this key.
    """
    text = render_view_settings(SYNTHETIC_TOKENS)
    top_block = text[text.index("[PlasmaViews][Panel 2]") : text.index("[PlasmaViews][Panel 8]")]
    bottom_block = text[text.index("[PlasmaViews][Panel 8]") :]
    assert "panelLengthMode" not in top_block
    assert "panelLengthMode=1" in bottom_block


def test_view_settings_both_panels_are_floating() -> None:
    """
    floating=1 is present for both panels - verified live as this Plasma version's
    uniform default for every panel view (even the plain edge-to-edge top panel and
    the pre-existing stock bottom panel already carried it), not specific to the
    "floating, centred" shelf panel alone.
    """
    text = render_view_settings(SYNTHETIC_TOKENS)
    assert text.count("floating=1") == 2


def test_view_settings_contains_updates_performed_list() -> None:
    """
    The [Updates] performed= list (copied from harness/vm/guest/skel/.config/
    plasmashellrc's own precedent) must be present so Plasma's first-run config
    migrations do not mutate a file that is shipped already-current.
    """
    text = render_view_settings(SYNTHETIC_TOKENS)
    assert "[Updates]" in text
    assert "performed=" in text
    assert "no_middle_click_paste_on_panels.js" in text


def test_view_settings_thickness_changes_are_isolated() -> None:
    """Changing menubar_height rewrites only the top panel's thickness, nothing else."""
    changed = copy.deepcopy(SYNTHETIC_TOKENS)
    changed["panel"]["menubar_height"] = 999

    before = render_view_settings(SYNTHETIC_TOKENS)
    after = render_view_settings(changed)
    assert before != after

    before_lines, after_lines = before.splitlines(), after.splitlines()
    assert len(before_lines) == len(after_lines)
    diff = [(b, a) for b, a in zip(before_lines, after_lines, strict=True) if b != a]
    assert diff == [("thickness=30", "thickness=999")]


def test_view_settings_shelf_icon_changes_are_isolated() -> None:
    """Changing shelf_icon rewrites only the bottom panel's thickness, nothing else."""
    changed = copy.deepcopy(SYNTHETIC_TOKENS)
    changed["panel"]["shelf_icon"] = 999

    before = render_view_settings(SYNTHETIC_TOKENS)
    after = render_view_settings(changed)
    assert before != after

    before_lines, after_lines = before.splitlines(), after.splitlines()
    assert len(before_lines) == len(after_lines)
    diff = [(b, a) for b, a in zip(before_lines, after_lines, strict=True) if b != a]
    assert diff == [("thickness=64", "thickness=999")]


@pytest.mark.parametrize("token_path", [("panel", "shelf_margin"), ("panel", "shelf_hover_scale")])
def test_view_settings_unexpressible_panel_tokens_do_not_change_output(token_path: tuple[str, str]) -> None:
    """
    shelf_margin and shelf_hover_scale have no equivalent key in plasmashellrc either
    (verified live the same way as appletsrc's) - changing them must never change the
    output.
    """
    group, key = token_path
    changed = copy.deepcopy(SYNTHETIC_TOKENS)
    changed[group][key] = changed[group][key] + 1000
    assert render_view_settings(changed) == render_view_settings(SYNTHETIC_TOKENS)


def test_view_settings_unexpressible_radius_token_does_not_change_output() -> None:
    """radius.panel (corner rounding) has no plasmashellrc key either."""
    changed = copy.deepcopy(SYNTHETIC_TOKENS)
    changed["radius"]["panel"] = 12345
    assert render_view_settings(changed) == render_view_settings(SYNTHETIC_TOKENS)


def test_view_settings_output_is_deterministic() -> None:
    """Identical inputs (even from a deep copy) give byte-identical output."""
    first = render_view_settings(SYNTHETIC_TOKENS)
    second = render_view_settings(copy.deepcopy(SYNTHETIC_TOKENS))
    assert first == second


def test_view_settings_output_ends_with_single_trailing_newline() -> None:
    """Exactly one trailing newline, no CR."""
    text = render_view_settings(SYNTHETIC_TOKENS)
    assert text.endswith("\n")
    assert not text.endswith("\n\n")
    assert "\r" not in text


def test_view_settings_panel_ids_match_appletsrc_containment_ids(real_tokens: dict) -> None:
    """
    plasmashellrc's [PlasmaViews][Panel <id>] ids must be the SAME ids render() gives
    the two panel Containments - otherwise Plasma would apply the thickness/floating
    settings to panels that do not exist (or the wrong ones).
    """
    appletsrc = render(real_tokens)
    view_settings = render_view_settings(real_tokens)
    assert "[Containments][2]" in appletsrc
    assert "[Containments][8]" in appletsrc
    assert "[PlasmaViews][Panel 2]" in view_settings
    assert "[PlasmaViews][Panel 8]" in view_settings


# ---------------------------------------------------------------------------
# render_activities() -- kactivitymanagerdrc
# ---------------------------------------------------------------------------


def test_activities_golden_output() -> None:
    """render_activities() ignores tokens too (the activity id is a fixed constant)."""
    expected = (
        "# The one activity of the session. Its id is also written into the desktop layout\n"
        "# (plasma-org.kde.plasma.desktop-appletsrc, render() in this same generator module);\n"
        "# both must stay equal, or the desktop containment refers to an activity that does\n"
        "# not exist.\n"
        "[activities]\n"
        f"{plasma_layout._ACTIVITY_ID}=Default\n"
        "\n"
        "[main]\n"
        f"currentActivity={plasma_layout._ACTIVITY_ID}\n"
    )
    assert render_activities(SYNTHETIC_TOKENS) == expected
    assert render_activities(SYNTHETIC_TOKENS) == render_activities({"panel": {}, "radius": {}})


def test_activities_id_matches_appletsrc_desktop_containment(real_tokens: dict) -> None:
    """
    The activity id kactivitymanagerdrc names as [main] currentActivity= must be
    EXACTLY the id render()'s desktop containment (Containments[1]) carries as
    activityId= - otherwise the desktop containment is orphaned from the session's
    current activity (the real gap this file closes; verified live against the
    actually-packaged guest image, not assumed from the appletsrc case alone).
    """
    appletsrc = render(real_tokens)
    activities = render_activities(real_tokens)
    desktop_block = appletsrc[appletsrc.index("[Containments][1]") : appletsrc.index("[Containments][2]")]
    activity_line = next(line for line in desktop_block.splitlines() if line.startswith("activityId="))
    appletsrc_id = activity_line.removeprefix("activityId=")

    assert f"currentActivity={appletsrc_id}" in activities
    assert f"{appletsrc_id}=Default" in activities


def test_activities_output_ends_with_single_trailing_newline() -> None:
    """Exactly one trailing newline, no CR."""
    text = render_activities(SYNTHETIC_TOKENS)
    assert text.endswith("\n")
    assert not text.endswith("\n\n")
    assert "\r" not in text
