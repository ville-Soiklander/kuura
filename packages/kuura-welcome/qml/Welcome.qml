// First-login welcome window (docs/WELCOME_CONTRACT.md).
//
// WHY plain QML and no compiled code: the window only shows a few facts and three
// actions, so Qt's own QML runtime is enough. QML cannot start programs or write
// files by itself, therefore every action is reported to the POSIX launcher as one
// line "WELCOME_ACTION <verb> [argument]" on the log output; the launcher validates
// the verb against a fixed list and performs it. Facts the window displays (mode,
// title, key combinations, current setting) arrive as "--name=value" arguments from
// the launcher, so nothing is typed into this file by hand and nothing can drift.
//
// WHY two token singletons: design/generators/qml_singleton.py produces one file per
// mode. Both are bundled and `tk` picks the active one, so the window follows a mode
// change immediately without restarting.
//
// WHY no literal colours or sizes: everything visual comes from `tk` (the generated
// token singleton). Only layout structure (anchors, counts, multiples of the grid
// unit) is written here.
pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import QtQuick.Window
import "tokens/light" as Light
import "tokens/dark" as Dark

Window {
    id: root

    // ---- Launcher-supplied facts ------------------------------------------------

    /**
     * Value of a "--name=value" launcher argument.
     *
     * @param name Argument name without the leading dashes.
     * @param fallback Returned when the argument is absent.
     * @return The argument value or the fallback.
     */
    function arg(name, fallback) {
        const prefix = "--" + name + "=";
        const all = Qt.application.arguments;
        for (let i = 0; i < all.length; i++) {
            if (all[i].indexOf(prefix) === 0)
                return all[i].substring(prefix.length);
        }
        return fallback;
    }

    /**
     * Reports an action to the launcher (see the module comment).
     *
     * @param verb Fixed action name the launcher understands.
     * @param argument Optional single argument for the verb.
     */
    function report(verb, argument) {
        console.log("WELCOME_ACTION " + verb + (argument === undefined ? "" : " " + argument));
    }

    // Unknown or missing mode means light, the same fallback the launcher uses.
    property bool dark: arg("mode", "light") === "dark"
    readonly property var tk: dark ? Dark.Tokens : Light.Tokens

    readonly property string searchKeys: arg("search", "")
    readonly property string overviewKeys: arg("overview", "")

    // ---- Window ------------------------------------------------------------------

    title: arg("title", "")
    color: tk.colorWindow

    // WHY the window starts hidden: Qt Wayland announces the application id when the
    // platform window is created, which happens at the first show. It derives the id
    // from the organisation domain (reversed) plus the executable name, and the QML
    // runtime's own domain would make the shelf show the runtime's identity. So the
    // domain is set from the launcher's --app-domain value first, then the window is
    // shown (see Component.onCompleted). "kuura-welcome" becomes the id
    // "kuura-welcome.qml", which the desktop file names in StartupWMClass.
    visible: false
    Component.onCompleted: {
        const domain = arg("app-domain", "");
        if (domain !== "")
            Qt.application.domain = domain;
        visible = true;
    }

    // Fixed size, no resizing: the width is a multiple of the grid unit and the
    // height follows the content, so the window never clips or leaves gaps.
    readonly property int fixedWidth: tk.spacingGrid * 110
    readonly property int fixedHeight: content.implicitHeight + tk.spacingSection * 2
    width: fixedWidth
    height: fixedHeight
    minimumWidth: fixedWidth
    maximumWidth: fixedWidth
    minimumHeight: fixedHeight
    maximumHeight: fixedHeight
    x: Screen.width / 2 - width / 2
    y: Screen.height / 2 - height / 2

    Shortcut {
        sequence: "Escape"
        onActivated: Qt.quit()
    }

    // ---- Small building blocks ---------------------------------------------------

    component BodyText: Text {
        color: root.tk.colorText
        font.family: root.tk.typeFamilyUi
        font.pixelSize: root.tk.typeSizeBody
        wrapMode: Text.WordWrap
        Layout.fillWidth: true
    }

    component SectionTitle: BodyText {
        font.pixelSize: root.tk.typeSizeTitle
        font.weight: root.tk.typeWeightSemibold
    }

    // One of the two appearance choices; the pair is mutually exclusive.
    component Choice: AbstractButton {
        id: choice
        checkable: true
        autoExclusive: true
        Layout.fillWidth: true
        implicitHeight: root.tk.spacingGrid * 10
        background: Rectangle {
            radius: root.tk.radiusButton
            color: choice.checked ? root.tk.colorAccent : root.tk.colorSurfaceAlt
            border.width: choice.visualFocus ? root.tk.materialEdgeHighlightWidth * 2 : 0
            border.color: root.tk.colorLink
            Behavior on color { ColorAnimation { duration: root.tk.motionDurationFast } }
        }
        contentItem: Text {
            text: choice.text
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            color: choice.checked ? root.tk.colorAccentText : root.tk.colorText
            font.family: root.tk.typeFamilyUi
            font.pixelSize: root.tk.typeSizeBody
            font.weight: root.tk.typeWeightMedium
        }
    }

    component ActionButton: Button {
        id: action
        implicitHeight: root.tk.spacingGrid * 10
        leftPadding: root.tk.spacingSection
        rightPadding: root.tk.spacingSection
        background: Rectangle {
            radius: root.tk.radiusButton
            color: action.highlighted ? root.tk.colorAccent : root.tk.colorSurfaceAlt
            border.width: action.visualFocus ? root.tk.materialEdgeHighlightWidth * 2 : 0
            border.color: root.tk.colorLink
        }
        contentItem: Text {
            text: action.text
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            color: action.highlighted ? root.tk.colorAccentText : root.tk.colorText
            font.family: root.tk.typeFamilyUi
            font.pixelSize: root.tk.typeSizeBody
            font.weight: root.tk.typeWeightMedium
        }
    }

    // One shortcut row: what it does on the left, the key combination on the right.
    component ShortcutRow: RowLayout {
        id: shortcutRow
        property string action
        property string keys
        Layout.fillWidth: true
        BodyText { text: shortcutRow.action }
        Rectangle {
            radius: root.tk.radiusField
            color: root.tk.colorSurfaceAlt
            implicitWidth: keyText.implicitWidth + root.tk.spacingGutter * 2
            implicitHeight: keyText.implicitHeight + root.tk.spacingGrid * 2
            Text {
                id: keyText
                anchors.centerIn: parent
                // An empty value means the launcher found no binding.
                text: shortcutRow.keys !== "" ? shortcutRow.keys : "Not set"
                color: root.tk.colorText
                font.family: root.tk.typeFamilyMono
                font.pixelSize: root.tk.typeSizeCaption
            }
        }
    }

    // ---- Content -----------------------------------------------------------------

    ColumnLayout {
        id: content
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: root.tk.spacingSection
        spacing: root.tk.spacingSection

        ColumnLayout {
            spacing: root.tk.spacingGrid
            BodyText {
                text: root.title
                font.pixelSize: root.tk.typeSizeHeader
                font.weight: root.tk.typeWeightSemibold
            }
            BodyText {
                text: "Glad you are here. These are the few things worth knowing before you start."
                color: root.tk.colorTextSecondary
            }
        }

        ColumnLayout {
            spacing: root.tk.spacingGutter
            SectionTitle { text: "Appearance" }
            RowLayout {
                spacing: root.tk.spacingGutter
                Choice {
                    text: "Light"
                    checked: !root.dark
                    onClicked: {
                        root.dark = false;
                        root.report("scheme", "light");
                    }
                }
                Choice {
                    text: "Dark"
                    checked: root.dark
                    onClicked: {
                        root.dark = true;
                        root.report("scheme", "dark");
                    }
                }
            }
        }

        ColumnLayout {
            spacing: root.tk.spacingGutter
            SectionTitle { text: "Shortcuts" }
            ShortcutRow { action: "Search"; keys: root.searchKeys }
            ShortcutRow { action: "Overview of windows"; keys: root.overviewKeys }
        }

        ColumnLayout {
            spacing: root.tk.spacingGutter
            SectionTitle { text: "Settings" }
            ActionButton {
                text: "Open System Settings"
                Layout.fillWidth: true
                onClicked: root.report("settings")
            }
        }

        Rectangle {
            Layout.fillWidth: true
            implicitHeight: root.tk.materialEdgeHighlightWidth
            color: root.tk.colorSeparator
        }

        RowLayout {
            spacing: root.tk.spacingGutter
            CheckBox {
                id: showBox
                text: "Show this window at login"
                checked: root.arg("show-at-login", "true") !== "false"
                onToggled: root.report("show-at-login", checked ? "true" : "false")
                indicator: Rectangle {
                    implicitWidth: root.tk.spacingGrid * 5
                    implicitHeight: root.tk.spacingGrid * 5
                    x: showBox.leftPadding
                    y: showBox.topPadding + (showBox.availableHeight - height) / 2
                    radius: root.tk.radiusField / 2
                    color: showBox.checked ? root.tk.colorAccent : root.tk.colorSurface
                    border.width: root.tk.materialEdgeHighlightWidth
                    border.color: showBox.visualFocus ? root.tk.colorLink : root.tk.colorSeparator
                    Text {
                        anchors.centerIn: parent
                        visible: showBox.checked
                        text: "✓"
                        color: root.tk.colorAccentText
                        font.pixelSize: root.tk.typeSizeCaption
                    }
                }
                contentItem: Text {
                    text: showBox.text
                    leftPadding: showBox.indicator.width + root.tk.spacingGutter
                    verticalAlignment: Text.AlignVCenter
                    color: root.tk.colorText
                    font.family: root.tk.typeFamilyUi
                    font.pixelSize: root.tk.typeSizeBody
                }
            }
            Item { Layout.fillWidth: true }
            ActionButton {
                id: closeButton
                text: "Close"
                highlighted: true
                focus: true
                onClicked: Qt.quit()
                Keys.onReturnPressed: Qt.quit()
                Keys.onEnterPressed: Qt.quit()
            }
        }
    }
}
