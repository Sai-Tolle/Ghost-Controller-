import QtQuick

// Center pitch ladder + fixed aircraft reference (circle + wings), like the
// video-first reference HUD. The ladder shifts with pitch; the ±5/±10 bars
// stay upright (no roll rotation) for a calm, readable overlay.
Canvas {
    id: root

    property real pitch: 0    // deg
    property real roll: 0     // deg (reserved: ladder stays level like the reference)
    property real pxPerDeg: 8

    width: 560
    height: 420

    onPitchChanged: requestPaint()
    onPaint: {
        var ctx = getContext("2d")
        ctx.reset()
        ctx.strokeStyle = Token.color_gauge_ladder.toString()
        ctx.fillStyle = Token.color_gauge_ladder.toString()
        ctx.lineWidth = 1.3
        ctx.globalAlpha = 0.7
        ctx.shadowColor = "rgba(0,0,0,0.6)"; ctx.shadowBlur = 3
        // CSS shorthand: quoted family (multi-word) + generic fallback
        ctx.font = "11px '" + Token.typography_familyMono + "', monospace"

        var cy = height / 2 + pitch * pxPerDeg
        var mid = width / 2
        var gap = 70          // half-gap around the center marker
        var major = 90        // half-width of major (labelled) bars

        function bar(deg, halfWidth) {
            var y = cy - deg * pxPerDeg
            ctx.beginPath()
            ctx.moveTo(mid - gap - 14, y)
            ctx.lineTo(mid - gap - 14 - halfWidth, y)
            ctx.stroke()
            ctx.beginPath()
            ctx.moveTo(mid + gap + 14, y)
            ctx.lineTo(mid + gap + 14 + halfWidth, y)
            ctx.stroke()
            if (halfWidth >= major) {
                ctx.textAlign = "right"
                ctx.fillText((deg > 0 ? "+" : "") + deg, mid - gap - 24, y + 4)
                ctx.textAlign = "left"
                ctx.fillText((deg > 0 ? "+" : "") + deg, mid + gap + 24, y + 4)
            }
        }

        for (var d = -30; d <= 30; d += 5) {
            if (d === 0) continue
            bar(d, d % 10 === 0 ? major : major * 0.55)
        }

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
        anchors.centerIn: parent
        width: 14; height: 14; radius: 7
        color: "transparent"
        border.width: 2
        border.color: Token.color_gauge_ladder
    }
    Rectangle {
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
