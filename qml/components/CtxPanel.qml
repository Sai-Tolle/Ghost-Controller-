import QtQuick

// Shared top-right context slot (waypoint / survey / orbit / fence share it).
Rectangle {
    property bool shown: false
    property Item below
    property color edge: Token.color_ui_line
    visible: shown
    anchors.top: below ? below.bottom : parent.top
    anchors.topMargin: 12
    anchors.right: parent.right
    anchors.rightMargin: 12
    width: 248
    radius: Token.dimension_radius_lg
    color: Token.color_ui_glassStrong
    border.width: 1
    border.color: edge
    z: 20
    SoftShadow { visible: true }
}
