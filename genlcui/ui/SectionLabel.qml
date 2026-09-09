import QtQuick
import QtQuick.Controls

Label {
    property Theme t: Theme { }
    color: t.dim
    font.pixelSize: t.fs(10)
    font.letterSpacing: 1.2
}
