"""
Generate the panel layout (top menubar panel, bottom floating shelf panel) from tokens.

This file is the LOCKED INTERFACE: implement the body of render() without changing its
signature. Only the standard library may be used; never hard code a token value.
Layout has no light/dark variant, so there is only one output, not one per mode.

REVISED CONTRACT (the scripting-API version this docstring described before is
abandoned - see the note at the end of this docstring for why): this generator now
produces a COMPLETE, ready-to-install `plasma-org.kde.plasma.desktop-appletsrc` INI
file, not a script meant to be run against a live session. Ship the output directly as
`packages/kuura-shell/skel/.config/plasma-org.kde.plasma.desktop-appletsrc`
(`install -Dm644`, same as the other skel files) - no merge step, no fragment.

Uses tokens["panel"] (menubar_height, shelf_icon, shelf_margin, shelf_hover_scale) and
tokens["radius"]["panel"]. The exact ini keys for panel thickness and for a floating,
horizontally-centred panel are NOT assumed here - verify them live in the guest image
before writing the implementation, do not guess a plausible-sounding key name. Two
concrete, already-available shortcuts to real ground truth instead of guessing:
  (a) `harness/vm/guest/skel/.config/plasma-org.kde.plasma.desktop-appletsrc` already
      ships a real, working, currently-applied panel containment (formfactor, location,
      plugin, Applets sub-sections, AppletOrder) - read it as a syntax reference for
      everything this generator's own output must ALSO get right structurally, even
      though its concrete panel differs from the one wanted here.
  (b) the abandoned scripting-API generator set `.height` on each panel through
      `org.kde.PlasmaShell.evaluateScript` and was never shown to be wrong about the
      RESULT, only about nothing ever calling it - applying that exact script once by
      hand through the same D-Bus call in a live guest, then reading back the appletsrc
      it produced, is a fast way to get the real key names for panel thickness and for
      a floating+centred panel with an evidence trail, without guessing.
If the real ini surface cannot express something listed below (this already happened
once for panel corner rounding under the old contract), leave it out and say so in the
report rather than approximating it silently - docs/SHELL_CONTRACT.md's `skel/`
fallback still applies.

Content (mode-independent, everything not named below is the format's own default):
- One top panel: height `tokens["panel"]["menubar_height"]`, full screen width, fixed to
  the top edge. Widgets left to right: the application menu button, a Global Menu widget,
  a spacer that fills remaining space, a system tray widget, a digital clock widget.
- One bottom panel: floating (not edge-to-edge), horizontally centred. One widget: an
  Icons-only Task Manager, icon size `tokens["panel"]["shelf_icon"]`, hover zoom factor
  `tokens["panel"]["shelf_hover_scale"]`. The panel's margin from the screen edge is
  `tokens["panel"]["shelf_margin"]`.
- Everything ELSE a valid appletsrc needs (the desktop containment, its wallpaper
  plugin, `[ActionPlugins]`, the activity id and whatever besides it the activity id
  must stay consistent with - verify live, do not assume the V2 test harness's own
  fixed choices such as its solid-colour wallpaper or curated launcher favourites apply
  here too; those were explicitly test-only simplifications, see that file's own header
  comment) is this generator's responsibility too, since the output must be a complete,
  directly installable file, not a fragment merged with something else at package time.
  Use Plasma's own real out-of-the-box defaults for whatever tokens.json does not
  parametrize, confirmed live, not recalled.

WHY the scripting-API version was abandoned: a `packages/kuura-shell` built against it
shipped a correct script that nothing ever executed - the package only ever installed
static `/etc/skel/...` files (the same mechanism already used for
kwinrc/kglobalshortcutsrc/kdeglobals), with no first-login trigger of any kind, so the
generated panel layout never reached a booted session. A static appletsrc file matches
that existing, already-working mechanism instead of requiring a new runtime step to be
designed, built and kept working - this is also standard practice for how Plasma-based
distributions ship a customised default panel.

SECOND FILE DISCOVERED WHILE IMPLEMENTING THIS REVISION (verified live, not assumed):
appletsrc alone is NOT enough. Applying the old scripting-API script once via
`evaluateScript` in a live guest and reading back BOTH
`~/.config/plasma-org.kde.plasma.desktop-appletsrc` AND `~/.config/plasmashellrc`
showed that panel THICKNESS and the floating/fit-to-content ("shrink to widgets, then
centre") behaviour are stored in plasmashellrc's `[PlasmaViews][Panel <id>]` /
`[PlasmaViews][Panel <id>][Defaults]` sections, not in appletsrc at all - appletsrc only
records which containments/applets exist, their type/edge and their display order.
`harness/vm/guest/skel/.config/plasmashellrc` already ships exactly this kind of file
for the V2 test harness's own stock panel (same `[PlasmaViews][Panel 2]` shape, same
`[Updates] performed=...` list to suppress Plasma's own first-run config-migration
scripts against a file that is shipped already-current) - this generator's second
function, `render_view_settings()`, follows that same precedent for the two new panels.
`packages/kuura-shell/PKGBUILD` installs its output to
`/etc/skel/.config/plasmashellrc` alongside appletsrc. No corner-rounding key
(tokens.radius.panel), margin key (tokens.panel.shelf_margin) or hover-zoom key
(tokens.panel.shelf_hover_scale) was found in EITHER file - confirmed by diffing the
live guest's config before and after applying the panel script, not by assumption -
so, as before, these three tokens are read by neither function and left to `skel/`
theme configuration.

THIRD FILE, ALSO DISCOVERED LIVE: the desktop containment's `activityId` (render(),
above) must match a real KDE Activity that `kactivitymanagerd` knows about, or the
desktop containment is orphaned from the session's current activity. Booting the
actually-packaged image (not just applying the script by hand) surfaced this for
real: with no matching `kactivitymanagerdrc` shipped, a fresh account's desktop
containment referenced an activity id kactivitymanagerd had never heard of. Live
testing (deleting BOTH appletsrc and kactivitymanagerdrc together, then letting
plasmashell/kactivitymanagerd regenerate both from nothing) showed they self-heal to
a MATCHING pair when both start fresh together - but a shipped, pre-existing
appletsrc with kactivitymanagerdrc absent is a different case and was not proven
safe. Rather than leave that unverified, this generator now also produces a matching
`kactivitymanagerdrc` (`render_activities()`) using the exact same `_ACTIVITY_ID`
constant, installed to `/etc/skel/.config/kactivitymanagerdrc` - the same
"activityId must equal the one in kactivitymanagerdrc" pairing
`harness/vm/guest/skel/.config/kactivitymanagerdrc`'s own header comment already
documents for the V2 test harness's stock layout, now extended to the real product.

NOTE ON THE TEST HARNESS'S OWN guest/skel: `harness/vm/guest/skel/.config/` used to
ship its own fixed `plasma-org.kde.plasma.desktop-appletsrc`, `plasmashellrc` and
`kactivitymanagerdrc` for the V2 stock panel. Because the Containerfile copies
`guest/skel/` onto `/etc/skel/` AFTER the metapackage (and therefore kuura-shell) is
installed, those three files silently overwrote everything this package now ships,
and the real panel never reached a booted TEST image even with the install lines
above in place (confirmed live: a freshly rebuilt guest image still showed the V2
stock panel byte-for-byte). Those three files were removed from `guest/skel/` so the
test image now gets the same real panel a shipped product would - see the
implementing agent's report for the exact evidence.
"""

