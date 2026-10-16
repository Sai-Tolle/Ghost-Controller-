import QtQuick
import QtQuick.Shapes

// SF Symbols-style line icon. Paths are drawn on a 24x24 grid and scaled to
// `size`; the stroke is compensated so every size keeps the same visual
// weight. Pure QtQuick.Shapes — renders on the software backend too.
//
//   Icon { name: "chevron.down"; size: 12; color: Token.color_ui_textDim }
Item {
    id: icon
    property string name: ""
    property real size: 16
    property color color: Token.color_ui_text
    property real weight: 1.75          // stroke width in output pixels
    property bool filled: false         // fill the closed path with `color`

    implicitWidth: size
    implicitHeight: size
    width: implicitWidth
    height: implicitHeight

    readonly property var paths: ({
        "chevron.down":   "M6 9.5l6 6 6-6",
        "chevron.up":     "M6 14.5l6-6 6 6",
        "chevron.right":  "M9.5 6l6 6-6 6",
        "xmark":          "M6.5 6.5l11 11M17.5 6.5l-11 11",
        "checkmark":      "M5 12.5l4.5 4.5L19 7",
        "plus":           "M12 5v14M5 12h14",
        "minus":          "M5 12h14",
        "exclamation":    "M12 6.5v7M12 17.4v.1",
        "warning":        "M12 3.8L2.8 19.6h18.4L12 3.8zM12 10v4.3M12 17v.1",
        "map":            "M3 6.6l6-2.4 6 2.4 6-2.4v13.2l-6 2.4-6-2.4-6 2.4zM9 4.2v13.2M15 6.6v13.2",
        "collapse":       "M4.5 14h5.5v5.5M19.5 10H14V4.5M10 14l-5.5 5.5M14 10l5.5-5.5",
        "expand":         "M14 4.5h5.5V10M10 19.5H4.5V14M19.5 4.5L14 10M4.5 19.5L10 14",
        "layers":         "M12 3.5l9 4.8-9 4.8-9-4.8zM3 12.6l9 4.8 9-4.8M3 16.4l9 4.8 9-4.8",
        "location":       "M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3M12 6.5a 5.5 5.5 0 1 1 0 11 a 5.5 5.5 0 0 1 0 -11z",
        "video":          "M3.8 7h10.4A 1.8 1.8 0 0 1 16 8.8v6.4a 1.8 1.8 0 0 1 -1.8 1.8H3.8A 1.8 1.8 0 0 1 2 15.2V8.8A 1.8 1.8 0 0 1 3.8 7zM16 10.4l5.5-3.2v9.6L16 13.6",
        "orbit":          "M20 12a 8 8 0 1 1 -2.4 -5.7M20 3.8v4h-4M12 10.2a 1.8 1.8 0 1 1 0 3.6 a 1.8 1.8 0 0 1 0 -3.6z",
        "grid":           "M5.5 4h13A 1.5 1.5 0 0 1 20 5.5v13a 1.5 1.5 0 0 1 -1.5 1.5h-13A 1.5 1.5 0 0 1 4 18.5v-13A 1.5 1.5 0 0 1 5.5 4zM4 9.3h16M4 14.7h16M9.3 4v16M14.7 4v16",
        "pin":            "M12 21.2s-6.5-6.1-6.5-11.2a 6.5 6.5 0 0 1 13 0c0 5.1-6.5 11.2-6.5 11.2zM12 7.6a 2.4 2.4 0 1 1 0 4.8 a 2.4 2.4 0 0 1 0 -4.8z",
        "fence":          "M6 4.5l9.5 1.5 4.5 7-5 6.5-9.5-1L3.5 11z",
        "trash":          "M4 6.8h16M9.5 6.8V4.5h5v2.3M6.3 6.8l.9 12.7h9.6l.9-12.7M10 10.5v5.5M14 10.5v5.5",
        "point.minus":    "M12 4.5a 7.5 7.5 0 1 1 0 15 a 7.5 7.5 0 0 1 0 -15zM8.5 12h7",
        "upload":         "M12 15V4M7.5 8.5L12 4l4.5 4.5M4.5 14.5v4A 1.5 1.5 0 0 0 6 20h12a 1.5 1.5 0 0 0 1.5 -1.5v-4",
        "download":       "M12 4v11M7.5 10.5L12 15l4.5-4.5M4.5 14.5v4A 1.5 1.5 0 0 0 6 20h12a 1.5 1.5 0 0 0 1.5 -1.5v-4",
        "import":         "M14 4.5h4A 1.5 1.5 0 0 1 19.5 6v12a 1.5 1.5 0 0 1 -1.5 1.5h-4M10 8l4 4-4 4M14 12H4",
        "export":         "M10 4.5H6A 1.5 1.5 0 0 0 4.5 6v12A 1.5 1.5 0 0 0 6 19.5h4M15 8l4 4-4 4M19 12H9",
        "gear":           "M12 9a 3 3 0 1 1 0 6 a 3 3 0 0 1 0 -6zM12 2.8l1.6 2.5 2.9-.6.6 2.9 2.5 1.6-1.4 2.8 1.4 2.8-2.5 1.6-.6 2.9-2.9-.6L12 21.2l-1.6-2.5-2.9.6-.6-2.9-2.5-1.6L5.8 12 4.4 9.2l2.5-1.6.6-2.9 2.9.6z",
        "link":           "M10 14a 4 4 0 0 0 5.7 0l3.2-3.2a 4 4 0 0 0 -5.7 -5.7l-1.2 1.2M14 10a 4 4 0 0 0 -5.7 0l-3.2 3.2a 4 4 0 0 0 5.7 5.7l1.2-1.2",
        "airplane":       "M12 3c.9 0 1.5.8 1.5 1.8V9.5l7 4.2v2l-7-2.2v4.3l2 1.6v1.6l-3.5-1-3.5 1v-1.6l2-1.6v-4.3l-7 2.2v-2l7-4.2V4.8C10.5 3.8 11.1 3 12 3z",
        "power":          "M12 3.5v8M7 6.6a 7.5 7.5 0 1 0 10 0",
        "info":           "M12 3.5a 8.5 8.5 0 1 1 0 17 a 8.5 8.5 0 0 1 0 -17zM12 11v5.5M12 7.7v.1"
    })

    Shape {
        id: shape
        width: 24; height: 24
        scale: icon.size / 24
        transformOrigin: Item.TopLeft
        antialiasing: true
        preferredRendererType: Shape.CurveRenderer
        ShapePath {
            strokeColor: icon.color
            strokeWidth: icon.weight * 24 / Math.max(1, icon.size)
            fillColor: icon.filled ? icon.color : "transparent"
            capStyle: ShapePath.RoundCap
            joinStyle: ShapePath.RoundJoin
            PathSvg { path: icon.paths[icon.name] || "" }
        }
    }
}
