import QtQuick

// Segmented battery glyph; fraction < 0 means "unknown". The terminal nub is on
// the RIGHT (it was anchored to the left edge, overlapping the body).
Item {
    id: root
    property real fraction: 0
    property bool critical: false
    readonly property bool known: fraction >= 0
    readonly property int cells: 5
    readonly property color tone: !known ? Token.color_text_muted
                                : critical ? Token.color_status_danger
                                : fraction < 0.3 ? Token.color_status_warn
                                : Token.color_status_ok
    implicitWidth: 38
    implicitHeight: 16
    width: implicitWidth; height: implicitHeight

    Rectangle {
        id: body
        width: parent.width - 3; height: parent.height
        radius: 4
        color: "transparent"
        border.width: 1.5
        border.color: root.tone
        Row {
            anchors.fill: parent
            anchors.margins: 2.5
            spacing: 2
            Repeater {
                model: root.cells
                Rectangle {
                    required property int index
                    width: (body.width - 5 - (root.cells - 1) * 2) / root.cells
                    height: parent.height
                    radius: 1.5
                    color: root.known && index < Math.ceil(root.fraction * root.cells - 0.001)
                           ? root.tone : Qt.rgba(1, 1, 1, 0.16)
                }
            }
        }
    }
    Rectangle {
        anchors.left: body.right
        anchors.verticalCenter: parent.verticalCenter
        width: 3; height: 7; radius: 1
        color: root.tone
    }
}
