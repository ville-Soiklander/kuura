"""
Generate the SDDM (login screen) greeter theme's `Main.qml` and `theme.conf`
from design/tokens.json (Vaihe 6, the SDDM sub-task of "Sovellustason
viimeistely" - its own separate work queue item, alongside but independent of
notifications/shutdown-dialog/lock-screen).

SCOPE DECISION - a self-contained QQC2 greeter, NOT a recoloured fork of
plasma-desktop's own Breeze SDDM theme (Main.qml/Login.qml/Background.qml at
/usr/share/sddm/themes/breeze/, confirmed live against the pinned snapshot's
plasma-desktop 6.7.5-1 tag v6.7.5 on invent.kde.org). Breeze's real Login.qml
draws its actual widget colours (password field background, focus ring, panel
tint) from `Kirigami.Theme.colorSet: Complementary`, which Kirigami resolves at
runtime from a KDE colour scheme loaded from the SDDM SYSTEM ACCOUNT's own
`kdeglobals` (confirmed against sddm-kcm's own real source, sddmkcm.cpp: its
"Apply Plasma Settings" action writes color-scheme/cursor/font values through a
root KAuth helper to `/etc/sddm.conf.d/kde_settings.conf` PLUS the sddm system
user's own home config - NOT anything inside the theme directory itself).
Forking Breeze's QML but shipping our own palette would therefore need this
project to ALSO install files into the sddm system account's home directory at
package time - a materially bigger, less-tested, more invasive mechanism than
"install a themed QML directory", and arguably lock-screen/notification
territory (KDE's colour-scheme plumbing is shared machinery) this task's own
scope excludes. Real-world precedent also points the other way: popular
community "themed" SDDM reskins (sddm-chili, sddm-sugar-candy) do NOT reuse
Breeze's Login.qml either - they ship self-contained QML reading their own
colours from theme.conf, which is the pattern followed here.

Confirmed real, current facts this file is built on (research pass against the
pinned sddm 0.21.0-7 / plasma-desktop 6.7.5-1, not guessed):
  - Theme layout: a directory under /usr/share/sddm/themes/<name>/ with
    Main.qml as the fixed entry point, plus theme.conf (shipped defaults) and
    theme.conf.user (an optional, real SDDM overlay file - keys present there
    override the same key in theme.conf, confirmed via sddm-kcm's own
    "theme.conf.user/General/background" write target). [General] is the real
    section header Breeze's own theme.conf.cmake uses.
  - The `config` object's real, confirmed accessor API: config.stringValue(key)
    / config.intValue(key) / config.realValue(key) / config.boolValue(key)
    (sddm/sddm wiki, "Theming"). Used below for exactly the small, deliberate
    subset of values this theme leaves runtime-overridable (see
    render_theme_conf()'s own docstring) - every other token (radius, font
    family/size beyond body, secondary/tertiary colours) is baked into Main.qml
    as a literal at generation time instead, like every other generator in
    this package bakes its own target format's values.
  - The `sddm` proxy object's real, confirmed surface (same source):
    properties hostname/canPowerOff/canReboot/canSuspend/canHibernate/
    canHybridSleep; methods powerOff()/reboot()/suspend()/hibernate()/
    hybridSleep()/login(user, password, sessionIndex); signals loginFailed()/
    loginSucceeded(). Cross-checked against plasma-desktop's own real Main.qml
    at v6.7.5, which calls exactly these (e.g. `sddm.login(username, password,
    sessionButton.currentIndex)`, `Connections { target: sddm; function
    onLoginFailed() {...} }`).
  - Data models, real confirmed properties (same two sources): `userModel`
    (name, realName, homeDir, icon, lastIndex, lastUser, count); `sessionModel`
    (file, name, exec, comment, lastIndex, count). A QML ListView delegate's
    `model.<role>` access (e.g. `model.name`) for these is standard, documented
    Qt model/view behaviour, not SDDM-specific.
  - QML import surface used below is deliberately limited to plain `QtQuick`,
    `QtQuick.Controls` and `QtQuick.Layouts` - the core QML modules every Qt6
    SDDM greeter already needs to run AT ALL, regardless of theme (SDDM's own
    Qt6 greeter binary requires qt6-declarative). This avoids the entire
    Kirigami/PlasmaComponents3/system-palette question above and any
    dependency on plasma-desktop's own theme-local `org.kde.breeze.components`
    QML module (whose resolution mechanism - a system-installed QML plugin vs.
    a theme-local qmldir - this research pass could not pin down with
    certainty; not needed since this theme never imports it).

Deliberately OUT of scope for v1 (bounded scope, not a silent gap - flagged in
this change's own handback/report too): the on-screen virtual keyboard
(Breeze's VirtualKeyboardLoader), a keyboard-layout switcher, Caps Lock
notice (would need the `org.kde.plasma.private.keyboardindicator` QML module -
real and confirmed available, but an extra import surface not worth it for one
cosmetic notice on a screen this sensitive), RTL layout mirroring, and
per-monitor background painting for multi-head setups (the root Item is a
plain `anchors.fill: parent`, which is correct for the single-output harness
VM and any single-monitor real install; a true multi-monitor install would see
the background stretched across the combined virtual desktop rather than
tiled per screen - cosmetic only, does not block login).

This file is NOT a pre-locked interface handed to a farm agent (unlike the
generators design/generate.py's own manifest enumerates) - it was designed and
implemented together in one pass for this task. Only the standard library and
`.colors` may be used; never hand-copy a token value here.
"""

