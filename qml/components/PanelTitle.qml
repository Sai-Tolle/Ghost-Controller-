import QtQuick

Item {
    id: root
    property string text: ""
    property color tone: Token.color_accent_primary
    signal closed()
    width: parent ? parent.width : 200
    height: 22
    Text {
        anchors.verticalCenter: parent.verticalCenter
        text: root.text
        font.family: Token.typography_familyMono
        font.pixelSize: 11; font.weight: Font.Bold; font.letterSpacing: 1.4
        color: root.tone
    }
    Text {
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        text: "✕"; font.pixelSize: 13
        color: closeHover.hovered ? "#FFFFFF" : Token.color_ui_textDim
        HoverHandler { id: closeHover; cursorShape: Qt.PointingHandCursor }
        TapHandler { onTapped: root.closed() }
    }
}
