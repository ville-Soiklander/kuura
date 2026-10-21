"""
Command line tool: photograph the SAME guest image as stock Plasma, for "before" shots.

    python3 -m harness.shots.stock [--out DIR] [--states a,b] [--display software|gpu]
                                   [--name NAME] [--image-dir DIR]

The README shows before/after pairs: "after" is the product as captured in the goldens,
"before" is what the same machine looks like with Plasma's own defaults. To keep that
comparison fair, this tool boots the very image the goldens come from (same VM, same
programs, same resolution, same window rules, same sample files), then turns every
product setting back to Plasma's default AT RUNTIME, inside the running session, and
captures the selected states with the normal runner (same reset, steps and settle
rules). The image itself is never touched: the VM runs with ``-snapshot``.

What is reverted, and why each item is product-specific (found in the image's own
package file lists and the desktop user's config, see docs/HARNESS_CONTRACT.md,
"Stock 'before' shots"):

* Look-and-feel: ``kdeglobals`` names the product's look-and-feel package. The Breeze
  look-and-feel is applied with ``--resetLayout``, which also sets the Breeze colour
  scheme, icon theme, widget style, Plasma theme, cursor, the Breeze window decoration
  and replaces the product's panel layout (top menubar + floating bottom shelf) with
  Plasma's default single bottom panel and default wallpaper.
* KWin (``kwinrc``): the product's decoration plugin, left-hand button layout, border
  size, corner and Overview tuning, sliding-popup timing and disabled crossfade are
  deleted (so KWin's compiled defaults apply), and the product's glass compositor
  effect is disabled and unloaded. The effect is installed with "enabled by default",
  so deleting a key would not turn it off; ``<id>Enabled=false`` is the only lever.
* Plasma view settings (``plasmashellrc``): the product's panel thickness and floating
  settings are keyed by containment id; they are deleted so a new default panel that
  happens to get the same id cannot inherit them.
* Runner, lock screen, Kvantum and GTK: the free-floating runner, the lock screen
  wallpaper, the Kvantum theme name and the GTK theme names/session variables are
  deleted or unset. None of them is visible in the states this tool captures; they are
  reverted so the session as a whole is stock.

Deliberately NOT reverted (test infrastructure shared with the goldens, so the pair
stays comparable): the harness window rules, animation factor 0, cursor blink off,
disabled splash, wallet, indexing and screen locking, the sample files and the
``LIBGL_ALWAYS_SOFTWARE`` hint.

After the revert the tool READS BACK the result (config values, KWin's own support
information, KWin's effect list, the shell's panels and wallpaper through its scripting
interface) and refuses to capture anything if one item is still product-specific.

Only states whose content can be the same on both sides are offered (see
``COMPARABLE_STATES`` and ``EXCLUDED_STATES``). Only the light mode is captured: the
stock counterpart of the product's light scheme is Breeze Light.

Exit codes as ``harness.shots.capture``: 0 ok, 1 a state failed, 2 environment or
revert problem (nothing captured, or the revert could not be proven).

Standard library only.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from harness.shots import states as states_module
from harness.shots.capture import (
    EXIT_ENVIRONMENT,
    EXIT_FAILED,
    EXIT_OK,
    NAME_PATTERN,
    PROJECT_ROOT,
    STATES_FILE,
    EnvironmentProblem,
    guard_output_dir,
    print_summary,
    sigterm_as_exit,
    split_names,
)
from harness.shots.diff import Rect
from harness.shots.runner import KWIN_EFFECTS_CALL, Runner, StateResult, StepError
from harness.shots.vm import Vm, VmBootError, VmConfig, VmEnvironmentError, host_summary

# Plasma's own defaults that the revert must end at.
STOCK_LOOK_AND_FEEL = "org.kde.breeze.desktop"
STOCK_COLOR_SCHEME = "BreezeLight"
STOCK_DECORATION = "org.kde.breeze"
STOCK_ICON_THEME = "breeze"

# The only mode captured, and its directory name (the goldens' light mode).
STOCK_MODE = states_module.Mode(name="light", scheme="light")

# States whose content is the same program in the same window on both sides.
COMPARABLE_STATES = ("desktop-empty", "files-window", "settings-window", "overview", "search-open", "notification")
DEFAULT_STATES = ("desktop-empty", "files-window", "settings-window", "overview")

# Every other state of states.toml, and why it cannot be a fair "before" picture.
EXCLUDED_STATES = {
    "menubar-open": "its click targets the product's top menubar; stock Plasma has no top panel there",
    "shelf-hover": "its pointer position targets the product's floating shelf, not the stock panel",
    "app-menu-gtk": "GTK apps in this image would show the bare GTK default theme: the image lacks the Breeze GTK theme a stock Plasma install has",
    "gtk4-widget-factory": "same GTK theme gap as app-menu-gtk (and it never settles, see states.toml)",
    "browser-window": "the browser is the product's preconfigured browser (policies, profile), not a stock one",
    "welcome-window": "the welcome window is the product's own program and does not exist in stock Plasma",
}

# Settle masks for the stock layout. WHY not the states.toml masks: those cover the
# product's clock in the top-right corner; the stock clock sits at the right end of the
# bottom panel. The mask only keeps a ticking clock from delaying the settle; the
# picture itself is taken unmasked.
STOCK_MASKS = (Rect(2420, 0, 2560, 55), Rect(2200, 1330, 2560, 1440))

PACMAN = "/usr/bin/pacman"
GDBUS = "gdbus"
KWRITECONFIG = "kwriteconfig6"
KREADCONFIG = "kreadconfig6"

# Script for the shell's scripting interface: report every panel (location, height,
# applet types) and the desktop wallpaper, as one JSON line. Read-only.
LAYOUT_PROBE_SCRIPT = (
    "var out = {panels: [], wallpaper: '', image: ''};"
    "var ps = panels();"
    "for (var i = 0; i < ps.length; ++i) {"
    " var types = [];"
    " var ws = ps[i].widgets();"
    " for (var j = 0; j < ws.length; ++j) { types.push(ws[j].type); }"
    " out.panels.push({location: ps[i].location, height: ps[i].height, widgets: types});"
    "}"
    "var ds = desktops();"
    "if (ds.length > 0) {"
    " out.wallpaper = ds[0].wallpaperPlugin;"
    " ds[0].currentConfigGroup = ['Wallpaper', 'org.kde.image', 'General'];"
    " out.image = String(ds[0].readConfig('Image', ''));"
    "}"
    "print(JSON.stringify(out));"
)

# Applets the stock Breeze layout puts into its panel (a subset is enough to tell it
# from the product's layout) and the one applet only the product's top bar has.
STOCK_PANEL_APPLETS = ("org.kde.plasma.kickoff", "org.kde.plasma.icontasks", "org.kde.plasma.systemtray", "org.kde.plasma.digitalclock")
PRODUCT_ONLY_APPLET = "org.kde.plasma.appmenu"


class StockRevertError(RuntimeError):
    """A revert command failed or the read-back shows a product setting still active."""


@dataclass(frozen=True)
class RevertCommand:
    """
    One program run as the desktop user during the revert.

    Attributes:
        description: What it reverts, for messages and the manifest.
        argv: Program and arguments (no shell).
    """

    description: str
    argv: tuple[str, ...]


@dataclass(frozen=True)
class StockOptions:
    """
    Everything ``run_stock`` needs, already validated.

    Attributes:
        out_dir: Output directory (inside the project tree); shots go to ``<out>/light``.
        states: State names to capture, in states.toml order.
        name: Product name the image was built with (names its packages, plugin ids).
        image_dir: Directory with ``root.img``, ``vmlinuz``, ``initramfs.img``.
        display: ``"software"`` or ``"gpu"`` (as ``harness.shots.capture``).
        states_file: The ``states.toml`` whose state steps are reused.
    """

    out_dir: Path
    states: tuple[str, ...]
    name: str
    image_dir: Path
    display: str = "software"
    states_file: Path = STATES_FILE


@dataclass
class StockEvidence:
    """
    What the session reports after the revert (the read-back, recorded in the manifest).

    Attributes:
        config: ``"file/group/key"`` to its current value ("" when unset).
        decoration: The decoration plugin KWin reports in its support information.
        effect_loaded: Product effect id to whether KWin reports it loaded.
        panels: The shell's panels: ``{"location", "height", "widgets"}`` each.
        wallpaper: Wallpaper plugin of the desktop.
        image: Configured wallpaper image ("" means the look-and-feel default).
    """

    config: dict[str, str] = field(default_factory=dict)
    decoration: str = ""
    effect_loaded: dict[str, bool] = field(default_factory=dict)
    panels: list[dict[str, Any]] = field(default_factory=list)
    wallpaper: str = ""
    image: str = ""


def _delete(file: str, groups: Sequence[str], key: str) -> RevertCommand:
    """
    Build a ``kwriteconfig6 --delete`` command.

    Args:
        file: Config file name (relative to the user's config directory) or absolute path.
        groups: Nested group names, outermost first.
        key: The key to delete.

    Returns:
        The command.
    """
    group_args = [arg for group in groups for arg in ("--group", group)]
    return RevertCommand(f"delete {file} [{']['.join(groups)}] {key}", (KWRITECONFIG, "--file", file, *group_args, "--key", key, "--delete"))


def _write(file: str, groups: Sequence[str], key: str, value: str) -> RevertCommand:
    """
    Build a ``kwriteconfig6`` command that writes one value.

    Args:
        file: Config file name.
        groups: Nested group names, outermost first.
        key: The key.
        value: The value.

    Returns:
        The command.
    """
    group_args = [arg for group in groups for arg in ("--group", group)]
    return RevertCommand(f"set {file} [{']['.join(groups)}] {key}={value}", (KWRITECONFIG, "--file", file, *group_args, "--key", key, value))


def _gdbus(dest: str, path: str, method: str, *args: str) -> tuple[str, ...]:
    """
    Build a session-bus ``gdbus call``.

    Args:
        dest: Bus name.
        path: Object path.
        method: Fully qualified method name.
        *args: Method arguments in gdbus syntax.

    Returns:
        The argument list.
    """
    return (GDBUS, "call", "--session", "--dest", dest, "--object-path", path, "--method", method, *args)


def frost_effect_id(name: str) -> str:
    """
    Return the KWin effect id of the product's glass effect.

    WHY derived from the file name: the effect's metadata has no explicit id, so KWin uses
    the plugin file name (``<name>_frost.so``) without its suffix.

    Args:
        name: Product name.

    Returns:
        The effect id.
    """
    return f"{name}_frost"


def build_revert_plan(name: str, home: str) -> tuple[RevertCommand, ...]:
    """
    List every command that turns the product's per-user settings back to Plasma defaults.

    The order matters: config keys first (so nothing the look-and-feel writes is deleted
    afterwards), the shell's stale panel view settings before the layout reset, the
    crossfade unloaded right before the look-and-feel switch (see
    ``Runner._disable_crossfade`` for the stale-panel bug it avoids), and KWin told to
    reload its configuration last, so the deleted keys and the disabled effect take hold.

    Args:
        name: Product name (plugin ids and theme names derive from it).
        home: The desktop user's home directory in the guest.

    Returns:
        The commands in run order.

    Raises:
        ValueError: ``name`` is not a plain product name or ``home`` not absolute.
    """
    if not NAME_PATTERN.match(name):
        raise ValueError("the product name may only contain lowercase letters, digits, '_' and '-'")
    if not home.startswith("/") or "\x00" in home:
        raise ValueError("the home directory must be an absolute guest path")
    deco = "org.kde.kdecoration2"
    plan: list[RevertCommand] = [
        # kwinrc: the product's decoration and its tuning; KWin's defaults apply once gone.
        _delete("kwinrc", [deco], "library"),
        _delete("kwinrc", [deco], "theme"),
        _delete("kwinrc", [deco], "ButtonsOnLeft"),
        _delete("kwinrc", [deco], "ButtonsOnRight"),
        _delete("kwinrc", [deco], "BorderSizeAuto"),
        _delete("kwinrc", ["Windeco"], "RoundedCorners"),
        _delete("kwinrc", ["Plugins"], "blendchangesEnabled"),
        _delete("kwinrc", ["Effect-overview"], "IgnoreMinimized"),
        _delete("kwinrc", ["Effect-overview"], "OrganizedGrid"),
        _delete("kwinrc", ["Effect-slidingpopups"], "SlideInTime"),
        _delete("kwinrc", ["Effect-slidingpopups"], "SlideOutTime"),
        # The glass effect is "enabled by default": only an explicit false turns it off.
        _write("kwinrc", ["Plugins"], f"{frost_effect_id(name)}Enabled", "false"),
        # Runner and lock screen.
        _delete("krunnerrc", ["General"], "FreeFloating"),
        _delete("kscreenlockerrc", ["Greeter"], "WallpaperPlugin"),
        _delete("kscreenlockerrc", ["Greeter", "Wallpaper", "org.kde.image", "General"], "Image"),
        # Kvantum and GTK theme names (absolute paths: these are not KDE config files).
        _delete(f"{home}/.config/Kvantum/kvantum.kvconfig", ["General"], "theme"),
        _delete(f"{home}/.config/gtk-3.0/settings.ini", ["Settings"], "gtk-theme-name"),
        _delete(f"{home}/.config/gtk-4.0/settings.ini", ["Settings"], "gtk-theme-name"),
        RevertCommand("unset the session's GTK theme and GTK module variables", ("systemctl", "--user", "unset-environment", "GTK_THEME", "GTK_MODULES")),
    ]
    # plasmashellrc: the product layout's two panels are containments 2 and 8 (see the
    # generated layout); their thickness/floating settings must not leak into a new panel.
    for panel in ("Panel 2", "Panel 8"):
        for key in ("floating", "panelLengthMode", "shell"):
            plan.append(_delete("plasmashellrc", ["PlasmaViews", panel], key))
        plan.append(_delete("plasmashellrc", ["PlasmaViews", panel, "Defaults"], "thickness"))
    plan += [
        RevertCommand("unload the colour-switch crossfade before the look-and-feel switch", (*KWIN_EFFECTS_CALL, "org.kde.kwin.Effects.unloadEffect", "blendchanges")),
        RevertCommand(
            "apply the Breeze look-and-feel with its default layout",
            ("plasma-apply-lookandfeel", "--apply", STOCK_LOOK_AND_FEEL, "--resetLayout"),
        ),
        RevertCommand("reload KWin's configuration", _gdbus("org.kde.KWin", "/KWin", "org.kde.KWin.reconfigure")),
        RevertCommand("unload the product's glass effect", (*KWIN_EFFECTS_CALL, "org.kde.kwin.Effects.unloadEffect", frost_effect_id(name))),
    ]
    return tuple(plan)


def revert_to_stock(guest: Any, plan: Sequence[RevertCommand], log: Callable[[str], None] = lambda line: None) -> None:
    """
    Run the revert plan as the desktop user, stopping at the first failure.

    Args:
        guest: The guest agent (``run_as_user``).
        plan: The commands (``build_revert_plan``).
        log: Progress callback.

    Raises:
        StockRevertError: a command did not run or exited non-zero; the message names it.
        ConnectionError: the VM connection is gone.
    """
    for command in plan:
        log(f"  revert: {command.description}")
        try:
            result = guest.run_as_user(list(command.argv), wait_exit=True, timeout=90)
        except (TimeoutError, RuntimeError, ValueError) as exc:
            raise StockRevertError(f"revert step failed: {command.description} ({exc})") from None
        if result is None or result.exit_code != 0:
            code = "no result" if result is None else f"exit {result.exit_code}"
            raise StockRevertError(f"revert step failed: {command.description} ({code})")


def _read(guest: Any, argv: Sequence[str]) -> str:
    """
    Run a read-only query as the desktop user and return its output.

    Args:
        guest: The guest agent.
        argv: The query.

    Returns:
        Standard output without surrounding white space.

    Raises:
        StockRevertError: the query did not run or failed.
    """
    try:
        result = guest.run_as_user(list(argv), wait_exit=True, timeout=60)
    except (TimeoutError, RuntimeError, ValueError) as exc:
        raise StockRevertError(f"could not read back the session state ({argv[0]}: {exc})") from None
    if result is None or result.exit_code != 0:
        raise StockRevertError(f"could not read back the session state ({argv[0]} failed)")
    return result.stdout.strip()


# Config values the read-back reports: (file, groups, key).
READBACK_KEYS: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("kdeglobals", ("KDE",), "LookAndFeelPackage"),
    ("kdeglobals", ("General",), "ColorScheme"),
    ("kdeglobals", ("Icons",), "Theme"),
    ("kdeglobals", ("KDE",), "widgetStyle"),
    ("kwinrc", ("org.kde.kdecoration2",), "library"),
    ("kwinrc", ("org.kde.kdecoration2",), "ButtonsOnLeft"),
    ("kwinrc", ("org.kde.kdecoration2",), "ButtonsOnRight"),
    ("kwinrc", ("org.kde.kdecoration2",), "BorderSizeAuto"),
    ("kwinrc", ("Plugins",), "blendchangesEnabled"),
    ("kwinrc", ("Effect-overview",), "OrganizedGrid"),
    ("krunnerrc", ("General",), "FreeFloating"),
)


def _config_id(file: str, groups: Sequence[str], key: str) -> str:
    """
    Name a config value for the evidence (``file/group/.../key``).

    Args:
        file: Config file.
        groups: Nested groups.
        key: Key.

    Returns:
        The identifier.
    """
    return "/".join([file, *groups, key])


def parse_decoration(support_information: str) -> str:
    """
    Find the decoration plugin in KWin's support information.

    KWin's ``supportInformation`` has a "Decoration" section whose first ``Plugin:`` line
    names the decoration that is really loaded (not merely configured).

    Args:
        support_information: The text KWin returned.

    Returns:
        The plugin id, or "" when the section or line is missing.
    """
    in_section = False
    for line in support_information.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("decoration"):
            in_section = True
            continue
        if in_section and stripped.startswith("Plugin:"):
            return stripped.split(":", 1)[1].strip()
    return ""


def _gdbus_text(reply: str) -> str:
    """
    Unwrap gdbus's printing of a single string reply, ``('text',)``.

    Args:
        reply: gdbus output.

    Returns:
        The string with gdbus's quoting and escapes undone (only ``\\n``, ``\\t``,
        ``\\'`` and ``\\\\``, which is all KWin's and the shell's text uses).

    Raises:
        StockRevertError: the reply is not a single string.
    """
    text = reply.strip()
    if not (text.startswith("('") or text.startswith('("')) or not text.endswith(",)"):
        raise StockRevertError("unexpected D-Bus reply while reading back the session state")
    body = text[2:-3]
    out: list[str] = []
    index = 0
    # WHY a small unescaper instead of ast.literal_eval: gdbus's escaping is GVariant
    # text, not Python; only these escapes occur in the replies read here.
    while index < len(body):
        char = body[index]
        if char == "\\" and index + 1 < len(body):
            following = body[index + 1]
            out.append({"n": "\n", "t": "\t"}.get(following, following))
            index += 2
            continue
        out.append(char)
        index += 1
    return "".join(out)


def read_stock_evidence(guest: Any, name: str) -> StockEvidence:
    """
    Read back the session's real state after the revert.

    Args:
        guest: The guest agent.
        name: Product name.

    Returns:
        The evidence.

    Raises:
        StockRevertError: a query failed or returned something unreadable.
    """
    evidence = StockEvidence()
    for file, groups, key in READBACK_KEYS:
        group_args = [arg for group in groups for arg in ("--group", group)]
        evidence.config[_config_id(file, groups, key)] = _read(guest, [KREADCONFIG, "--file", file, *group_args, "--key", key])
    support = _gdbus_text(_read(guest, _gdbus("org.kde.KWin", "/KWin", "org.kde.KWin.supportInformation")))
    evidence.decoration = parse_decoration(support)
    for effect in (frost_effect_id(name), "blur"):
        reply = _read(guest, [*KWIN_EFFECTS_CALL, "org.kde.kwin.Effects.isEffectLoaded", effect])
        evidence.effect_loaded[effect] = reply == "(true,)"
    layout = _gdbus_text(_read(guest, _gdbus("org.kde.plasmashell", "/PlasmaShell", "org.kde.PlasmaShell.evaluateScript", LAYOUT_PROBE_SCRIPT)))
    try:
        data = json.loads(layout.strip().splitlines()[-1])
        evidence.panels = [dict(panel) for panel in data["panels"]]
        evidence.wallpaper = str(data["wallpaper"])
        evidence.image = str(data["image"])
    except (ValueError, KeyError, IndexError, TypeError):
        raise StockRevertError("the desktop shell's layout report could not be read") from None
    return evidence


def check_stock_evidence(evidence: StockEvidence, name: str) -> list[str]:
    """
    Compare the read-back with Plasma's defaults.

    Args:
        evidence: What the session reports.
        name: Product name (anything carrying it is product-specific).

    Returns:
        One message per problem; empty when the session is stock.
    """
    problems: list[str] = []
    config = evidence.config

    def expect(file: str, groups: tuple[str, ...], key: str, allowed: tuple[str, ...]) -> None:
        value = config.get(_config_id(file, groups, key), "")
        if value not in allowed:
            problems.append(f"{_config_id(file, groups, key)} is {value!r}, expected {' or '.join(repr(a) for a in allowed)}")

    # An empty value means "not set", which Plasma reads as its own default. WHY that
    # is accepted even for the look-and-feel: KConfig deletes a key instead of writing a
    # value equal to the compiled default, so applying Breeze (the default package)
    # leaves the key unset - observed in the guest.
    expect("kdeglobals", ("KDE",), "LookAndFeelPackage", (STOCK_LOOK_AND_FEEL, ""))
    expect("kdeglobals", ("General",), "ColorScheme", (STOCK_COLOR_SCHEME, ""))
    expect("kdeglobals", ("Icons",), "Theme", (STOCK_ICON_THEME, ""))
    expect("kdeglobals", ("KDE",), "widgetStyle", ("Breeze", ""))
    expect("kwinrc", ("org.kde.kdecoration2",), "library", (STOCK_DECORATION, ""))
    for key in ("ButtonsOnLeft", "ButtonsOnRight", "BorderSizeAuto"):
        expect("kwinrc", ("org.kde.kdecoration2",), key, ("",))
    expect("kwinrc", ("Plugins",), "blendchangesEnabled", ("",))
    expect("kwinrc", ("Effect-overview",), "OrganizedGrid", ("",))
    expect("krunnerrc", ("General",), "FreeFloating", ("",))
    if evidence.decoration != STOCK_DECORATION:
        problems.append(f"KWin reports decoration {evidence.decoration or 'none'!r}, expected {STOCK_DECORATION!r}")
    if evidence.effect_loaded.get(frost_effect_id(name), True):
        problems.append(f"KWin still reports the product effect {frost_effect_id(name)} loaded")
    if len(evidence.panels) != 1:
        problems.append(f"the shell has {len(evidence.panels)} panels, the stock layout has exactly one")
    for panel in evidence.panels:
        widgets = panel.get("widgets", [])
        if panel.get("location") != "bottom":
            problems.append(f"a panel sits at {panel.get('location')!r}, the stock panel is at the bottom")
        if PRODUCT_ONLY_APPLET in widgets:
            problems.append("a panel still holds the product's global menu applet")
        missing = [applet for applet in STOCK_PANEL_APPLETS if applet not in widgets]
        if missing:
            problems.append(f"the panel lacks stock applets: {', '.join(missing)}")
    if evidence.wallpaper != "org.kde.image":
        problems.append(f"the desktop uses wallpaper plugin {evidence.wallpaper!r}, expected 'org.kde.image'")
    # The default ("" = look-and-feel default "Next") or the Next package itself are stock.
    if evidence.image and "/wallpapers/Next" not in evidence.image:
        problems.append("the desktop wallpaper is not Plasma's default")
    # Catch-all: no reported VALUE may name the product (the effect table is keyed by
    # the product effect's id on purpose, so it is left out of the scan).
    reported = json.dumps([evidence.config, evidence.decoration, evidence.panels, evidence.wallpaper, evidence.image])
    if name in reported:
        problems.append(f"the read-back still mentions {name!r}")
    return problems


def _check_product(guest: Any, name: str) -> None:
    """
    Make sure the image was built as ``name`` (plugin ids derive from it).

    WHY: with a wrong name the effect id would not match, unloading it would be a silent
    no-op and the read-back could not tell; the metapackage ties the name to the image.

    Args:
        guest: The guest agent (``exec`` as root).
        name: Product name.

    Raises:
        StockRevertError: the package is missing or the query failed.
    """
    try:
        result = guest.exec([PACMAN, "-Q", f"{name}-desktop"], timeout=30.0)
    except (TimeoutError, RuntimeError) as exc:
        raise StockRevertError(f"could not check the image's product name ({exc})") from None
    if result.exit_code != 0:
        raise StockRevertError(f"the image was not built as {name!r}; pass --name or set DISTRO_NAME")


def select_states(parsed: states_module.StatesFile, names: Sequence[str] | None) -> list[states_module.State]:
    """
    Pick the states to capture.

    Args:
        parsed: The validated states file.
        names: Requested names, or None for ``DEFAULT_STATES``.

    Returns:
        The states in file order.

    Raises:
        ValueError: a name is unknown, excluded (the message says why) or not light-mode.
    """
    wanted = list(names) if names is not None else list(DEFAULT_STATES)
    by_name = {state.name: state for state in parsed.states}
    for name in wanted:
        if name in EXCLUDED_STATES:
            raise ValueError(f"state {name!r} cannot be a fair stock comparison: {EXCLUDED_STATES[name]}")
        if name not in COMPARABLE_STATES:
            raise ValueError(f"state {name!r} is not offered for stock shots (offered: {', '.join(COMPARABLE_STATES)})")
        if name not in by_name:
            raise ValueError(f"state {name!r} is not defined in {STATES_FILE.name}")
        if STOCK_MODE.name not in by_name[name].modes:
            raise ValueError(f"state {name!r} is not captured in the light mode")
    return [state for state in parsed.states if state.name in wanted]


def _default_vm(config: VmConfig) -> Vm:
    """
    Build the real VM.

    Args:
        config: The VM configuration.

    Returns:
        A ``Vm`` (not yet started).
    """
    return Vm(config)


def _default_runner(vm: Any, settings: states_module.Settings, work_dir: Path, log: Callable[[str], None]) -> Runner:
    """
    Build the real runner for a booted VM.

    Args:
        vm: The running ``Vm``.
        settings: The ``[settings]`` table.
        work_dir: Scratch directory.
        log: Progress callback.

    Returns:
        The runner.
    """
    return Runner(getattr(vm, "screen", None) or vm.qmp, vm.agent, settings, work_dir, log=log, cpu_probe=vm.agent.cpu_sample)


def _revert_and_prove(vm: Any, runner: Any, options: StockOptions, work_dir: Path, log: Callable[[str], None]) -> StockEvidence:
    """
    Revert the session to stock Plasma, wait for the screen, and prove the result.

    Args:
        vm: The running VM (``agent`` and ``screen``/``qmp``).
        runner: The runner (``settle``).
        options: The options.
        work_dir: Scratch directory for the reference frame.
        log: Progress callback.

    Returns:
        The read-back evidence (all checks passed).

    Raises:
        StockRevertError: a step failed, the screen did not settle, or the read-back
            still shows a product setting.
    """
    guest = vm.agent
    _check_product(guest, options.name)
    screen = getattr(vm, "screen", None) or vm.qmp
    before = work_dir / "before-stock.png"
    screen.screendump(before)
    revert_to_stock(guest, build_revert_plan(options.name, guest.user.home), log)
    # The layout reset must visibly change the screen (the product's panels go away).
    settled = runner.settle(list(STOCK_MASKS), reference=before)
    if not settled.stable:
        raise StockRevertError(f"the desktop did not settle after the revert ({settled.reason})")
    evidence = read_stock_evidence(guest, options.name)
    problems = check_stock_evidence(evidence, options.name)
    if problems:
        raise StockRevertError("the session is not stock after the revert: " + "; ".join(problems))
    log("  revert proven: " + ", ".join(f"{p['location']} panel {p['height']}px" for p in evidence.panels) + f", decoration {evidence.decoration}")
    return evidence


def run_stock(
    options: StockOptions,
    vm_factory: Callable[[VmConfig], Any] = _default_vm,
    runner_factory: Callable[[Any, states_module.Settings, Path, Callable[[str], None]], Any] = _default_runner,
    log: Callable[[str], None] = lambda line: print(line, flush=True),
) -> tuple[int, dict[str, Any]]:
    """
    Boot once, revert to stock Plasma, prove it, and capture the selected states.

    Args:
        options: The validated options.
        vm_factory: Creates the (not yet started) VM; replaced in tests.
        runner_factory: Creates the runner for a started VM; replaced in tests.
        log: Progress callback.

    Returns:
        ``(exit code, manifest)``; the manifest is also written to ``<out>/manifest.json``.

    Raises:
        EnvironmentProblem: bad states file or selection, the VM did not boot, or the
            revert failed or could not be proven (then no state is captured).
    """
    started = time.monotonic()
    try:
        parsed = states_module.load_states(options.states_file)
        chosen = select_states(parsed, list(options.states))
    except ValueError as exc:
        raise EnvironmentProblem(str(exc)) from None
    target = options.out_dir / STOCK_MODE.name
    target.mkdir(parents=True, exist_ok=True)
    for state in chosen:
        # Results of an earlier run must never be mistaken for this run's.
        (target / f"{state.name}.png").unlink(missing_ok=True)
        (target / f"{state.name}.FAILED.png").unlink(missing_ok=True)

    settings = parsed.settings
    config = VmConfig(image_dir=options.image_dir, resolution=settings.resolution, rtc_base=settings.rtc_base, display=options.display)
    manifest: dict[str, Any] = {
        "schema": 1,
        "kind": "stock-plasma",
        "name": options.name,
        "display": options.display,
        "resolution": list(settings.resolution),
        "modes": [STOCK_MODE.name],
        "outcome": "incomplete",
        "reverted": [command.description for command in build_revert_plan(options.name, "/home/user")],
        "results": [],
    }
    results: list[StateResult] = []
    problem: EnvironmentProblem | None = None
    lost = ""
    work_dir = Path(tempfile.mkdtemp(prefix="shots-stock-"))
    try:
        with vm_factory(config) as vm:
            manifest["boot"] = dict(vm.timings)
            runner = runner_factory(vm, settings, work_dir, log)
            log("waiting for the desktop")
            runner.wait_for_desktop(list(STOCK_MASKS))
            log("reverting to stock Plasma")
            evidence = _revert_and_prove(vm, runner, options, work_dir, log)
            manifest["evidence"] = asdict(evidence)
            for state in chosen:
                rel = f"{STOCK_MODE.name}/{state.name}.png"
                if lost:
                    results.append(StateResult(state.name, STOCK_MODE.name, "failed", error=f"not run: {lost}"))
                    continue
                try:
                    results.append(runner.run_state(state, STOCK_MODE, list(STOCK_MASKS), options.out_dir / rel, rel))
                except ConnectionError as exc:
                    lost = f"the VM connection was lost ({exc})"
                    results.append(StateResult(state.name, STOCK_MODE.name, "failed", error=lost))
            manifest["resources"] = vm.resources()
    except (VmEnvironmentError, VmBootError) as exc:
        problem = EnvironmentProblem(str(exc))
    except StepError as exc:
        problem = EnvironmentProblem(f"boot: {exc}")
    except StockRevertError as exc:
        problem = EnvironmentProblem(str(exc))
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

    failed = [r for r in results if r.status != "ok"]
    ok = problem is None and not lost and not failed and len(results) == len(chosen)
    manifest["results"] = [asdict(r) for r in results]
    manifest["host"] = host_summary()
    manifest["total_seconds"] = round(time.monotonic() - started, 1)
    manifest["summary"] = {"total": len(chosen), "ok": len(results) - len(failed), "failed": len(chosen) - (len(results) - len(failed))}
    manifest["outcome"] = "ok" if ok else ("environment-error" if problem else "failed")
    if problem is not None:
        manifest["error"] = str(problem)
    (options.out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    if problem is not None:
        raise problem
    return (EXIT_OK if ok else EXIT_FAILED), manifest


def build_options(args: argparse.Namespace) -> StockOptions:
    """
    Validate parsed command line arguments.

    Args:
        args: The parsed arguments.

    Returns:
        The options.

    Raises:
        ValueError: on a bad name, state list or output directory.
    """
    if not NAME_PATTERN.match(args.name):
        raise ValueError("--name may only contain lowercase letters, digits, '_' and '-'")
    default_out = ".build/shots-stock-gpu" if args.display == "gpu" else ".build/shots-stock"
    out = args.out if args.out is not None else PROJECT_ROOT / default_out
    names = split_names(args.states, "--states")
    return StockOptions(
        out_dir=guard_output_dir(out),
        states=tuple(names) if names is not None else DEFAULT_STATES,
        name=args.name,
        image_dir=args.image_dir,
        display=args.display,
    )


def main(argv: list[str] | None = None) -> int:
    """
    Command line entry point.

    Args:
        argv: Arguments (default ``sys.argv[1:]``).

    Returns:
        The exit code (0, 1 or 2).
    """
    parser = argparse.ArgumentParser(prog="python3 -m harness.shots.stock", description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, help="output directory inside the project tree (default: .build/shots-stock, or .build/shots-stock-gpu with --display gpu)")
    parser.add_argument("--states", help=f"comma separated state names (default: {','.join(DEFAULT_STATES)}; offered: {','.join(COMPARABLE_STATES)})")
    parser.add_argument("--name", default=os.environ.get("DISTRO_NAME", "theme"), help="product name the image was built with (default: $DISTRO_NAME)")
    parser.add_argument("--display", choices=("software", "gpu"), default="software", help="software (default) or gpu (local only, as harness.shots.capture)")
    parser.add_argument("--image-dir", type=Path, default=PROJECT_ROOT / ".build" / "vm", help="directory with root.img, vmlinuz, initramfs.img")
    args = parser.parse_args(argv)
    try:
        options = build_options(args)
        with sigterm_as_exit():
            code, manifest = run_stock(options)
    except (ValueError, EnvironmentProblem) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ENVIRONMENT
    print_summary(manifest)
    return code


if __name__ == "__main__":
    sys.exit(main())
