import QtQuick

// Translucent glass surface used by every HUD panel.
Rectangle {
    id: panel

    // .data (not .children) so non-visual children — input handlers,
    // Connections, Timers — are also accepted in the content slot.
    default property alias content: contentHost.data
    property string title: ""
    property bool accentBorder: false

    radius: Token.dimension_radius_md
    color: Token.color_ui_glass
    border.width: Token.dimension_border
    border.color: accentBorder
        ? Token.color_ui_accentLine
        : Token.color_ui_line

    Text {
        id: header
        visible: panel.title !== ""
        text: panel.title
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.margins: Token.dimension_spacing_md
        font.family: Token.typography_familyUi
        font.pixelSize: Token.typography_size_sm
        font.weight: Token.typography_weight_medium
        font.letterSpacing: 1.6
        color: Token.color_text_secondary
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
