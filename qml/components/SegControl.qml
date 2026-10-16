import QtQuick

// Segmented control (UISegmentedControl look): options = [{id, label}],
// emits picked(id). One recessed track, a raised thumb under the selection.
Rectangle {
    id: seg
    property var options: []
    property string current: ""
    signal picked(string id)
    readonly property int index: {
        for (var i = 0; i < options.length; i++) if (options[i].id === current) return i
        return -1
    }
    implicitHeight: 30
    height: implicitHeight
    radius: Token.dimension_radius_sm + 2
    color: Token.color_ui_fill

    Rectangle {                                       // thumb
        visible: seg.index >= 0
        y: 2; height: parent.height - 4
        width: (seg.width - 4) / Math.max(1, seg.options.length)
        x: 2 + seg.index * width
        radius: parent.radius - 2
        color: Token.color_ui_segThumb
        border.width: Token.theme === "light" ? 1 : 0          // white thumb needs an edge on the light track
        border.color: Token.color_ui_line
        Behavior on x { NumberAnimation { duration: Token.motion_normal; easing.type: Easing.OutCubic } }
    }
    Row {
        anchors.fill: parent
        anchors.margins: 2
        Repeater {
            model: seg.options
            delegate: Item {
                required property var modelData
                required property int index
                readonly property bool on: seg.current === modelData.id
                objectName: "seg_" + modelData.id
                width: parent.width / seg.options.length
                height: parent.height
                Rectangle {                           // divider between unselected segments
                    visible: index > 0 && !on && seg.index !== index - 1
                    width: 1; height: parent.height * 0.5
                    anchors.verticalCenter: parent.verticalCenter
                    color: Token.color_ui_lineStrong
                }
                Text {
                    anchors.centerIn: parent; text: modelData.label
                    font.pixelSize: Token.typography_size_sm
                    font.weight: on ? Font.DemiBold : Font.Medium
                    color: on ? Token.color_ui_text : Token.color_ui_textDim
                }
                HoverHandler { cursorShape: Qt.PointingHandCursor }
                TapHandler { gesturePolicy: TapHandler.ReleaseWithinBounds; onTapped: seg.picked(modelData.id) }
            }
        }
    }
}
