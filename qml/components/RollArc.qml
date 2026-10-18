import QtQuick

// Roll scale: a shallow ±45° arc with ticks at 10/20/30/45° and a pointer
// that slides along it with bank angle. The bank value appears beside the
// pointer only while the aircraft is actually banked.
Item {
    id: root

    property real roll: 0            // deg, right wing down = positive
    property real maxRoll: 45

    implicitWidth: 300
    implicitHeight: 64

    onRollChanged: arc.requestPaint()

    Canvas {
        id: arc
        anchors.fill: parent
        property color ink: Token.hudInk
        property color shadow: Token.hudInkShadow
        onShadowChanged: requestPaint()
        property color accent: Token.color_accent_primary
        onInkChanged: requestPaint()
        onWidthChanged: requestPaint()
        onPaint: {
            var ctx = getContext("2d"); ctx.reset()
            // circle centre well below the item: a wide, shallow arc
            var r = width * 0.9
            var cx = width / 2, cy = 8 + r
            var toRad = function (deg) { return (deg - 90) * Math.PI / 180 }
            ctx.lineCap = "round"
            ctx.shadowColor = shadow; ctx.shadowBlur = 4

            ctx.globalAlpha = 0.55
            ctx.strokeStyle = ink; ctx.lineWidth = 1.25
            ctx.beginPath(); ctx.arc(cx, cy, r, toRad(-root.maxRoll), toRad(root.maxRoll), false); ctx.stroke()

            var ticks = [-45, -30, -20, -10, 0, 10, 20, 30, 45]
            for (var i = 0; i < ticks.length; i++) {
                var t = ticks[i]
                var major = t === 0 || Math.abs(t) === 30 || Math.abs(t) === 45
                var len = t === 0 ? 10 : major ? 8 : 5
                var a = toRad(t)
                ctx.globalAlpha = major ? 0.9 : 0.6
                ctx.lineWidth = t === 0 ? 2 : 1.25
                ctx.beginPath()
                ctx.moveTo(cx + r * Math.cos(a), cy + r * Math.sin(a))
                ctx.lineTo(cx + (r + len) * Math.cos(a), cy + (r + len) * Math.sin(a))
                ctx.stroke()
            }

            // pointer: rides inside the arc at the current bank angle
            var rr = Math.max(-root.maxRoll, Math.min(root.maxRoll, root.roll))
            var pa = toRad(rr)
            ctx.save()
            ctx.translate(cx + (r - 3) * Math.cos(pa), cy + (r - 3) * Math.sin(pa))
            ctx.rotate(rr * Math.PI / 180)
            ctx.globalAlpha = 1
            ctx.fillStyle = Math.abs(root.roll) > root.maxRoll ? "#FF9F0A" : accent
            ctx.beginPath(); ctx.moveTo(0, 0); ctx.lineTo(-6, 10); ctx.lineTo(6, 10); ctx.closePath(); ctx.fill()
            ctx.restore()
        }
    }

    Text {
        visible: Math.abs(root.roll) >= 1.5
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.horizontalCenterOffset: root.roll > 0 ? 44 : -44
        anchors.top: parent.top
        anchors.topMargin: 22
        text: Math.abs(root.roll).toFixed(0) + "°"
        font.pixelSize: 11; font.weight: Font.DemiBold
        font.features: { "tnum": 1 }
        color: Token.hudInk
        style: Text.Outline; styleColor: Token.hudInkShadow
        opacity: 0.85
    }
}
