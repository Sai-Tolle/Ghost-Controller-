import QtQuick

// Signal-strength bars. `level` 0..bars. Inactive bars use Token.color_text_muted
// (the old code read Token.color_text_disabled, which did not exist, so the
// colour binding errored and inactive bars rendered black).
Item {
    id: root
    property int level: 0
    property int bars: 5
    property color tone: Token.color_status_ok
    implicitWidth: bars * 6 - 2
    implicitHeight: 20
    width: implicitWidth; height: implicitHeight
    Repeater {
        model: root.bars
        Rectangle {
            required property int index
            x: index * 6
            width: 4
            height: 6 + index * 3
            anchors.bottom: parent.bottom
            radius: 1
            color: index < root.level ? root.tone : Qt.rgba(1, 1, 1, 0.2)
        }
    }
}
