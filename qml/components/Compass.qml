import QtQuick

// Heading compass. The dial is laid out against the COMPASS' OWN size.
// (Each tick used to live in a hard-coded 360x360 box, so on the 92 px map
// compass every tick and cardinal letter sat ~170 px from the centre — outside
// the clipped circle — and only the pointer and number were visible.)
Rectangle {
    id: compass

    property real heading: 0        // deg 0..360, nose direction
    property bool showReadout: true

    width: 92; height: 92
    radius: width / 2
    color: Qt.alpha(Token.color_base_bg, 0.0)

    readonly property real r: width / 2
    readonly property real norm: ((heading % 360) + 360) % 360

    Rectangle {                                    // glass disc
        anchors.fill: parent
        radius: width / 2
        color: Token.color_ui_glass
        border.width: 1
        border.color: Token.color_ui_lineStrong
    }

    // minor/major ticks every 10 degrees, rotated with the heading
    Repeater {
        model: 36
        delegate: Item {
            required property int index
            width: compass.width; height: compass.height
            rotation: index * 10 - compass.heading
            transformOrigin: Item.Center
            Rectangle {
                width: index % 9 === 0 ? 2 : 1
                height: index % 3 === 0 ? compass.r * 0.16 : compass.r * 0.09
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.top: parent.top
                anchors.topMargin: 3
                color: index === 0 ? Token.color_status_danger
                     : index % 9 === 0 ? "#FFFFFF" : Qt.rgba(1, 1, 1, 0.5)
            }
        }
    }

    // cardinal letters stay upright and ride the circle
    Repeater {
        model: ["N", "E", "S", "W"]
        delegate: Text {
            required property int index
            required property string modelData
            readonly property real a: (index * 90 - compass.heading) * Math.PI / 180
            readonly property real rr: compass.r * 0.64
            x: compass.r + rr * Math.sin(a) - width / 2
            y: compass.r - rr * Math.cos(a) - height / 2
            text: modelData
            font.family: Token.typography_familyMono
            font.pixelSize: Math.max(9, compass.r * 0.24)
            font.weight: Font.Bold
            color: index === 0 ? Token.color_status_danger : Token.color_ui_text
        }
    }

    // fixed lubber pointer at 12 o'clock
    Canvas {
        width: 10; height: 8
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.top: parent.top
        onPaint: {
            var ctx = getContext("2d"); ctx.reset()
            ctx.fillStyle = Token.color_accent_primary.toString()
            ctx.beginPath(); ctx.moveTo(5, 8); ctx.lineTo(0, 0); ctx.lineTo(10, 0)
            ctx.closePath(); ctx.fill()
        }
    }

    Rectangle {                                    // readout pill under the dial
        visible: compass.showReadout
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.top: parent.bottom
        anchors.topMargin: 6
        width: pillText.implicitWidth + 18; height: 20; radius: 10
        color: Token.color_ui_glass
        border.width: 1; border.color: Token.color_ui_line
        Text {
            id: pillText
            anchors.centerIn: parent
            text: compass.pad3(compass.norm) + "  " + ["N","NE","E","SE","S","SW","W","NW"][Math.round(compass.norm / 45) % 8]
            font.family: Token.typography_familyMono
            font.pixelSize: 10; font.weight: Font.Bold; font.letterSpacing: 1
            color: "#FFFFFF"
        }
    }

    function pad3(n) {
        var s = "" + Math.round(n) % 360
        while (s.length < 3) s = "0" + s
        return s + "°"
    }
}
