import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ApplicationWindow {
    id: root
    width: 520; height: 720
    minimumWidth: 420; minimumHeight: 600
    visible: true
    title: "Genelec"

    // Dark, Plasma-adjacent. Deliberately restrained: this is a control
    // surface glanced at mid-work, not something to look at.
    readonly property color bg:      "#16181d"
    readonly property color surface: "#1e2128"
    readonly property color line:    "#2c313a"
    readonly property color text:    "#e6e9ef"
    readonly property color dim:     "#8b93a3"
    readonly property color accent:  "#5c9ded"
    readonly property color warn:    "#e0a458"
    readonly property color ok:      "#6cc17f"

    color: bg

    function fmtDb(v) { return (v > -130 ? v.toFixed(1) : "-∞") + " dB" }

    header: ToolBar {
        height: 44
        background: Rectangle { color: root.surface
            Rectangle { anchors.bottom: parent.bottom; width: parent.width
                        height: 1; color: root.line } }
        RowLayout {
            anchors.fill: parent; anchors.leftMargin: 14; anchors.rightMargin: 10
            Rectangle {
                width: 8; height: 8; radius: 4
                color: bridge.connected ? root.ok : root.warn
            }
            Label {
                text: bridge.status; color: root.dim; font.pixelSize: 12
                Layout.fillWidth: true
            }
            ToolButton {
                text: "Rescan"; onClicked: bridge.rediscover()
                contentItem: Label { text: parent.text; color: root.dim
                                     font.pixelSize: 12 }
            }
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 14
        spacing: 14

        // ---- level readout -------------------------------------------
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: 148
            radius: 10
            color: root.surface
            border.color: root.line

            ColumnLayout {
                anchors.centerIn: parent
                spacing: 2

                Label {
                    Layout.alignment: Qt.AlignHCenter
                    text: bridge.muted ? "MUTED"
                                       : (bridge.knobKnown ? root.fmtDb(bridge.knobDb)
                                                           : "—")
                    color: bridge.muted ? root.warn : root.text
                    font.pixelSize: 46
                    font.weight: Font.Light
                }
                Label {
                    Layout.alignment: Qt.AlignHCenter
                    text: "hardware volume knob"
                    color: root.dim; font.pixelSize: 11
                }
                Item { implicitHeight: 6 }
                Label {
                    Layout.alignment: Qt.AlignHCenter
                    visible: bridge.micPresent
                    text: "mic " + bridge.micDbSpl.toFixed(1) + " dB SPL"
                    color: root.dim; font.pixelSize: 12
                }
            }
        }

        // ---- presets --------------------------------------------------
        Label { text: "LEVEL PRESETS"; color: root.dim; font.pixelSize: 10
                font.letterSpacing: 1.2 }

        GridLayout {
            Layout.fillWidth: true
            columns: 2; columnSpacing: 10; rowSpacing: 10

            Repeater {
                model: bridge.presets
                delegate: Rectangle {
                    required property var modelData
                    Layout.fillWidth: true
                    implicitHeight: 68
                    radius: 8
                    color: bridge.activePreset === modelData.index
                           ? Qt.darker(root.accent, 2.4) : root.surface
                    border.color: bridge.activePreset === modelData.index
                                  ? root.accent : root.line

                    MouseArea {
                        anchors.fill: parent
                        enabled: modelData.isSet
                        onClicked: bridge.recallPreset(modelData.index)
                        cursorShape: modelData.isSet ? Qt.PointingHandCursor
                                                     : Qt.ArrowCursor
                    }

                    ColumnLayout {
                        anchors.left: parent.left; anchors.leftMargin: 12
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: 1
                        Label { text: modelData.name; color: root.text
                                font.pixelSize: 13 }
                        Label {
                            text: modelData.isSet ? root.fmtDb(modelData.db)
                                                  : "not set"
                            color: modelData.isSet ? root.dim
                                                   : Qt.darker(root.dim, 1.4)
                            font.pixelSize: 12
                        }
                    }

                    // Capture from the knob. There is deliberately no way to
                    // type a level: you set it with your hand and your ears.
                    Button {
                        anchors.right: parent.right; anchors.rightMargin: 8
                        anchors.verticalCenter: parent.verticalCenter
                        implicitWidth: 52; implicitHeight: 26
                        enabled: bridge.knobKnown
                        onClicked: bridge.capturePreset(modelData.index)
                        background: Rectangle {
                            radius: 5; color: parent.pressed ? root.line
                                                             : "transparent"
                            border.color: root.line
                        }
                        contentItem: Label {
                            text: "Store"; color: root.dim; font.pixelSize: 11
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }
                    }
                }
            }
        }

        Label {
            Layout.fillWidth: true
            text: "Store captures the knob's current position, so a preset is "
                + "always a level you have just heard."
            color: Qt.darker(root.dim, 1.3); font.pixelSize: 11
            wrapMode: Text.WordWrap
        }

        // ---- speakers -------------------------------------------------
        Label { text: "SPEAKERS"; color: root.dim; font.pixelSize: 10
                font.letterSpacing: 1.2 }

        ListView {
            Layout.fillWidth: true; Layout.fillHeight: true
            model: bridge.speakers
            spacing: 6
            clip: true

            delegate: Rectangle {
                required property var modelData
                width: ListView.view.width
                height: 52
                radius: 8
                color: root.surface
                border.color: root.line
                opacity: modelData.online ? 1.0 : 0.45

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 12; anchors.rightMargin: 12
                    spacing: 10

                    Rectangle {
                        width: 6; height: 6; radius: 3
                        color: modelData.online ? root.ok : root.dim
                    }
                    ColumnLayout {
                        spacing: 0
                        Label { text: modelData.name; color: root.text
                                font.pixelSize: 13 }
                        Label {
                            text: modelData.role + "  ·  #" + modelData.serial
                            color: root.dim; font.pixelSize: 11
                        }
                    }
                    Item { Layout.fillWidth: true }
                    Label {
                        visible: modelData.temperature >= 0
                        text: modelData.temperature + "°C"
                        color: modelData.temperature > 70 ? root.warn : root.dim
                        font.pixelSize: 12
                    }
                }
            }
        }

        // ---- actions --------------------------------------------------
        RowLayout {
            Layout.fillWidth: true
            spacing: 8

            component Action: Button {
                Layout.fillWidth: true
                implicitHeight: 38
                property color tint: root.text
                background: Rectangle {
                    radius: 7
                    color: parent.pressed ? root.line : root.surface
                    border.color: root.line
                }
                contentItem: Label {
                    text: parent.text; color: parent.enabled ? parent.tint
                                                             : root.dim
                    font.pixelSize: 13
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
            }

            Action { text: bridge.muted ? "Unmute" : "Mute"
                     tint: bridge.muted ? root.warn : root.text
                     onClicked: bridge.toggleMute() }
            Action { text: "Wake"; onClicked: bridge.wake() }
            Action { text: "Sleep"; onClicked: bridge.sleep() }
        }
    }

    // ---- ceiling confirmation ----------------------------------------
    Dialog {
        id: ceilingDialog
        anchors.centerIn: parent
        modal: true
        width: 360
        title: "Above your volume limit"
        property int idx: 0
        property real db: 0

        contentItem: Label {
            text: "That level is " + ceilingDialog.db.toFixed(1)
                + " dB, above your " + bridge.maxVolumeDb.toFixed(0)
                + " dB limit.\n\nThe preset is stored either way, but the "
                + "limit will clamp it on recall unless you raise it."
            color: root.text; wrapMode: Text.WordWrap
        }
        standardButtons: Dialog.Ok | Dialog.Cancel
        onAccepted: bridge.setMaxVolume(ceilingDialog.db)
    }

    Connections {
        target: bridge
        function onPresetCaptured(index, db, exceeds) {
            if (exceeds) {
                ceilingDialog.idx = index
                ceilingDialog.db = db
                ceilingDialog.open()
            }
        }
        function onErrorRaised(message) { toast.show(message) }
    }

    Rectangle {
        id: toast
        anchors.bottom: parent.bottom; anchors.bottomMargin: 20
        anchors.horizontalCenter: parent.horizontalCenter
        radius: 6; color: "#33191b"; border.color: root.warn
        width: label.implicitWidth + 28; height: 34
        opacity: 0
        visible: opacity > 0
        Label { id: label; anchors.centerIn: parent; color: root.warn
                font.pixelSize: 12 }
        Behavior on opacity { NumberAnimation { duration: 180 } }
        Timer { id: hide; interval: 4000; onTriggered: toast.opacity = 0 }
        function show(message) { label.text = message; opacity = 1; hide.restart() }
    }
}