from __future__ import annotations

from .colors import to_hex_rgb, to_qml

# The five text/background colour tokens embedded as QML literals (baked at
# generation time). "background" and "accent" are deliberately NOT here - they
# are the two colour keys this theme instead reads back from theme.conf at
# greeter runtime (see render_theme_conf()'s own docstring for why those two
# and not more), so Main.qml reads them through `config.stringValue()` instead
# of a literal.
_LITERAL_COLOR_KEYS = (
    "surface",
    "surface_alt",
    "text",
    "text_secondary",
    "separator",
    "accent_text",
    "error",
)


def _check_mode(mode: str) -> None:
    """Raise ValueError with the same message shape every other generator uses."""
    if mode not in ("light", "dark"):
        raise ValueError("mode must be 'light' or 'dark'")


def render_theme_conf(tokens: dict, mode: str, name: str) -> str:
    """
    Render `theme.conf`: the small, real, SDDM-native override surface for
    this theme (read back at greeter runtime via the confirmed `config`
    object - see module docstring).

    WHY only "background"/"accent"/"fontSize" and not the full palette: these
    three are the values a system administrator most plausibly wants to tweak
    post-install without touching this generator/rebuilding the package
    (matching SDDM's own real theme.conf/theme.conf.user layering, which
    exists for exactly that kind of override). Every other design token
    (radius, secondary/tertiary colours, the rest of the type scale) is baked
    into Main.qml directly instead, like every other generator in this
    package bakes its own target format's values - see render_main_qml()'s
    own docstring for the split.

    Args:
        tokens: Validated token dictionary (design/validate.py's load_tokens()).
        mode: "light" or "dark" - selects which of tokens["color"] feeds
            "background"/"accent" below. The SDDM greeter itself never
            switches mode at runtime (see render_main_qml()'s own docstring
            for why a login screen is pinned to one fixed mode); this
            argument exists so the choice is a real, testable one rather than
            a hard-coded "dark" inside this function, matching how every
            mode-dependent generator in this package validates its own
            argument the same way.
        name: Theme name; unused by theme.conf's own content (kept for CLI/
            signature parity with every other generator's own
            (tokens, mode, name) shape, mirroring generators.firefox_theme's
            own "accepted but unused" precedent).

    Returns:
        The complete `theme.conf` content ("[General]" plus three
        "key=value" lines, in this exact order: background, accent,
        fontSize), ending with exactly one trailing newline.

    Raises:
        ValueError: if mode is neither "light" nor "dark".
    """
    _check_mode(mode)
    del name  # unused - see docstring

    palette = tokens["color"][mode]
    lines = [
        "[General]",
        f"background={to_hex_rgb(palette['window'])}",
        f"accent={to_hex_rgb(palette['accent'])}",
        f"fontSize={tokens['type']['size']['body']}",
    ]
    return "\n".join(lines) + "\n"


