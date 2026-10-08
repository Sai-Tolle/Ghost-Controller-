import QtQuick

// Speed / altitude tape: title, value box, then 9 scrolling ticks with the
// current value in the centre. Ticks scroll continuously with the fractional
// part of the value (they used to jump a whole step at a time), and the
// current-tick highlight now works — it read `root.isCurrent`, a property that
// only exists on the delegate, so the centre tick was never highlighted.
Item {
    id: root
    property real value: 0
    property real step: 1
    property string title: ""
    property string readout: ""
    property string unit: ""
    property string side: "left"      // "left" | "right"
    property string sourceNote: ""
    property real minValue: -1e9           // ticks below this are hidden (speed never goes negative)
    readonly property bool isLeft: side === "left"

    readonly property real rowH: 28
    readonly property real base: Math.round(value / step)
    readonly property real frac: value / step - base            // -0.5 .. 0.5

    Column {
        id: stack
        anchors.centerIn: parent
        spacing: 8

        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: root.title
            font.family: Token.typography_familyMono
            font.pixelSize: 9
            font.letterSpacing: 2
            font.weight: Font.DemiBold
            color: Token.color_ui_textDim
            style: Text.Outline
            styleColor: Qt.rgba(0, 0, 0, 0.7)
        }

        Rectangle {
            anchors.horizontalCenter: parent.horizontalCenter
            width: root.width - 16
            height: 38
            radius: 8
            color: Token.color_ui_glass
            border.width: 1
            border.color: Token.color_ui_line
            Row {
                anchors.centerIn: parent
                spacing: 3
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: root.readout
                    font.family: Token.typography_familyMono
                    font.pixelSize: 20
                    font.weight: Font.Bold
                    color: "#FFFFFF"
                }
                Text {
                    id: unitText
                    text: root.unit
                    font.family: Token.typography_familyMono
                    font.pixelSize: 9
                    color: Token.color_ui_textDim
                }
            }
        }

        Item {                                          // scrolling ticks
            anchors.horizontalCenter: parent.horizontalCenter
            width: root.width - 16
            height: root.rowH * 9
            clip: true
            Repeater {
                model: 9
                delegate: Item {
                    id: tick
                    required property int index
                    readonly property bool current: index === 4
                    readonly property real dist: Math.abs(index - 4 + root.frac)
                    width: parent.width
                    height: root.rowH
                    y: (index + root.frac) * root.rowH - 0       // value up -> ticks move down
                    visible: (root.base + (4 - index)) * root.step >= root.minValue
                    opacity: Math.max(0.15, 1.0 - dist * 0.2)
                    Row {
                        anchors.verticalCenter: parent.verticalCenter
                        anchors.right: root.isLeft ? parent.right : undefined
                        anchors.left: root.isLeft ? undefined : parent.left
                        spacing: 6
                        layoutDirection: root.isLeft ? Qt.LeftToRight : Qt.RightToLeft
                        Rectangle {
                            anchors.verticalCenter: parent.verticalCenter
                            width: tick.current ? 22 : 12
                            height: tick.current ? 2 : 1
                            color: tick.current ? Token.color_accent_primary : Qt.rgba(1, 1, 1, 0.55)
                        }
                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            text: (root.base + (4 - tick.index)) * root.step
                            font.family: Token.typography_familyMono
                            font.pixelSize: tick.current ? 13 : 11
                            font.weight: tick.current ? Font.Bold : Font.Normal
                            color: tick.current ? "#FFFFFF" : Qt.rgba(0.91, 0.93, 0.97, 0.65)
                            style: Text.Outline
                            styleColor: Qt.rgba(0, 0, 0, 0.55)
                        }
                    }
                }
            }
        }

        Text {
            visible: root.sourceNote !== ""
            anchors.horizontalCenter: parent.horizontalCenter
            text: root.sourceNote
            font.family: Token.typography_familyMono
            font.pixelSize: 8
            font.letterSpacing: 1
            color: Token.color_text_muted
        }
    }
}
