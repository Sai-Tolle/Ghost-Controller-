import QtQuick

// Sidebar list row (Finder-sidebar style): tinted pill when active.
Rectangle {
    id: root
    property string label: ""
    property string icon: ""
    property bool active: false
    property color activeColor: Token.color_accent_primary
    signal clicked()
    implicitHeight: 32
    height: implicitHeight
    radius: Token.dimension_radius_sm + 1
    color: active ? Qt.alpha(activeColor, 0.22) : (hover.hovered ? Token.color_ui_fill : "transparent")
    Behavior on color { ColorAnimation { duration: Token.motion_fast } }
    Icon {
        id: glyph
        visible: root.icon !== ""
        anchors.left: parent.left
        anchors.leftMargin: 9
        anchors.verticalCenter: parent.verticalCenter
        name: root.icon; size: 16; weight: 1.5
        color: root.active ? Qt.lighter(root.activeColor, 1.25) : Token.color_ui_textDim
    }
    Text {
        anchors.left: parent.left
        anchors.leftMargin: root.icon !== "" ? 33 : 10
        anchors.verticalCenter: parent.verticalCenter
        text: root.label
        font.pixelSize: Token.typography_size_md
        font.weight: root.active ? Font.DemiBold : Font.Normal
        color: root.active ? Qt.lighter(root.activeColor, 1.25) : Token.color_ui_text
    }
    HoverHandler { id: hover; cursorShape: Qt.PointingHandCursor }
    TapHandler { gesturePolicy: TapHandler.ReleaseWithinBounds; onTapped: root.clicked() }
}