from __future__ import annotations

# Real widget/plasmoid ids for the top panel, left to right - verified live
# against Plasma 6.7.5 in the project's guest image (not recalled/guessed):
#   - "org.kde.plasma.kickoff" is the stock application launcher button
#     (what the contract calls "the application menu button").
#   - "org.kde.plasma.appmenu" is the Global Menu widget. KDE's own shipped
#     layout-templates/org.kde.plasma.desktop.appmenubar package (metadata
#     Name "Application Menu Bar", Description "Panel containing the global
#     menu applet") confirms this id is the Global Menu.
#   - "org.kde.plasma.panelspacer" is the generic *expanding* spacer widget
#     (confirmed from the compiled plugin path
#     /usr/lib/qt6/plugins/plasma/applets/org.kde.plasma.panelspacer.so and
#     PanelConfiguration.qml's "Add New > Spacer" action). This is distinct
#     from "org.kde.plasma.marginsseparator", which is a thin static
#     separator with no fill behaviour, so it cannot stand in for it here.
#   - "org.kde.plasma.systemtray" and "org.kde.plasma.digitalclock" are the
#     stock system tray and digital clock widgets.
_TOP_WIDGETS = (
    "org.kde.plasma.kickoff",
    "org.kde.plasma.appmenu",
    "org.kde.plasma.panelspacer",
    "org.kde.plasma.systemtray",
    "org.kde.plasma.digitalclock",
)

