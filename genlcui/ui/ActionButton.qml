import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// A row button. fillWidth alone distributes only the *surplus* evenly,
// starting from each button's implicitWidth -- so "Close" came out wider than
// "Quit" purely because the word is longer. A shared preferredWidth makes
// every Action in a row exactly equal regardless of its label.
Button {
    id: control
    property Theme t: Theme { }
    property color tint: t.text

    //: Hover explanation. Say what the button does or why it is unavailable,
    //: rather than restating the label.
    property string tip: ""

    ToolTip.visible: hovered && tip.length > 0
    ToolTip.text: tip
    ToolTip.delay: 500

    Layout.fillWidth: true
    Layout.preferredWidth: 1
    implicitHeight: Math.max(38, t.fs(38))


    // Qt Quick's Button sets no cursor. HoverHandler gives one without
    // intercepting clicks the way an overlaid MouseArea would.
    HoverHandler {
        enabled: control.enabled
        cursorShape: Qt.PointingHandCursor
    }

    background: Rectangle {
        radius: 7
        color: control.pressed ? t.line : t.surface
        border.color: t.line
    }
    contentItem: Label {
        text: control.text
        color: control.enabled ? control.tint : t.dim
        font.pixelSize: t.fs(13)
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
    }
}
