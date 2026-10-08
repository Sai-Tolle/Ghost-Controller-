import QtQuick

Rectangle {
    id: root
    property string label: ""
    property bool active: false
    property color activeColor: Token.color_accent_primary
    signal clicked()
    implicitHeight: 32
    height: implicitHeight
    radius: 7
    color: active ? Qt.alpha(activeColor, 0.18) : (hover.hovered ? Qt.rgba(1, 1, 1, 0.05) : "transparent")
    border.width: 1
    border.color: active ? activeColor : Token.color_ui_line
    Behavior on color { ColorAnimation { duration: Token.motion_fast } }
    Text {
        anchors.left: parent.left
        anchors.leftMargin: 11
        anchors.verticalCenter: parent.verticalCenter
        text: root.label
        font.family: Token.typography_familyMono
        font.pixelSize: 11
        font.weight: root.active ? Font.DemiBold : Font.Normal
        font.letterSpacing: 0.8
        color: root.active ? root.activeColor : Token.color_ui_text
    }
    HoverHandler { id: hover; cursorShape: Qt.PointingHandCursor }
    TapHandler { gesturePolicy: TapHandler.ReleaseWithinBounds; onTapped: root.clicked() }
}