# Icons-Only Task Manager - confirmed shipped by plasma-desktop
# (/usr/share/plasma/plasmoids/org.kde.plasma.icontasks/metadata.json, Name
# "Icons-Only Task Manager") and used verbatim in KDE's own shipped
# layout-templates/org.kde.plasma.desktop.defaultPanel/contents/layout.js.
_SHELF_WIDGET = "org.kde.plasma.icontasks"

# Containment/applet ids this generator mints for the hand-authored appletsrc. A real,
# never-customised Plasma session assigns these sequentially as containments happen to
# be created; a shipped, complete file may pick ANY ids, as long as every reference to
# one (AppletOrder, and plasmashellrc's [PlasmaViews][Panel <id>] sections below) uses
# the same number consistently. Kept low/sequential purely for readability.
_DESKTOP_ID = 1
_TOP_PANEL_ID = 2
_BOTTOM_PANEL_ID = 8
_TOP_APPLET_IDS = (3, 4, 5, 6, 7)  # one per _TOP_WIDGETS entry, same order
_BOTTOM_APPLET_ID = 9

# Fixed KDE Activity id this generator mints for the desktop containment (a freeform
# UUID-shaped string, not one KDE issues - any syntactically valid, stable string
# works). WHY a fixed one rather than leaving it to be invented at first login:
# appletsrc's desktop containment (plugin=org.kde.plasma.folder) always carries a
# non-empty activityId in every live sample taken (a fresh regeneration always filled
# one in) - an empty value was never observed to be valid, so this generator does not
# guess that leaving it blank is safe. kactivitymanagerd (which owns the "which
# activities exist" list, kactivitymanagerdrc) is NOT shipped a matching file by
# kuura-shell, so on a genuinely fresh account it will invent its OWN random id the
# first time it runs, independently of whatever fixed id is baked in here - live
# testing only ever exercised the case where BOTH files start missing together (they
# then agree, because plasmashell asks kactivitymanagerd and writes back whatever it
# is told), not the shipped-appletsrc-with-no-matching-kactivitymanagerdrc case this
# package actually ships. This is called out explicitly (not silently assumed fine)
# and was re-checked visually against the real packaged guest image - see the
# implementing agent's report for the result.
_ACTIVITY_ID = "f3a1c2d4-5b6e-47a8-9c1d-2e3f4a5b6c7d"

# The two ActionPlugins blocks below are Plasma's own compiled-in, per-CONTAINMENT-TYPE
# default context-menu actions (index 0 = Containment::Desktop, index 1 =
# Containment::Panel - confirmed live: every fresh session regenerates exactly these
# two blocks, keyed by containment TYPE, not by containment id, so one panel or ten
# still only ever produce these same two [ActionPlugins][0]/[1] sections). Desktop gets
# an extra middle-click-paste action that panels do not (matches this Plasma version's
# own "no_middle_click_paste_on_panels" migration script, which V2's plasmashellrc
# already lists as performed - see render_view_settings()).
_ACTION_PLUGINS = """\
[ActionPlugins][0]
MiddleButton;NoModifier=org.kde.paste
RightButton;NoModifier=org.kde.contextmenu

[ActionPlugins][1]
RightButton;NoModifier=org.kde.contextmenu"""

