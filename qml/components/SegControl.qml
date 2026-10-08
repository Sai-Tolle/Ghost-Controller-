import QtQuick

// Segmented selector: options = [{id, label}], emits picked(id).
Row {
    id: seg
    property var options: []
    property string current: ""
    signal picked(string id)
    spacing: 4
    Repeater {
        model: seg.options
        delegate: Rectangle {
            required property var modelData
            readonly property bool on: seg.current === modelData.id
            objectName: "seg_" + modelData.id
            width: (seg.width - (seg.options.length - 1) * 4) / seg.options.length
            height: 28; radius: 6
            color: on ? Token.color_ui_accentSoft : (segHover.hovered ? Qt.rgba(1, 1, 1, 0.04) : "transparent")
            border.width: 1; border.color: on ? Token.color_ui_accentLine : Token.color_ui_line
            Text {
                anchors.centerIn: parent; text: modelData.label
                font.family: Token.typography_familyMono; font.pixelSize: 9; font.letterSpacing: 0.8
                font.weight: on ? Font.Bold : Font.Normal
                color: on ? Token.color_accent_primary : Token.color_ui_text
            }
            HoverHandler { id: segHover; cursorShape: Qt.PointingHandCursor }
            TapHandler { gesturePolicy: TapHandler.ReleaseWithinBounds; onTapped: seg.picked(modelData.id) }
        }
    }
}
