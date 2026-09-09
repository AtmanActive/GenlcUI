import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ApplicationWindow {
    id: root
    width: 520; height: 780
    minimumWidth: 420; minimumHeight: 600
    visible: true
    title: "GenlcUI"

    Theme { id: t }
    color: t.bg
    Behavior on color { ColorAnimation { duration: 160 } }

    // ---- page flip ----------------------------------------------------
    // A real rotation of one surface, not two stacked windows: the front
    // face is visible for the first half of the turn and the back for the
    // second, so it reads as one object turning over.
    Item {
        id: flip
        anchors.fill: parent
        property bool showingSettings: false
        property real angle: showingSettings ? 180 : 0

        Behavior on angle {
            NumberAnimation { duration: 460; easing.type: Easing.InOutQuad }
        }

        transform: [
            Rotation {
                origin.x: flip.width / 2; origin.y: flip.height / 2
                axis { x: 0; y: 1; z: 0 }
                angle: flip.angle
            },
            Scale {
                // A slight dip mid-turn reads as depth without needing a
                // perspective projection.
                origin.x: flip.width / 2; origin.y: flip.height / 2
                xScale: 1 - 0.06 * Math.sin(flip.angle * Math.PI / 180)
                yScale: xScale
            }
        ]

        MainPage {
            anchors.fill: parent
            visible: flip.angle < 90
            onOpenSettings: flip.showingSettings = true
            onRequestHide: root.hide()
            onRequestQuit: quitDialog.open()
        }

        SettingsPage {
            anchors.fill: parent
            visible: flip.angle >= 90
            // Counter-rotated so the back face reads correctly once turned.
            transform: Rotation {
                origin.x: width / 2; origin.y: height / 2
                axis { x: 0; y: 1; z: 0 }
                angle: 180
            }
            onCloseSettings: flip.showingSettings = false
        }
    }

    // ---- confirmations ------------------------------------------------
    ThemedDialog {
        id: ceilingDialog
        title: "Above your volume limit"
        property real db: 0

        contentItem: Label {
            text: "That level is " + ceilingDialog.db.toFixed(1)
                + " dB, above your " + bridge.ceilingDb.toFixed(0)
                + " dB limit.\n\nThe preset is stored either way, but the "
                + "limit will clamp it on recall unless you raise it."
            color: t.text
            font.pixelSize: t.fs(13)
            wrapMode: Text.WordWrap
        }
        standardButtons: Dialog.Ok | Dialog.Cancel
        onAccepted: bridge.setMaxVolume(ceilingDialog.db)
    }

    ThemedDialog {
        id: quitDialog
        title: "Quit " + bridge.appName + "?"
        contentItem: Label {
            text: "Volume control returns to the hardware knob.\n\n"
                + "Presets, mute and the status display will stop working "
                + "until you start the application again."
            color: t.text
            font.pixelSize: t.fs(13)
            wrapMode: Text.WordWrap
        }
        standardButtons: Dialog.Ok | Dialog.Cancel
        onAccepted: bridge.quitApplication()
    }

    // Shown once per run when the adapter is present but unreadable -- the
    // usual first-run state, and one with an exact fix.
    ThemedDialog {
        id: permissionDialog
        width: 520
        title: "Cannot reach the GLM adapter"
        property string devicePath: ""
        standardButtons: Dialog.Close

        contentItem: ColumnLayout {
            spacing: 12
            Label {
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                color: t.text
                font.pixelSize: t.fs(13)
                text: "The adapter is plugged in"
                    + (permissionDialog.devicePath
                       ? " at " + permissionDialog.devicePath : "")
                    + ", but this account is not allowed to open it. Linux "
                    + "restricts raw USB devices to root by default.\n\n"
                    + "Paste this into a terminal to grant access, then "
                    + "unplug and replug the adapter:"
            }
            Rectangle {
                Layout.fillWidth: true
                implicitHeight: commandText.implicitHeight + 20
                radius: 6
                color: t.isDark ? Qt.darker(t.bg, 1.25) : Qt.darker(t.bg, 1.04)
                border.color: t.line
                TextEdit {
                    id: commandText
                    anchors.fill: parent
                    anchors.margins: 10
                    text: bridge.udevFixCommand
                    color: t.text
                    font.family: "monospace"
                    font.pixelSize: t.fs(11)
                    wrapMode: TextEdit.NoWrap
                    readOnly: true
                    selectByMouse: true
                }
            }
            Button {
                id: copyButton
                Layout.alignment: Qt.AlignLeft
                implicitWidth: Math.max(130, t.fs(136))
                implicitHeight: Math.max(30, t.fs(32))
                onClicked: {
                    bridge.copyToClipboard(bridge.udevFixCommand)
                    toast.show("Commands copied to the clipboard", false)
                }
                HoverHandler { cursorShape: Qt.PointingHandCursor }
                background: Rectangle {
                    radius: 6
                    color: copyButton.pressed ? t.line : t.surface
                    border.color: t.line
                }
                contentItem: Label {
                    text: "Copy commands"
                    color: t.text
                    font.pixelSize: t.fs(12)
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
            }
            Label {
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                color: t.dim
                font.pixelSize: t.fs(11)
                text: "Nothing else needs changing, and this only has to be "
                    + "done once per machine."
            }
        }
    }

    Connections {
        target: bridge
        function onPresetCaptured(index, db, exceeds) {
            if (exceeds) { ceilingDialog.db = db; ceilingDialog.open() }
            else toast.show("Stored " + t.fmtDb(db))
        }
        function onCeilingCaptured(db) {
            toast.show("Limit set to " + t.fmtDb(db), false)
        }
        function onErrorRaised(message) { toast.show(message) }
        function onPermissionProblem(devicePath) {
            permissionDialog.devicePath = devicePath
            permissionDialog.open()
        }
    }

    Rectangle {
        id: toast
        anchors.bottom: parent.bottom; anchors.bottomMargin: 20
        anchors.horizontalCenter: parent.horizontalCenter
        radius: 6
        property bool isError: true
        color: isError ? (t.isDark ? "#33191b" : "#fdecec")
                       : (t.isDark ? "#1b2a20" : "#e9f7ee")
        border.color: isError ? t.warn : t.ok
        width: label.implicitWidth + 28
        height: Math.max(34, t.fs(34))
        opacity: 0
        visible: opacity > 0
        Label {
            id: label; anchors.centerIn: parent
            color: toast.isError ? t.warn : t.ok
            font.pixelSize: t.fs(12)
        }
        Behavior on opacity { NumberAnimation { duration: 180 } }
        Timer { id: hide; interval: 4000; onTriggered: toast.opacity = 0 }
        function show(message, error) {
            isError = error === undefined ? true : error
            label.text = message; opacity = 1; hide.restart()
        }
    }
}