# Migration scripts this pinned Plasma version (6.7.5) ships under
# /usr/share/plasma/shells/org.kde.plasma.desktop/contents/updates/ - copied verbatim
# from harness/vm/guest/skel/.config/plasmashellrc (same pinned image, same Plasma
# version, already discovered by this project for the V2 test harness's own shipped-
# complete plasmashellrc). Listing them as "performed" stops Plasma's first-run
# migration runner from mutating a file that is shipped already-current.
_UPDATES_PERFORMED = (
    "/usr/share/plasma/shells/org.kde.plasma.desktop/contents/updates/no_middle_click_paste_on_panels.js,"
    "/usr/share/plasma/shells/org.kde.plasma.desktop/contents/updates/digitalclock_migrate_showseconds_setting.js,"
    "/usr/share/plasma/shells/org.kde.plasma.desktop/contents/updates/taskmanager_configUpdate_wheelEnabled.js,"
    "/usr/share/plasma/shells/org.kde.plasma.desktop/contents/updates/mediaframe_migrate_useBackground_setting.js,"
    "/usr/share/plasma/shells/org.kde.plasma.desktop/contents/updates/migrate_font_weights.js,"
    "/usr/share/plasma/shells/org.kde.plasma.desktop/contents/updates/keyboardlayout_remove_shortcut.js,"
    "/usr/share/plasma/shells/org.kde.plasma.desktop/contents/updates/move_desktop_layout_config.js,"
    "/usr/share/plasma/shells/org.kde.plasma.desktop/contents/updates/folderview_fix_recursive_screenmapping.js,"
    "/usr/share/plasma/shells/org.kde.plasma.desktop/contents/updates/systemloadviewer_systemmonitor.js,"
    "/usr/share/plasma/shells/org.kde.plasma.desktop/contents/updates/digitalclock_migrate_font_settings.js,"
    "/usr/share/plasma/shells/org.kde.plasma.desktop/contents/updates/unlock_widgets.js,"
    "/usr/share/plasma/shells/org.kde.plasma.desktop/contents/updates/containmentactions_middlebutton.js,"
    "/usr/share/plasma/shells/org.kde.plasma.desktop/contents/updates/maintain_existing_desktop_icon_sizes.js,"
    "/usr/share/plasma/shells/org.kde.plasma.desktop/contents/updates/keyboardlayout_migrateiconsetting.js,"
    "/usr/share/plasma/shells/org.kde.plasma.desktop/contents/updates/digitalclock_rename_timezonedisplay_key.js,"
    "/usr/share/plasma/shells/org.kde.plasma.desktop/contents/updates/klipper_clear_config.js"
)


