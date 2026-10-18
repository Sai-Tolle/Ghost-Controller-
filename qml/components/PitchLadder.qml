import QtQuick

// Center pitch ladder + fixed aircraft reference (circle + wings), like the
// video-first reference HUD. The ladder shifts with pitch; the ±5/±10 bars
// stay upright (no roll rotation) for a calm, readable overlay.
Canvas {
    id: root

    property real pitch: 0    // deg
    property real roll: 0     // deg (reserved: ladder stays level like the reference)
    property real pxPerDeg: 8
    // The flight HUD draws its own (white) bore-sight; it turns this one off so
    // two aircraft symbols are not stacked on each other.
    property bool showReference: true

    width: 560
    height: 420

    // Operator-chosen HUD ink (Theme ▸ HUD colour) with a contrasting soft
    // outline; the old fixed white vanished against cloud and snow.
    property color ink: Token.hudInk
    property color shadow: Token.hudInkShadow
    onInkChanged: requestPaint()
    onShadowChanged: requestPaint()
    onPitchChanged: requestPaint()
    onPaint: {
        var ctx = getContext("2d")
        ctx.reset()
        ctx.strokeStyle = ink
        ctx.fillStyle = ink
        ctx.lineWidth = 1.5
        ctx.lineCap = "round"
        ctx.shadowColor = shadow; ctx.shadowBlur = 4
        // CSS shorthand: quoted family (multi-word) + generic fallback
        ctx.font = "500 11px '" + Token.typography_familyUi + "', sans-serif"

        var cy = height / 2 + pitch * pxPerDeg
        var mid = width / 2
        var gap = 70          // half-gap around the center marker
        var major = 90        // half-width of major (labelled) bars

        function bar(deg, halfWidth) {
            var y = cy - deg * pxPerDeg
            // fade out toward the top/bottom so the ladder dissolves instead of clipping
            var a = 1 - Math.abs(y - height / 2) / (height / 2)
            if (a <= 0.02) return
            ctx.globalAlpha = Math.min(0.9, a * 1.3)
            // below the horizon: dashed bars (standard HUD convention)
            ctx.setLineDash(deg < 0 ? [7, 5] : [])
            ctx.beginPath()
            ctx.moveTo(mid - gap - 14, y)
            ctx.lineTo(mid - gap - 14 - halfWidth, y)
            ctx.stroke()
            ctx.beginPath()
            ctx.moveTo(mid + gap + 14, y)
            ctx.lineTo(mid + gap + 14 + halfWidth, y)
            ctx.stroke()
            ctx.setLineDash([])
            if (halfWidth >= major) {
                ctx.textAlign = "right"
                ctx.fillText(Math.abs(deg), mid - gap - 22 - halfWidth, y + 4)
                ctx.textAlign = "left"
                ctx.fillText(Math.abs(deg), mid + gap + 22 + halfWidth, y + 4)
            }
        }

        for (var d = -30; d <= 30; d += 5) {
            if (d === 0) continue
            bar(d, d % 10 === 0 ? major : major * 0.45)
        }
        ctx.globalAlpha = 0.9

        // zenith/nadir arrow above the +30 bar
        var zy = cy - 30 * pxPerDeg
        if (zy > -20 && zy < height + 20) {
            ctx.beginPath()
            ctx.moveTo(mid, zy - 26)
            ctx.lineTo(mid - 7, zy - 12)
            ctx.lineTo(mid + 7, zy - 12)
            ctx.closePath()
            ctx.fill()
        }
    }

    // ---- fixed aircraft reference: circle + wing bars -----------------
    Rectangle {
        visible: root.showReference
        anchors.centerIn: parent
        width: 14; height: 14; radius: 7
        color: "transparent"
        border.width: 2
        border.color: Token.color_gauge_ladder
    }
    Rectangle {
        visible: root.showReference
        anchors.verticalCenter: parent.verticalCenter
        anchors.right: centerDot.left
        anchors.rightMargin: 10
        width: 90; height: 2
        color: Token.color_gauge_ladder
        Rectangle {  // wingtip drop
            anchors.right: parent.right
            anchors.verticalCenter: parent.bottom
            width: 2; height: 10
            color: parent.color
        }
    }
    Rectangle {
        id: centerDot
        anchors.centerIn: parent
        width: 1; height: 1
    }
    Rectangle {
        visible: root.showReference
        anchors.verticalCenter: parent.verticalCenter
        anchors.left: centerDot.right
        anchors.leftMargin: 10
        width: 90; height: 2
        color: Token.color_gauge_ladder
        Rectangle {
            anchors.left: parent.left
            anchors.verticalCenter: parent.bottom
            width: 2; height: 10
            color: parent.color
        }
    }
}
