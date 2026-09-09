import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: page
    signal openSettings()
    signal requestHide()
    signal requestQuit()

    Theme { id: t }

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
                spacing: 8

                // Dot and label are one hover target: hovering the word
                // "Connected" and getting nothing was needlessly fussy.
                Item {
                    Layout.fillWidth: true
                    Layout.fillHeight: true

                    RowLayout {
                        id: statusRow
                        anchors.left: parent.left
                        anchors.verticalCenter: parent.verticalCenter
                        width: parent.width
                        spacing: 8

                        Rectangle {
                            width: 8; height: 8; radius: 4
                            color: bridge.connected ? t.ok : t.warn
                        }
                        Label {
                            text: bridge.status; color: t.dim
                            font.pixelSize: t.fs(12); Layout.fillWidth: true
                            elide: Text.ElideRight
                        }
                    }

                    HoverHandler { id: statusHover }
                    ToolTip.visible: statusHover.hovered
                    ToolTip.delay: 500
                    ToolTip.text: bridge.adapterInfo
                }
                Label {
                    text: bridge.speakers.length > 0
                          ? bridge.speakers.length + " speakers" : ""
                    color: t.dim; font.pixelSize: t.fs(12)
                }

                // Settings affordance
                Item {
                    implicitWidth: Math.max(30, t.fs(30))
                    implicitHeight: implicitWidth
                    Rectangle {
                        anchors.fill: parent; radius: 6
                        color: cogMouse.containsMouse ? t.line : "transparent"
                    }
                    Label {
                        anchors.centerIn: parent
                        text: "⚙"                      // gear
                        color: cogMouse.containsMouse ? t.text : t.dim
                        font.pixelSize: t.fs(17)
                    }
                    MouseArea {
                        id: cogMouse
                        anchors.fill: parent; hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: page.openSettings()
                    }
                    ToolTip.delay: 500
                    ToolTip.visible: cogMouse.containsMouse
                    ToolTip.text: "Appearance, presets, volume limit and autostart"
                }
            }
        }

        // ---- body -----------------------------------------------------
        ColumnLayout {
            Layout.fillWidth: true; Layout.fillHeight: true
            Layout.margins: 14
            spacing: 12

            Rectangle {
                Layout.fillWidth: true
                implicitHeight: Math.max(140, t.fs(148))
                radius: 10; color: t.surface; border.color: t.line

                ColumnLayout {
                    anchors.centerIn: parent
                    spacing: 2
                    Label {
                        Layout.alignment: Qt.AlignHCenter
                        text: bridge.asleep ? "ASLEEP"
                              : bridge.muted ? "MUTED"
                              : (bridge.knobKnown ? t.fmtDb(bridge.knobDb) : "—")
                        color: bridge.asleep ? t.dim
                               : bridge.muted ? t.warn : t.text
                        font.pixelSize: t.fs(46)
                        //: Font.Black is the heaviest weight Qt defines (900).
                        //: It falls back to the closest available weight if
                        //: the system font has no black cut.
                        font.weight: Font.Black
                    }
                    Label {
                        Layout.alignment: Qt.AlignHCenter
                        text: bridge.asleep
                              ? "knob at " + t.fmtDb(bridge.knobDb)
                                + " — wake to apply"
                              : "hardware volume knob"
                        color: t.dim; font.pixelSize: t.fs(11)
                    }
                    Label {
                        Layout.alignment: Qt.AlignHCenter
                        Layout.maximumWidth: 340
                        visible: bridge.asleep
                        horizontalAlignment: Text.AlignHCenter
                        wrapMode: Text.WordWrap
                        //: ISS wakes a monitor as soon as its input carries a
                        //: signal -- including a digital bit clock with no
                        //: audio at all. Nothing the app does can prevent it,
                        //: and it cannot be detected without sending traffic
                        //: that would itself keep the speakers awake.
                        text: "They will wake on their own if the input "
                            + "signal returns — including a digital clock "
                            + "with no audio playing."
                        color: Qt.darker(t.dim, 1.25)
                        font.pixelSize: t.fs(10)
                    }
                    Item { implicitHeight: 6 }
                    Label {
                        Layout.alignment: Qt.AlignHCenter
                        visible: bridge.micPresent
                        text: "mic " + bridge.micDbSpl.toFixed(1) + " dB SPL"
                        color: t.dim; font.pixelSize: t.fs(12)
                    }
                }
            }

            // Largest target in the window, closest to the readout: the
            // control you reach for in a hurry.
            Button {
                id: muteButton
                Layout.fillWidth: true
                implicitHeight: Math.max(70, t.fs(76))
                enabled: !bridge.asleep
                opacity: enabled ? 1.0 : 0.5
                onClicked: bridge.toggleMute()
                ToolTip.visible: hovered
                ToolTip.delay: 500
                ToolTip.text: bridge.muted
                              ? "Click again to go back to the knob ("
                                + t.fmtDb(bridge.knobDb) + ")"
                              : "Silence the speakers by taking the level to "
                                + "the bottom of the fader"
                HoverHandler {
                    enabled: muteButton.enabled
                    cursorShape: Qt.PointingHandCursor
                }
                background: Rectangle {
                    radius: 10
                    color: bridge.muted
                           ? (muteButton.pressed ? Qt.darker(t.warn, 3.0)
                                                 : Qt.darker(t.warn, 3.6))
                           : (muteButton.pressed ? t.line : t.surface)
                    border.color: bridge.muted ? t.warn : t.line
                    border.width: bridge.muted ? 2 : 1
                    Behavior on color { ColorAnimation { duration: 120 } }
                }
                contentItem: Label {
                    text: bridge.muted ? "UNMUTE" : "MUTE"
                    color: bridge.muted ? t.warn : t.text
                    font.pixelSize: t.fs(20); font.weight: Font.Medium
                    font.letterSpacing: 1.5
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
            }

            SectionLabel { text: "LEVEL PRESETS" }

            GridLayout {
                Layout.fillWidth: true
                columns: 2; columnSpacing: 10; rowSpacing: 10
                Repeater {
                    model: bridge.presets
                    delegate: Rectangle {
                        required property var modelData
                        Layout.fillWidth: true
                        Layout.preferredWidth: 1
                        implicitHeight: Math.max(48, t.fs(56))
                        radius: 8
                        color: bridge.activePreset === modelData.index
                               ? Qt.darker(t.accent, t.isDark ? 2.4 : 0.6)
                               : t.surface
                        border.color: bridge.activePreset === modelData.index
                                      ? t.accent : t.line
                        opacity: modelData.isSet ? 1.0 : 0.55

                        MouseArea {
                            id: presetMouse
                            anchors.fill: parent
                            hoverEnabled: true
                            enabled: modelData.isSet
                            onClicked: bridge.recallPreset(modelData.index)
                            cursorShape: modelData.isSet
                                         ? Qt.PointingHandCursor : Qt.ArrowCursor
                        }
                        ToolTip.visible: presetMouse.containsMouse
                        ToolTip.delay: 500
                        ToolTip.text: modelData.isSet
                            ? (bridge.activePreset === modelData.index
                               ? "Click again to go back to the knob ("
                                 + t.fmtDb(bridge.knobDb) + ")"
                               : "Recall " + modelData.name + " ("
                                 + t.fmtDb(modelData.db)
                                 + "). Touching the knob takes control back.")
                            : "No level stored yet — set one in Settings"
                        // Fixed identity colour, matching the tray icon
                        // for this preset. Never themed.
                        Rectangle {
                            anchors.left: parent.left
                            anchors.leftMargin: 12
                            anchors.verticalCenter: parent.verticalCenter
                            width: Math.max(10, t.fs(10))
                            height: width
                            radius: width / 2
                            color: bridge.presetColours[modelData.index]
                            border.width: 1
                            border.color: Qt.rgba(0, 0, 0, 0.35)
                            opacity: modelData.isSet ? 1.0 : 0.35
                        }

                        ColumnLayout {
                            anchors.centerIn: parent
                            spacing: 1
                            Label {
                                Layout.alignment: Qt.AlignHCenter
                                text: modelData.name; color: t.text
                                font.pixelSize: t.fs(13)
                            }
                            Label {
                                Layout.alignment: Qt.AlignHCenter
                                text: modelData.isSet ? t.fmtDb(modelData.db)
                                                      : "not set"
                                color: t.dim; font.pixelSize: t.fs(12)
                            }
                        }
                    }
                }
            }

            SectionLabel { text: "SPEAKERS" }

            ListView {
                Layout.fillWidth: true; Layout.fillHeight: true
                model: bridge.speakers
                spacing: 6
                clip: true
                delegate: Rectangle {
                    required property var modelData
                    width: ListView.view.width
                    height: Math.max(46, t.fs(52))
                    radius: 8; color: t.surface; border.color: t.line
                    opacity: modelData.online ? 1.0 : 0.45

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 12; anchors.rightMargin: 12
                        spacing: 10
                        Rectangle {
                            width: 6; height: 6; radius: 3
                            color: modelData.online ? t.ok : t.dim
                        }
                        ColumnLayout {
                            spacing: 0
                            Label { text: modelData.name; color: t.text
                                    font.pixelSize: t.fs(13) }
                            Label {
                                text: modelData.role + "  ·  #" + modelData.serial
                                color: t.dim; font.pixelSize: t.fs(11)
                            }
                        }
                        Item { Layout.fillWidth: true }
                        Label {
                            visible: modelData.temperature >= 0
                            text: modelData.temperature + "°C"
                            color: modelData.temperature > 70 ? t.warn : t.dim
                            font.pixelSize: t.fs(12)
                        }
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true; spacing: 8
                ActionButton {
                    text: "Wake"
                    tint: bridge.asleep ? t.accent : t.text
                    tip: "Wake the speakers, holding them silent until they "
                       + "answer — they boot at full level otherwise"
                    onClicked: bridge.wake()
                }
                ActionButton {
                    text: "Sleep"
                    enabled: !bridge.asleep
                    tip: bridge.asleep ? "Already asleep"
                                       : "Put the speakers into standby"
                    onClicked: bridge.sleep()
                }
            }

            RowLayout {
                Layout.fillWidth: true; spacing: 8
                // Close hides to the tray, leaving the app running so presets,
                // mute and the readouts stay available. (Quitting is harmless:
                // the adapter is the standalone master and resumes applying the
                // knob by itself the moment we release the bus.)
                ActionButton {
                    text: "Close"
                    enabled: bridge.trayAvailable
                    tip: bridge.trayAvailable
                         ? "Hide to the tray — keeps running so presets and "
                           + "mute stay available"
                         : "No system tray available on this desktop"
                    onClicked: page.requestHide()
                }
                ActionButton {
                    text: "Quit"
                    tint: t.dim
                    tip: "Exit. The knob keeps working without this app — "
                       + "the adapter takes volume control back"
                    onClicked: page.requestQuit()
                }
            }
        }
    }
}
