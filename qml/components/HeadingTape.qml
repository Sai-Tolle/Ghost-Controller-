import QtQuick

// Compass heading tape (top of the flight HUD): a horizontal strip that
// scrolls with heading — minor ticks every 5°, labels every 15° with
// cardinals as letters — under a glass readout capsule with a caret.
// Edges fade out instead of clipping.
Item {
    id: root
    property real heading: 0              // deg, nose direction
    property real pxPerDeg: 4.2
    readonly property real norm: ((heading % 360) + 360) % 360

    implicitWidth: 460
    implicitHeight: 74

    function pad3(n) {
        var s = "" + (Math.round(n) % 360)
        while (s.length < 3) s = "0" + s
        return s
    }
    readonly property string cardinal: ["N", "NE", "E", "SE", "S", "SW", "W", "NW"][Math.round(norm / 45) % 8]

    // ---- readout capsule ---------------------------------------------------------
    Rectangle {
        id: readout
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.top: parent.top
        width: readRow.implicitWidth + 26
        height: 30
        radius: 15
        color: Token.color_ui_glass
        border.width: 1
        border.color: Token.color_ui_line
        Row {
            id: readRow
            anchors.centerIn: parent
            spacing: 6
            Text {
                anchors.baseline: parent.children[1].baseline
                text: root.pad3(root.norm) + "°"
                font.pixelSize: 17; font.weight: Font.DemiBold
                font.features: { "tnum": 1 }
                color: Token.color_ui_text
            }
            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: root.cardinal
                font.pixelSize: 12; font.weight: Font.DemiBold
                color: Token.color_ui_textDim
            }
        }
    }
    Canvas {                                       // caret under the capsule
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.top: readout.bottom
        anchors.topMargin: 2
        width: 12; height: 6
        property color tint: Token.color_accent_primary
        onTintChanged: requestPaint()
        onPaint: {
            var ctx = getContext("2d"); ctx.reset()
            ctx.fillStyle = tint
            ctx.beginPath(); ctx.moveTo(0, 0); ctx.lineTo(12, 0); ctx.lineTo(6, 6); ctx.closePath(); ctx.fill()
        }
    }

    // ---- scrolling tape ----------------------------------------------------------
    Canvas {
        id: tape
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: 34
        property real h: root.norm
        property color ink: Token.hudInk
        property color shadow: Token.hudInkShadow
        onHChanged: requestPaint()
        onInkChanged: requestPaint()
        onShadowChanged: requestPaint()
        onWidthChanged: requestPaint()
        onPaint: {
            var ctx = getContext("2d"); ctx.reset()
            var mid = width / 2
            var span = width / 2 / root.pxPerDeg            // degrees visible each side
            ctx.font = "600 12px '" + Token.typography_familyUi + "', sans-serif"
            ctx.textAlign = "center"
            ctx.lineCap = "round"
            ctx.shadowColor = shadow; ctx.shadowBlur = 4
            var start = Math.ceil((h - span) / 5) * 5
            for (var d = start; d <= h + span; d += 5) {
                var x = mid + (d - h) * root.pxPerDeg
                var fade = 1 - Math.abs(x - mid) / mid           // dissolve toward the edges
                if (fade <= 0.02) continue
                var deg = ((d % 360) + 360) % 360
                var major = deg % 15 === 0
                ctx.globalAlpha = Math.min(1, fade * 1.6) * (major ? 0.95 : 0.55)
                ctx.strokeStyle = ink
                ctx.lineWidth = major ? 1.6 : 1.1
                ctx.beginPath()
                ctx.moveTo(x, 0)
                ctx.lineTo(x, major ? 9 : 5)
                ctx.stroke()
                if (major) {
                    var card = { 0: "N", 90: "E", 180: "S", 270: "W" }[deg]
                    ctx.fillStyle = card === "N" ? "#FF453A" : ink
                    ctx.fillText(card !== undefined ? card : String(deg), x, 26)
                }
            }
        }
    }
}
