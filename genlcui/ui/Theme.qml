import QtQuick

// Shared styling, instantiated per file as `Theme { id: t }`.
//
// Not a QML singleton: singletons cannot reach context properties, and the
// palette lives on `bridge`. Instantiating one per file costs nothing and
// keeps every colour and font size in one place.
QtObject {
    readonly property var pal: bridge.palette

    readonly property color bg:      pal.bg
    readonly property color surface: pal.surface
    readonly property color line:    pal.line
    readonly property color text:    pal.text
    readonly property color dim:     pal.dim
    readonly property color accent:  pal.accent
    readonly property color warn:    pal.warn
    readonly property color ok:      pal.ok
    readonly property bool isDark:   pal.isDark === "1"

    //: Every font size goes through this so the text-size setting scales the
    //: whole interface rather than a chosen few labels.
    function fs(size) { return Math.round(size * bridge.fontScale) }

    function fmtDb(v) { return (v > -130 ? v.toFixed(1) : "-∞") + " dB" }
}
