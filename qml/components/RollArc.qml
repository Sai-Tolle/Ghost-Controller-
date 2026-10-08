import QtQuick

// Web RollArc parity: arc with degree ticks and a rotating pointer showing
// roll attitude. Presentation-only.
Item {
    id: root

    property real roll: 0

    onRollChanged: arcCanvas.requestPaint()

    Canvas {
        id: arcCanvas
        anchors.fill: parent
        readonly property real cx: width / 2
        readonly property real cy: height * 0.82
        readonly property real r: Math.min(width, height) * 0.62
        onPaint: {
            var ctx = getContext("2d")
            ctx.reset()
            // main arc (0..180°, upper half)
            ctx.strokeStyle = "rgba(255,255,255,0.75)"
            ctx.shadowColor = "rgba(0,0,0,0.6)"; ctx.shadowBlur = 3
            ctx.lineWidth = 2
            ctx.beginPath()
            ctx.arc(cx, cy, r, Math.PI, 2 * Math.PI, false)
            ctx.stroke()
            // tick marks at -30/-20/-10/0/10/20/30
            for (var i = 0; i <= 6; i++) {
                var deg = i * 10 - 30
                var rad = (deg * Math.PI / 180) - Math.PI / 2
                ctx.lineWidth = deg === 0 ? 2.5 : 1.5
                ctx.beginPath()
                ctx.moveTo(cx + (r - 6) * Math.cos(rad), cy + (r - 6) * Math.sin(rad))
                ctx.lineTo(cx + (r + 2) * Math.cos(rad), cy + (r + 2) * Math.sin(rad))
                ctx.stroke()
            }
            // rotating pointer triangle
            ctx.save()
            ctx.translate(cx, cy)
            ctx.rotate(-root.roll * Math.PI / 180)
            ctx.fillStyle = "#5AA9FF"
            ctx.beginPath()
            ctx.moveTo(0, -r + 5)
            ctx.lineTo(-4, -r + 14)
            ctx.lineTo(4, -r + 14)
            ctx.closePath()
            ctx.fill()
            ctx.restore()
        }
        onWidthChanged: requestPaint()
        onHeightChanged: requestPaint()
    }
}
