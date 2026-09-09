import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: page
    signal closeSettings()

    Theme { id: t }

    component Row_: RowLayout {
        Layout.fillWidth: true
        spacing: 10
        property alias label: rowLabel.text
        property alias hint: rowHint.text
        ColumnLayout {
            Layout.fillWidth: true
            spacing: 0
            Label { id: rowLabel; color: t.text; font.pixelSize: t.fs(13) }
            Label {
                id: rowHint; color: t.dim; font.pixelSize: t.fs(11)
                visible: text.length > 0
                Layout.fillWidth: true; wrapMode: Text.WordWrap
            }
        }
    }

    component Choice: ComboBox {
        property string tip: ""
        ToolTip.visible: hovered && tip.length > 0
        ToolTip.text: tip
        ToolTip.delay: 500
        HoverHandler { cursorShape: Qt.PointingHandCursor }
        implicitWidth: Math.max(140, t.fs(150))
        font.pixelSize: t.fs(12)
        background: Rectangle {
            radius: 6; color: t.surface; border.color: t.line
        }
        contentItem: Label {
            text: parent.displayText; color: t.text
            font.pixelSize: t.fs(12)
            leftPadding: 10; rightPadding: 24
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }
        delegate: ItemDelegate {
            required property var modelData
            required property int index
            width: parent !== null ? parent.width : 0
            highlighted: parent !== null && parent.currentIndex === index
            background: Rectangle {
                color: highlighted ? t.line : t.surface
            }
            contentItem: Label {
                text: modelData; color: t.text; font.pixelSize: t.fs(12)
                verticalAlignment: Text.AlignVCenter
            }
        }
        popup.background: Rectangle { color: t.surface; border.color: t.line
                                      radius: 6 }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        // ---- header ---------------------------------------------------
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: Math.max(44, t.fs(44))
            color: t.surface
            Rectangle { anchors.bottom: parent.bottom; width: parent.width
                        height: 1; color: t.line }
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 14; anchors.rightMargin: 8
                Label {
                    text: "Settings"; color: t.text
                    font.pixelSize: t.fs(14); Layout.fillWidth: true
                }
                Item {
                    implicitWidth: Math.max(30, t.fs(30))
                    implicitHeight: implicitWidth
                    Rectangle {
                        anchors.fill: parent; radius: 6
                        color: closeMouse.containsMouse ? t.line : "transparent"
                    }
                    Label {
                        anchors.centerIn: parent
                        text: "✕"
                        color: closeMouse.containsMouse ? t.text : t.dim
                        font.pixelSize: t.fs(15)
                    }
                    MouseArea {
                        id: closeMouse
                        anchors.fill: parent; hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: page.closeSettings()
                    }
                    ToolTip.delay: 500
                    ToolTip.visible: closeMouse.containsMouse
                    ToolTip.text: "Back to the main screen"
                }
            }
        }

        // ---- body -----------------------------------------------------
        Flickable {
            Layout.fillWidth: true; Layout.fillHeight: true
            contentWidth: width
            contentHeight: form.implicitHeight + 28
            clip: true
            ScrollBar.vertical: ScrollBar {
                id: scroller
                width: 8
                policy: ScrollBar.AsNeeded
                contentItem: Rectangle {
                    radius: 4
                    color: scroller.pressed ? t.accent
                           : (scroller.hovered ? t.dim : t.line)
                    opacity: scroller.active ? 1.0 : 0.5
                    Behavior on color { ColorAnimation { duration: 120 } }
                    Behavior on opacity { NumberAnimation { duration: 160 } }
                }
                background: Rectangle { color: "transparent" }
            }

            ColumnLayout {
                id: form
                x: 14; width: parent.width - 28; y: 14
                spacing: 16

                SectionLabel { text: "APPEARANCE" }

                // A GridLayout sizes its first column to the widest label,
                // so the three dropdowns line up by construction instead of
                // by hand-tuned padding that breaks at other text sizes.
                GridLayout {
                    Layout.fillWidth: true
                    columns: 2
                    columnSpacing: 12
                    rowSpacing: 10

                    Label {
                        text: "Mode"; color: t.text; font.pixelSize: t.fs(13)
                    }
                    Choice {
                        Layout.fillWidth: true
                        model: bridge.modeNames
                        currentIndex: bridge.modeNames.indexOf(bridge.themeMode)
                        onActivated: bridge.setThemeMode(currentValue)
                        tip: "System follows your desktop's light/dark setting"
                    }

                    Label {
                        text: "Theme"; color: t.text; font.pixelSize: t.fs(13)
                    }
                    Choice {
                        Layout.fillWidth: true
                        model: bridge.themeNames
                        currentIndex: bridge.themeNames.indexOf(bridge.themeName)
                        onActivated: bridge.setThemeName(currentValue)
                        tip: "Accent colour, tinted through the whole interface"
                    }

                    Label {
                        text: "Text size"; color: t.text; font.pixelSize: t.fs(13)
                    }
                    Choice {
                        Layout.fillWidth: true
                        model: bridge.textSizeNames
                        currentIndex: bridge.textSizeNames.indexOf(bridge.textSize)
                        onActivated: bridge.setTextSize(currentValue)
                        tip: "Scales every label and control, not just text"
                    }
                }

                Rectangle { Layout.fillWidth: true; height: 1; color: t.line }

                SectionLabel { text: "STARTUP" }

                Row_ {
                    label: "Start automatically at login"
                    hint: "The knob works with or without this running; " +
                          "autostart just keeps presets and mute to hand."
                    ThemedSwitch {
                        checked: bridge.autostartEnabled
                        onToggled: bridge.setAutostart(checked)
                        ToolTip.visible: hovered
                        ToolTip.delay: 500
                        ToolTip.text: "Start " + bridge.appName
                                      + " automatically when you log in"
                    }
                }

                Rectangle { Layout.fillWidth: true; height: 1; color: t.line }

                SectionLabel { text: "GLOBAL SHORTCUTS" }

                Row_ {
                    label: "Register shortcuts with KDE"
                    hint: bridge.kdeShortcutsAvailable
                          ? "Off by default: nothing is added to your desktop "
                            + "until you ask. Turning this on registers the "
                            + "actions below with no keys bound and opens "
                            + "KDE's shortcut editor so you can assign them. "
                            + "Turning it off removes them again."
                          : "KDE's global shortcut service is not running on "
                            + "this session."
                    ThemedSwitch {
                        enabled: bridge.kdeShortcutsAvailable
                        checked: bridge.kdeShortcutsEnabled
                        onToggled: bridge.setKdeShortcuts(checked)
                        ToolTip.visible: hovered
                        ToolTip.delay: 500
                        ToolTip.text: bridge.kdeShortcutsAvailable
                            ? "Adds these actions to System Settings → Shortcuts"
                            : "Requires KDE Plasma"
                    }
                }

                Flow {
                    Layout.fillWidth: true
                    visible: bridge.kdeShortcutsEnabled
                    spacing: 6
                    Repeater {
                        model: bridge.shortcutActions
                        delegate: Rectangle {
                            required property var modelData
                            radius: 4
                            color: t.surface
                            border.color: t.line
                            implicitWidth: chip.implicitWidth + 16
                            implicitHeight: chip.implicitHeight + 8
                            Label {
                                id: chip
                                anchors.centerIn: parent
                                text: modelData.label
                                color: t.dim
                                font.pixelSize: t.fs(11)
                            }
                        }
                    }
                }

                Button {
                    id: editorButton
                    Layout.alignment: Qt.AlignLeft
                    visible: bridge.kdeShortcutsEnabled
                    implicitWidth: Math.max(150, t.fs(158))
                    implicitHeight: Math.max(30, t.fs(32))
                    onClicked: bridge.openShortcutEditor()
                    HoverHandler { cursorShape: Qt.PointingHandCursor }
                    background: Rectangle {
                        radius: 6
                        color: editorButton.pressed ? t.line : t.surface
                        border.color: t.line
                    }
                    contentItem: Label {
                        text: "Open shortcut editor"
                        color: t.text
                        font.pixelSize: t.fs(12)
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                }

                Rectangle { Layout.fillWidth: true; height: 1; color: t.line }

                SectionLabel { text: "VOLUME LIMIT" }

                Row_ {
                    label: "Ceiling  " + t.fmtDb(bridge.ceilingDb)
                    hint: "Clamps preset recall, wake and unmute. Set it the " +
                          "same way as a preset: turn the knob to the loudest " +
                          "level you want reachable, then capture it."
                    Button {
                        id: ceilingButton
                        implicitWidth: Math.max(178, t.fs(186))
                        implicitHeight: Math.max(30, t.fs(32))
                        enabled: bridge.knobKnown
                        onClicked: bridge.captureCeiling()
                        ToolTip.visible: hovered
                        ToolTip.delay: 500
                        ToolTip.text: "The loudest level presets, wake and "
                                    + "unmute will be allowed to reach"
                        HoverHandler {
                            enabled: ceilingButton.enabled
                            cursorShape: Qt.PointingHandCursor
                        }
                        background: Rectangle {
                            radius: 6
                            color: ceilingButton.pressed ? t.line : t.surface
                            border.color: t.line
                        }
                        contentItem: Label {
                            //: Shows the level it would capture, so the click
                            //: is never a guess.
                            text: bridge.knobKnown
                                  ? "Set from knob to " + t.fmtDb(bridge.knobDb)
                                  : "Waiting for knob…"
                            color: ceilingButton.enabled ? t.text : t.dim
                            font.pixelSize: t.fs(12)
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                            elide: Text.ElideRight
                        }
                    }
                }

                Rectangle { Layout.fillWidth: true; height: 1; color: t.line }

                SectionLabel { text: "LEVEL PRESETS" }

                Label {
                    Layout.fillWidth: true
                    text: "Turn the knob to the level you want, then Store. "
                        + "Levels cannot be typed, so a preset is always "
                        + "something you have just listened to."
                    color: t.dim; font.pixelSize: t.fs(11)
                    wrapMode: Text.WordWrap
                }

                Repeater {
                    model: bridge.presets
                    delegate: RowLayout {
                        required property var modelData
                        Layout.fillWidth: true
                        spacing: 8

                        Rectangle {
                            Layout.alignment: Qt.AlignVCenter
                            implicitWidth: Math.max(10, t.fs(10))
                            implicitHeight: implicitWidth
                            radius: implicitWidth / 2
                            color: bridge.presetColours[modelData.index]
                            border.width: 1
                            border.color: Qt.rgba(0, 0, 0, 0.35)
                        }
                        TextField {
                            Layout.fillWidth: true
                            Layout.minimumWidth: Math.max(70, t.fs(74))
                            text: modelData.name
                            font.pixelSize: t.fs(13)
                            color: t.text
                            background: Rectangle {
                                radius: 6; color: t.surface
                                border.color: parent.activeFocus ? t.accent : t.line
                            }
                            onEditingFinished:
                                bridge.renamePreset(modelData.index, text)
                            ToolTip.visible: hovered
                            ToolTip.delay: 500
                            ToolTip.text: "Rename this preset"
                        }
                        Label {
                            //: What is stored now, as against what the button
                            //: would replace it with.
                            text: modelData.isSet ? t.fmtDb(modelData.db) : "not set"
                            color: modelData.isSet ? t.dim : Qt.darker(t.dim, 1.3)
                            font.pixelSize: t.fs(12)
                            horizontalAlignment: Text.AlignRight
                            Layout.preferredWidth: Math.max(62, t.fs(66))
                        }
                        Button {
                            id: storeButton
                            implicitWidth: Math.max(118, t.fs(124))
                            implicitHeight: Math.max(30, t.fs(32))
                            enabled: bridge.knobKnown
                            onClicked: bridge.capturePreset(modelData.index)
                            ToolTip.visible: hovered
                            ToolTip.delay: 500
                            ToolTip.text: "Replace " + modelData.name
                                        + " with the knob's current position"
                            HoverHandler {
                                enabled: storeButton.enabled
                                cursorShape: Qt.PointingHandCursor
                            }
                            background: Rectangle {
                                radius: 6
                                color: storeButton.pressed ? t.line : t.surface
                                border.color: t.line
                            }
                            contentItem: Label {
                                text: bridge.knobKnown
                                      ? "Store " + t.fmtDb(bridge.knobDb)
                                      : "Store"
                                color: storeButton.enabled ? t.text : t.dim
                                font.pixelSize: t.fs(12)
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                                elide: Text.ElideRight
                            }
                        }
                    }
                }

                Rectangle { Layout.fillWidth: true; height: 1; color: t.line }

                SectionLabel { text: "SPEAKERS" }

                Label {
                    Layout.fillWidth: true
                    text: "Identify turns a speaker's LED red for five "
                        + "seconds. That command also pauses its volume "
                        + "control for those seconds, so avoid changing "
                        + "level while it runs."
                    color: t.dim; font.pixelSize: t.fs(11)
                    wrapMode: Text.WordWrap
                }

                Repeater {
                    model: bridge.speakers
                    delegate: RowLayout {
                        required property var modelData
                        Layout.fillWidth: true
                        spacing: 8

                        Rectangle {
                            Layout.alignment: Qt.AlignVCenter
                            implicitWidth: Math.max(8, t.fs(8))
                            implicitHeight: implicitWidth
                            radius: implicitWidth / 2
                            color: bridge.identifyingSerial === modelData.serial
                                   ? "#e04040"
                                   : (modelData.online ? t.ok : t.dim)
                            Behavior on color { ColorAnimation { duration: 150 } }
                        }

                        TextField {
                            Layout.fillWidth: true
                            Layout.minimumWidth: Math.max(80, t.fs(84))
                            text: modelData.name
                            font.pixelSize: t.fs(13)
                            color: t.text
                            background: Rectangle {
                                radius: 6; color: t.surface
                                border.color: parent.activeFocus ? t.accent : t.line
                            }
                            onEditingFinished:
                                bridge.renameSpeaker(modelData.serial, text)
                            ToolTip.visible: hovered
                            ToolTip.delay: 500
                            ToolTip.text: modelData.model + "  ·  #"
                                        + modelData.serial + "  ·  "
                                        + modelData.role
                        }

                        Button {
                            id: identifyButton
                            implicitWidth: Math.max(78, t.fs(82))
                            implicitHeight: Math.max(30, t.fs(32))
                            enabled: modelData.online
                                     && bridge.identifyingSerial === ""
                            onClicked: bridge.identifySpeaker(modelData.serial)
                            ToolTip.visible: hovered
                            ToolTip.delay: 500
                            ToolTip.text: "Light this speaker's LED red for "
                                        + "five seconds so you can see which "
                                        + "cabinet it is"
                            HoverHandler {
                                enabled: identifyButton.enabled
                                cursorShape: Qt.PointingHandCursor
                            }
                            background: Rectangle {
                                radius: 6
                                color: identifyButton.pressed ? t.line : t.surface
                                border.color: t.line
                            }
                            contentItem: Label {
                                text: bridge.identifyingSerial === modelData.serial
                                      ? "Lit…" : "Identify"
                                color: identifyButton.enabled ? t.text : t.dim
                                font.pixelSize: t.fs(12)
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                            }
                        }
                    }
                }

                Label {
                    Layout.fillWidth: true
                    visible: bridge.speakers.length === 0
                    text: "No speakers found yet."
                    color: t.dim; font.pixelSize: t.fs(12)
                }

                Row_ {
                    label: "Reset speaker state"
                    hint: "Returns every speaker to normal operation. Use "
                        + "this if one stops responding to volume — an "
                        + "interrupted Identify can leave it that way."
                    Button {
                        id: repairButton
                        implicitWidth: Math.max(78, t.fs(82))
                        implicitHeight: Math.max(30, t.fs(32))
                        enabled: bridge.speakers.length > 0
                        onClicked: bridge.repair()
                        ToolTip.visible: hovered
                        ToolTip.delay: 500
                        ToolTip.text: "Clears mute, identify and any frozen "
                                    + "volume stage on every speaker"
                        HoverHandler {
                            enabled: repairButton.enabled
                            cursorShape: Qt.PointingHandCursor
                        }
                        background: Rectangle {
                            radius: 6
                            color: repairButton.pressed ? t.line : t.surface
                            border.color: t.line
                        }
                        contentItem: Label {
                            text: "Reset"
                            color: repairButton.enabled ? t.text : t.dim
                            font.pixelSize: t.fs(12)
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }
                    }
                }

                Rectangle { Layout.fillWidth: true; height: 1; color: t.line }

                SectionLabel { text: "ABOUT" }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 3
                    Label {
                        text: bridge.appName + "  " + bridge.appVersion
                        color: t.text; font.pixelSize: t.fs(14)
                    }
                    Label {
                        text: "Control for Genelec SAM monitors over the GLM adapter."
                        color: t.dim; font.pixelSize: t.fs(11)
                        Layout.fillWidth: true; wrapMode: Text.WordWrap
                    }
                    Label {
                        text: bridge.appHomepage
                        color: homeMouse.containsMouse ? t.accent : t.dim
                        font.pixelSize: t.fs(11)
                        font.underline: homeMouse.containsMouse
                        MouseArea {
                            id: homeMouse
                            anchors.fill: parent; hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: bridge.openHomepage()
                        }
                    }
                }

                Item { implicitHeight: 8 }
            }
        }
    }
}