def render(tokens: dict) -> str:  # noqa: ARG001 - tokens kept for interface stability, see below
    """
    Render a complete, ready-to-install plasma-org.kde.plasma.desktop-appletsrc file.

    Args:
        tokens: Validated token dictionary (see design/validate.py). Not read by this
            function: live testing (see the module docstring's "SECOND FILE DISCOVERED"
            note) found that appletsrc carries no panel-thickness or geometry key at
            all - only WHICH containments/applets exist, their type/edge and their
            order, none of which any current token varies. `tokens` stays a parameter
            (the locked signature) so a future token that genuinely maps onto this file
            (a new widget toggle, for example) can be read here without an interface
            change; today the file's content is identical for every valid tokens.json.

    Returns:
        The complete appletsrc content, exactly as specified in the module docstring's
        REVISED CONTRACT, using the real ini keys verified live against Plasma 6.7.5 in
        the project's guest image (see the module docstring for how to find them without
        guessing).
    """
    lines: list[str] = []

    lines.append("# Panel layout, desktop containment and default context-menu actions,")
    lines.append("# generated from design tokens - do not edit by hand.")
    lines.append("#")
    lines.append("# Structure verified live against Plasma 6.7.5 in the project's guest image: applying")
    lines.append("# the equivalent panel layout once through org.kde.PlasmaShell.evaluateScript and reading")
    lines.append("# back the resulting ~/.config/plasma-org.kde.plasma.desktop-appletsrc gave the exact")
    lines.append("# Containment/Applets/AppletOrder keys below - nothing here is a guessed key name.")
    lines.append("#")
    lines.append("# Panel THICKNESS and floating/fit-to-content/centred behaviour are NOT stored in this")
    lines.append("# file - they live in plasmashellrc's [PlasmaViews] sections instead (see")
    lines.append("# design/generators/plasma_layout.py's render_view_settings() and the matching")
    lines.append("# packages/kuura-shell skel install of /etc/skel/.config/plasmashellrc).")
    lines.append("")

    lines.append(_ACTION_PLUGINS)
    lines.append("")

    # ---- Desktop containment (plugin=org.kde.plasma.folder) ----
    # ItemGeometries-*/ItemGeometriesHorizontal are icon-position caches; empty is the
    # verified-live default for a session with no manually arranged desktop icons.
    lines.append(f"[Containments][{_DESKTOP_ID}]")
    lines.append("ItemGeometries-1280x720=")
    lines.append("ItemGeometriesHorizontal=")
    lines.append(f"activityId={_ACTIVITY_ID}")
    lines.append("formfactor=0")
    lines.append("immutability=1")
    lines.append("lastScreen=0")
    lines.append("location=0")
    lines.append("plugin=org.kde.plasma.folder")
    lines.append("wallpaperplugin=org.kde.image")
    lines.append("")

    # ---- Top panel (plugin=org.kde.panel, location=3 == TopEdge) ----
    # location's real enum values were read back live, not recalled: 3 = top edge,
    # 4 = bottom edge (used below for the shelf panel) - confirmed because the OLD
    # stock bottom panel that pre-existed in every test boot already showed location=4,
    # and the NEW top panel this generator's predecessor script created showed
    # location=3, in the same live appletsrc read-back.
    lines.append(f"[Containments][{_TOP_PANEL_ID}]")
    lines.append("activityId=")
    lines.append("formfactor=2")
    lines.append("immutability=1")
    lines.append("lastScreen=0")
    lines.append("location=3")
    lines.append("plugin=org.kde.panel")
    lines.append("wallpaperplugin=org.kde.image")
    lines.append("")

    # Widgets, left to right == AppletOrder order (confirmed live: AppletOrder lists
    # applet ids in exactly the order they were addWidget()-called / appear on screen).
    for applet_id, widget in zip(_TOP_APPLET_IDS, _TOP_WIDGETS, strict=True):
        lines.append(f"[Containments][{_TOP_PANEL_ID}][Applets][{applet_id}]")
        lines.append("immutability=1")
        lines.append(f"plugin={widget}")
        lines.append("")
        # Per-applet Configuration (popup sizes, kickoff's favoritesPortedToKAstats,
        # the system tray's own extraItems/knownItems list of sub-applets) is left out
        # entirely - live testing showed these are populated by each applet's OWN
        # first-run defaults regardless of whether the containment was created live via
        # evaluateScript or read from a saved config for the first time, so hand-
        # authoring them here would just be duplicating the format's own default.

    lines.append(f"[Containments][{_TOP_PANEL_ID}][General]")
    lines.append("AppletOrder=" + ";".join(str(i) for i in _TOP_APPLET_IDS))
    lines.append("")

    # ---- Bottom / shelf panel (plugin=org.kde.panel, location=4 == BottomEdge) ----
    lines.append(f"[Containments][{_BOTTOM_PANEL_ID}]")
    lines.append("activityId=")
    lines.append("formfactor=2")
    lines.append("immutability=1")
    lines.append("lastScreen=0")
    lines.append("location=4")
    lines.append("plugin=org.kde.panel")
    lines.append("wallpaperplugin=org.kde.image")
    lines.append("")

    lines.append(f"[Containments][{_BOTTOM_PANEL_ID}][Applets][{_BOTTOM_APPLET_ID}]")
    lines.append("immutability=1")
    lines.append(f"plugin={_SHELF_WIDGET}")
    lines.append("")

    lines.append(f"[Containments][{_BOTTOM_PANEL_ID}][General]")
    lines.append(f"AppletOrder={_BOTTOM_APPLET_ID}")
    lines.append("")

    lines.append("[ScreenMapping]")
    lines.append("itemsOnDisabledScreens=")

    return "\n".join(lines) + "\n"