def render_main_qml(tokens: dict, mode: str, name: str) -> str:
    """
    Render `Main.qml`: the self-contained SDDM greeter UI (background, clock,
    user list, password field, session picker, power buttons) - see module
    docstring for the scope decision and the confirmed real QML API this
    relies on.

    Args:
        tokens: Validated token dictionary (design/validate.py's load_tokens()).
        mode: "light" or "dark" - which palette is baked into the literal
            colours below (everything except "background"/"accent", which
            Main.qml instead reads from theme.conf at runtime - see
            render_theme_conf()'s own docstring). A login screen cannot react
            to the desktop session's own light/dark toggle (the greeter runs
            before any user session, and therefore before that preference
            even exists) - see design/generate_sddm.py's own module docstring
            for which one fixed mode this project's CLI actually renders and
            why. This argument stays real and validated rather than a
            decorative/ignored one, so a caller other than that CLI (a test,
            or a future revision that reconsiders the fixed-mode choice) gets
            the mode it actually asked for.
        name: Theme name; unused by the greeter UI itself (Breeze's own
            theme.conf.cmake default already ships `showlogo=hidden` - even
            KDE's own theme hides a logo by default - so this theme has no
            wordmark/logo either; kept for CLI/signature parity, mirroring
            generators.firefox_theme's "no visible branding" precedent).

    Returns:
        The complete `Main.qml` content, ending with exactly one trailing
        newline.

    Raises:
        ValueError: if mode is neither "light" nor "dark".
    """
    _check_mode(mode)
    del name  # unused - see docstring

    palette = tokens["color"][mode]
    radius = tokens["radius"]
    type_tokens = tokens["type"]
    motion = tokens["motion"]

    literal_colors = "\n".join(
        f"    readonly property color color{_pascal(key)}: \"{to_qml(palette[key])}\""
        for key in _LITERAL_COLOR_KEYS
    )

    lines = [
        "import QtQuick",
        "import QtQuick.Controls as QQC2",
        "import QtQuick.Layouts",
        "",
        "// Main.qml - generated from design tokens, do not edit.",
        "// Pinned target: SDDM 0.21.0 (docs/VERSIONS.md). Self-contained greeter -",
        "// see design/generators/sddm_theme.py's own module docstring for the real,",
        "// confirmed sddm/userModel/sessionModel/config API surface used below and",
        "// why plasma-desktop's own Breeze Login.qml is deliberately not reused.",
        "Item {",
        "    id: root",
        "    anchors.fill: parent",
        "",
        "    // ---- Palette: \"background\"/\"accent\" stay runtime-overridable via",
        "    // theme.conf/theme.conf.user (config.stringValue - confirmed real SDDM",
        "    // API); every other colour below is a literal baked from design/tokens.json",
        "    // at generation time, like every other generator in this package. ----",
        "    readonly property color colorWindow: config.stringValue(\"background\")",
        "    readonly property color colorAccent: config.stringValue(\"accent\")",
        literal_colors,
        "",
        "    // ---- Metrics: radius/type/motion tokens, baked as literals. ----",
        f"    readonly property int radiusWindow: {radius['window']}",
        f"    readonly property int radiusField: {radius['field']}",
        f"    readonly property int radiusButton: {radius['button']}",
        f"    readonly property int radiusMenu: {radius['menu']}",
        f"    readonly property string fontFamily: \"{type_tokens['family_ui']}\"",
        "    readonly property int fontSizeBody: config.intValue(\"fontSize\")",
        f"    readonly property int fontSizeTitle: {type_tokens['size']['title']}",
        f"    readonly property int fontSizeHeader: {type_tokens['size']['header']}",
        f"    readonly property int transitionMs: {motion['duration']['fast']}",
        "",
        "    Rectangle {",
        "        anchors.fill: parent",
        "        color: root.colorWindow",
        "    }",
        "",
        "    // Clock: no external module needed, just the current time re-read once a",
        "    // second - a plain, low-risk touch matching Breeze's own greeter (which",
        "    // shows one too), not a functional login requirement.",
        "    Text {",
        "        id: clock",
        "        anchors.horizontalCenter: parent.horizontalCenter",
        "        y: Math.round(parent.height * 0.12)",
        "        color: root.colorText",
        "        font.family: root.fontFamily",
        "        font.pixelSize: root.fontSizeHeader",
        "        text: Qt.formatTime(new Date(), \"hh:mm\")",
        "",
        "        Timer {",
        "            interval: 1000",
        "            running: true",
        "            repeat: true",
        "            onTriggered: clock.text = Qt.formatTime(new Date(), \"hh:mm\")",
        "        }",
        "    }",
        "",
        "    // ---- Login card: user list, password field, session picker, power",
        "    // buttons. userModel/sessionModel/sddm are the real, confirmed SDDM",
        "    // greeter context objects (see module docstring); no other context",
        "    // object or role name beyond the ones confirmed there is used below. ----",
        "    Rectangle {",
        "        id: card",
        "        width: Math.min(360, root.width - 64)",
        "        height: Math.min(columnLayout.implicitHeight + 48, root.height - 96)",
        "        anchors.centerIn: parent",
        "        radius: root.radiusWindow",
        "        color: root.colorSurface",
        "        border.width: 1",
        "        border.color: root.colorSeparator",
        "",
        "        ColumnLayout {",
        "            id: columnLayout",
        "            anchors.fill: parent",
        "            anchors.margins: 24",
        "            spacing: 12",
        "",
        "            ListView {",
        "                id: userListView",
        "                Layout.fillWidth: true",
        "                Layout.preferredHeight: Math.min(contentHeight, 160)",
        "                clip: true",
        "                model: userModel",
        "                currentIndex: userModel.lastIndex >= 0 ? userModel.lastIndex : 0",
        "                // Real userModel property (module docstring); pre-selects the",
        "                // account name shown for the initially highlighted row below.",
        "                property string currentName: userModel.lastUser",
        "",
        "                delegate: Rectangle {",
        "                    width: userListView.width",
        "                    height: 40",
        "                    radius: root.radiusButton",
        "                    color: ListView.isCurrentItem ? root.colorAccent : \"transparent\"",
        "",
        "                    Text {",
        "                        anchors.verticalCenter: parent.verticalCenter",
        "                        anchors.left: parent.left",
        "                        anchors.leftMargin: 12",
        "                        // model.name/model.realName: real, confirmed userModel",
        "                        // roles (module docstring); realName falls back to name",
        "                        // when the account has no display name set.",
        "                        text: model.realName && model.realName.length > 0 ? model.realName : model.name",
        "                        color: ListView.isCurrentItem ? root.colorAccentText : root.colorText",
        "                        font.family: root.fontFamily",
        "                        font.pixelSize: root.fontSizeBody",
        "                    }",
        "",
        "                    MouseArea {",
        "                        anchors.fill: parent",
        "                        onClicked: {",
        "                            userListView.currentIndex = index",
        "                            userListView.currentName = model.name",
        "                            passwordField.forceActiveFocus()",
        "                        }",
        "                    }",
        "                }",
        "            }",
        "",
        "            QQC2.TextField {",
        "                id: passwordField",
        "                Layout.fillWidth: true",
        "                echoMode: TextInput.Password",
        "                placeholderText: qsTr(\"Password\")",
        "                font.family: root.fontFamily",
        "                font.pixelSize: root.fontSizeBody",
        "                Keys.onReturnPressed: root.doLogin()",
        "                Component.onCompleted: forceActiveFocus()",
        "            }",
        "",
        "            QQC2.ComboBox {",
        "                id: sessionCombo",
        "                Layout.fillWidth: true",
        "                // Real, confirmed sessionModel property (module docstring);",
        "                // hidden entirely when there is only one session to choose.",
        "                visible: sessionModel.count > 1",
        "                model: sessionModel",
        "                textRole: \"name\"",
        "                currentIndex: sessionModel.lastIndex >= 0 ? sessionModel.lastIndex : 0",
        "            }",
        "",
        "            QQC2.Button {",
        "                Layout.fillWidth: true",
        "                text: qsTr(\"Log In\")",
        "                onClicked: root.doLogin()",
        "            }",
        "",
        "            Text {",
        "                id: errorText",
        "                Layout.fillWidth: true",
        "                color: root.colorError",
        "                font.family: root.fontFamily",
        "                font.pixelSize: root.fontSizeBody",
        "                text: \"\"",
        "                horizontalAlignment: Text.AlignHCenter",
        "            }",
        "",
        "            RowLayout {",
        "                Layout.fillWidth: true",
        "                spacing: 8",
        "",
        "                // sddm.canSuspend/canReboot/canPowerOff and sddm.suspend()/",
        "                // reboot()/powerOff(): the real, confirmed proxy-object surface",
        "                // (module docstring). Each button hides itself when the",
        "                // corresponding action is unavailable, matching Breeze's own",
        "                // real Main.qml (`enabled: sddm.canHibernate` etc.).",
        "                QQC2.Button {",
        "                    Layout.fillWidth: true",
        "                    text: qsTr(\"Suspend\")",
        "                    visible: sddm.canSuspend",
        "                    onClicked: sddm.suspend()",
        "                }",
        "                QQC2.Button {",
        "                    Layout.fillWidth: true",
        "                    text: qsTr(\"Restart\")",
        "                    visible: sddm.canReboot",
        "                    onClicked: sddm.reboot()",
        "                }",
        "                QQC2.Button {",
        "                    Layout.fillWidth: true",
        "                    text: qsTr(\"Shut Down\")",
        "                    visible: sddm.canPowerOff",
        "                    onClicked: sddm.powerOff()",
        "                }",
        "            }",
        "        }",
        "    }",
        "",
        "    // sddm.login(user, password, sessionIndex): the real, confirmed method",
        "    // signature (module docstring), cross-checked against plasma-desktop's own",
        "    // real Main.qml call site at the pinned tag.",
        "    function doLogin() {",
        "        errorText.text = \"\"",
        "        sddm.login(userListView.currentName, passwordField.text, sessionCombo.currentIndex)",
        "    }",
        "",
        "    // sddm.loginFailed()/loginSucceeded(): the real, confirmed signals",
        "    // (module docstring). A QML binding/property error elsewhere in this file",
        "    // does not stop this Connections block from working - Qt logs a warning",
        "    // and keeps the property at its last value rather than aborting.",
        "    Connections {",
        "        target: sddm",
        "        function onLoginFailed() {",
        "            errorText.text = qsTr(\"Login failed\")",
        "            passwordField.text = \"\"",
        "            passwordField.forceActiveFocus()",
        "        }",
        "        function onLoginSucceeded() {",
        "            root.opacity = 0",
        "        }",
        "    }",
        "",
        "    Behavior on opacity {",
        "        NumberAnimation { duration: root.transitionMs }",
        "    }",
        "}",
    ]

    return "\n".join(lines) + "\n"


def _pascal(key: str) -> str:
    """
    "text_secondary" -> "TextSecondary": the same snake_case-to-PascalCase
    rule design/generators/qml_singleton.py's own _to_camel_case() uses,
    capitalised on the first letter too (that function lowercases the first
    part; every call site here wants it as a suffix after "color" instead).

    Args:
        key: A tokens["color"][mode] key, e.g. "text_secondary".

    Returns:
        The PascalCase form, e.g. "TextSecondary".
    """
    return "".join(part.capitalize() for part in key.split("_"))
