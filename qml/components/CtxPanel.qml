import QtQuick

// Shared top-right context slot (waypoint / survey / orbit / fence share it).
Rectangle {
    property bool shown: false
    property Item below
    property color edge: Token.color_ui_lineStrong
    visible: shown
    anchors.top: below ? below.bottom : parent.top
    anchors.topMargin: 14
    anchors.right: parent.right
    anchors.rightMargin: 14
    width: 226
    radius: 12
    color: Token.color_ui_glassStrong
    border.width: 1
    border.color: edge
    z: 20
}
