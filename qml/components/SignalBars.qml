import QtQuick

// Signal-strength bars. `level` 0..bars. Inactive bars use Token.color_text_muted
// (the old code read Token.color_text_disabled, which did not exist, so the
// colour binding errored and inactive bars rendered black).
Item {
    id: root
    property int level: 0
    property int bars: 5
    property color tone: Token.color_status_ok
    implicitWidth: bars * 5 - 1.5
    implicitHeight: 15
    width: implicitWidth; height: implicitHeight
    Repeater {
        model: root.bars
        Rectangle {
            required property int index
            x: index * 5
            width: 3.5
            height: 4 + index * 2.5
            anchors.bottom: parent.bottom
            radius: 1.25
            color: index < root.level ? root.tone : Qt.alpha(Token.color_ui_text, 0.2)
        }
    }
}
