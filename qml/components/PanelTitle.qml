import QtQuick

Item {
    id: root
    property string text: ""
    property color tone: Token.color_ui_text
    signal closed()
    width: parent ? parent.width : 200
    height: 26
    Text {
        anchors.verticalCenter: parent.verticalCenter
        text: root.text
        font.pixelSize: Token.typography_size_lg
        font.weight: Font.DemiBold
        color: root.tone
    }
    Rectangle {                                       // circular close glyph (macOS sheet style)
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        width: 22; height: 22; radius: 11
        color: closeHover.hovered ? Token.color_ui_fillHover : Token.color_ui_fill
        Icon {
            anchors.centerIn: parent
            name: "xmark"; size: 12; weight: 1.8
            color: closeHover.hovered ? Token.color_ui_text : Token.color_ui_textDim
        }
        HoverHandler { id: closeHover; cursorShape: Qt.PointingHandCursor }
        TapHandler { onTapped: root.closed() }
    }
}