def render_view_settings(tokens: dict) -> str:
    """
    Render a complete, ready-to-install plasmashellrc file for the two new panels.

    Discovered live while implementing the appletsrc contract above (see the module
    docstring's "SECOND FILE DISCOVERED" note): panel thickness and the floating/
    fit-to-content/centred behaviour this project's contract asks for are stored here,
    under `[PlasmaViews][Panel <id>]` / `[PlasmaViews][Panel <id>][Defaults]`, keyed by
    the SAME containment ids `render()` mints for the two panels - not in appletsrc.

    Args:
        tokens: Validated token dictionary (see design/validate.py). Reads
            tokens["panel"]["menubar_height"] (top panel thickness) and
            tokens["panel"]["shelf_icon"] (bottom/shelf panel thickness - the closest
            real proxy for "icon size": Icons-Only Task Manager has no separate
            icon-size key on this Plasma version, but sizes its icons to fill the
            panel's own thickness). tokens["panel"]["shelf_margin"] and
            tokens["panel"]["shelf_hover_scale"] have no equivalent key anywhere in
            this file either (confirmed live the same way as the appletsrc keys) and
            are therefore not read.

    Returns:
        The complete plasmashellrc content: one `[PlasmaViews][Panel <id>]` /
        `[PlasmaViews][Panel <id>][Defaults]` pair per panel, plus the `[Updates]`
        block that marks this Plasma version's own config-migration scripts as already
        performed (the same precedent the V2 test harness's own now-removed
        `harness/vm/guest/skel/.config/plasmashellrc` set for its shipped-complete
        stock panel - see the module docstring's "NOTE ON THE TEST HARNESS'S OWN
        guest/skel").
    """
    menubar_height = tokens["panel"]["menubar_height"]
    shelf_icon = tokens["panel"]["shelf_icon"]

    lines: list[str] = []
    lines.append("# Panel view settings (thickness, floating/fit-to-content) and the list of")
    lines.append("# layout migrations that count as already applied. Because the layout file is")
    lines.append("# shipped complete, the migration scripts of the shell must not run against it;")
    lines.append("# listing them here marks them as done (same precedent as the screenshot")
    lines.append("# harness's own harness/vm/guest/skel/.config/plasmashellrc).")

    lines.append(f"[PlasmaViews][Panel {_TOP_PANEL_ID}]")
    lines.append("floating=1")
    lines.append("shell=org.kde.plasma.desktop")
    lines.append("")
    lines.append(f"[PlasmaViews][Panel {_TOP_PANEL_ID}][Defaults]")
    lines.append(f"thickness={menubar_height}")
    lines.append("")

    # panelLengthMode=1 is the one key (confirmed live by diffing this panel's section
    # against the top panel's, which does NOT get this key) that makes a floating panel
    # shrink to its widgets' content width instead of filling the screen; Plasma then
    # centres a "fit" floating panel horizontally on its own, with no separate stored
    # alignment key anywhere - none was ever observed in either config file.
    lines.append(f"[PlasmaViews][Panel {_BOTTOM_PANEL_ID}]")
    lines.append("floating=1")
    lines.append("panelLengthMode=1")
    lines.append("shell=org.kde.plasma.desktop")
    lines.append("")
    lines.append(f"[PlasmaViews][Panel {_BOTTOM_PANEL_ID}][Defaults]")
    lines.append(f"thickness={shelf_icon}")
    lines.append("")

    lines.append("[Updates]")
    lines.append(f"performed={_UPDATES_PERFORMED}")

    return "\n".join(lines) + "\n"


def render_activities(tokens: dict) -> str:  # noqa: ARG001 - tokens kept for interface stability
    """
    Render a complete, ready-to-install kactivitymanagerdrc naming the one activity
    the desktop containment above (render()) refers to.

    Discovered while packaging and booting the REAL image (not just applying the
    panel script by hand in a live session - see the module docstring's "THIRD FILE"
    note): render()'s desktop containment carries a fixed `activityId`, and without a
    matching kactivitymanagerdrc shipped alongside it, kactivitymanagerd invents its
    OWN unrelated activity id the first time it runs, leaving the desktop containment
    referring to an activity nothing else knows about.

    Args:
        tokens: Validated token dictionary (see design/validate.py). Not read: the
            activity id is a fixed generator constant (`_ACTIVITY_ID`), not a design
            token - kept for the same interface-stability reason as render()'s own
            unused `tokens` parameter.

    Returns:
        The complete kactivitymanagerdrc content: one `[activities]` entry naming
        `_ACTIVITY_ID` "Default", and `[main] currentActivity=` set to the same id -
        the exact shape `harness/vm/guest/skel/.config/kactivitymanagerdrc` already
        used for the V2 test harness's own stock layout (see that file's own header
        comment: "the id must also be written into the desktop layout... both must
        stay equal"), reused here with this generator's own id instead.
    """
    lines = [
        "# The one activity of the session. Its id is also written into the desktop layout",
        "# (plasma-org.kde.plasma.desktop-appletsrc, render() in this same generator module);",
        "# both must stay equal, or the desktop containment refers to an activity that does",
        "# not exist.",
        "[activities]",
        f"{_ACTIVITY_ID}=Default",
        "",
        "[main]",
        f"currentActivity={_ACTIVITY_ID}",
    ]
    return "\n".join(lines) + "\n"
