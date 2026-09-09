import QtQuick
import QtQuick.Controls

// The stock Switch draws itself from the Qt style, not from our palette, so
// on a light theme it came out dark on near-white and was barely visible.
Switch {
    id: control
    property Theme t: Theme { }

    implicitWidth: track.implicitWidth
    implicitHeight: Math.max(28, t.fs(28))

    HoverHandler {
        enabled: control.enabled
        cursorShape: Qt.PointingHandCursor
    }

    indicator: Rectangle {
        id: track
        implicitWidth: Math.max(46, control.t.fs(46))
        implicitHeight: Math.max(26, control.t.fs(26))
        anchors.verticalCenter: parent.verticalCenter
        radius: height / 2
        opacity: control.enabled ? 1.0 : 0.45
        color: control.checked ? control.t.accent : control.t.line
        border.width: 1
        // One border colour cannot define the shape on both a dark and a
        // light ground, so it follows the mode.
        border.color: control.checked
                      ? control.t.accent
                      : (control.t.isDark ? Qt.lighter(control.t.line, 1.4)
                                          : Qt.darker(control.t.line, 1.25))
        Behavior on color { ColorAnimation { duration: 130 } }

        Rectangle {
            width: parent.height - 6
            height: width
            radius: width / 2
            y: 3
            x: control.checked ? parent.width - width - 3 : 3
            color: control.checked ? "#ffffff" : control.t.surface
            border.width: 1
            border.color: Qt.rgba(0, 0, 0, control.t.isDark ? 0.45 : 0.25)
            Behavior on x {
                NumberAnimation { duration: 130; easing.type: Easing.OutCubic }
            }
        }
    }
    contentItem: Item { }
}
