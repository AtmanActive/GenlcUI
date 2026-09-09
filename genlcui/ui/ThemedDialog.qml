import QtQuick
import QtQuick.Controls

// A Dialog drawn from our palette.
//
// The stock Dialog takes its background, title bar and footer buttons from
// the Qt style, which ignores the app palette entirely -- on a light theme
// those came out dark-on-near-white, the same fault the autostart switch had.
Dialog {
    id: control
    property Theme t: Theme { }

    modal: true
    anchors.centerIn: parent
    width: 360
    padding: 18

    background: Rectangle {
        color: t.surface
        radius: 10
        border.color: t.line
    }

    header: Label {
        text: control.title
        visible: control.title.length > 0
        color: t.text
        font.pixelSize: t.fs(15)
        font.weight: Font.Medium
        leftPadding: 18
        topPadding: 16
        bottomPadding: 4
    }

    footer: DialogButtonBox {
        padding: 14
        spacing: 8
        alignment: Qt.AlignRight
        background: Rectangle { color: "transparent" }

        delegate: Button {
            id: dialogButton
            implicitWidth: Math.max(88, control.t.fs(92))
            implicitHeight: Math.max(32, control.t.fs(34))

            //: The accepting button carries the accent so the default action
            //: is obvious without reading both labels.
            readonly property bool primary:
                DialogButtonBox.buttonRole === DialogButtonBox.AcceptRole

            HoverHandler { cursorShape: Qt.PointingHandCursor }

            background: Rectangle {
                radius: 7
                color: dialogButton.primary
                       ? (dialogButton.pressed
                          ? Qt.darker(control.t.accent, 1.25)
                          : control.t.accent)
                       : (dialogButton.pressed ? control.t.line
                                               : control.t.surface)
                border.color: dialogButton.primary ? control.t.accent
                                                   : control.t.line
            }
            contentItem: Label {
                text: dialogButton.text
                color: dialogButton.primary ? "#ffffff" : control.t.text
                font.pixelSize: control.t.fs(13)
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
            }
        }
    }

    Overlay.modal: Rectangle {
        color: Qt.rgba(0, 0, 0, control.t.isDark ? 0.55 : 0.28)
    }
}
