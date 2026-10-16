import QtQuick

// Translucent material surface (macOS/iPadOS-style dark "regular material"):
// tinted fill, 1px hairline, continuous large radius and a soft ambient shadow.
Rectangle {
    id: panel

    // .data (not .children) so non-visual children — input handlers,
    // Connections, Timers — are also accepted in the content slot.
    default property alias content: contentHost.data
    property string title: ""
    property bool accentBorder: false
    property bool elevated: true

    radius: Token.dimension_radius_lg
    color: Token.color_ui_glass
    border.width: Token.dimension_border
    border.color: accentBorder ? Qt.alpha(Token.color_accent_primary, 0.6) : Token.color_ui_line

    SoftShadow { visible: panel.elevated }

    Text {
        id: header
        visible: panel.title !== ""
        text: panel.title
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.margins: Token.dimension_spacing_md
        font.pixelSize: Token.typography_size_md
        font.weight: Font.DemiBold
        color: Token.color_ui_text
    }

    Item {
        id: contentHost
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.margins: Token.dimension_spacing_md
        anchors.top: panel.title !== "" ? header.bottom : parent.top
        anchors.topMargin: Token.dimension_spacing_md
    }
}
