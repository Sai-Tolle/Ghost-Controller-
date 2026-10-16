import QtQuick
import QtQuick.Controls

// Toolbar dropdown built on Popup. The old version faked outside-click dismissal
// with a 1500x900 MouseArea at z:-1 inside a 28 px item; Popup gives real
// overlay stacking, outside-press and Esc handling, and only one menu at a time.
Item {
    id: root
    property string label: ""
    property bool cyan: false
    property var items: []            // [{text, action, danger}] | [{sep: true}]
    signal action(string name)

    readonly property color tone: cyan ? "#64D2FF" : Token.color_accent_primary
    implicitWidth: btnText.implicitWidth + 40
    implicitHeight: 30

    Rectangle {
        anchors.fill: parent
        radius: Token.dimension_radius_sm + 1
        color: popup.opened ? Token.color_ui_fillPressed : (hover.hovered ? Token.color_ui_fillHover : Token.color_ui_fill)
        Behavior on color { ColorAnimation { duration: Token.motion_fast } }
        Text {
            id: btnText
            anchors.verticalCenter: parent.verticalCenter
            anchors.left: parent.left; anchors.leftMargin: 12
            text: root.label
            font.pixelSize: Token.typography_size_md
            font.weight: Font.Medium
            color: Token.color_ui_text
        }
        Icon {
            anchors.verticalCenter: parent.verticalCenter
            anchors.right: parent.right; anchors.rightMargin: 10
            name: "chevron.down"; size: 11; weight: 1.6
            color: Token.color_ui_textDim
            rotation: popup.opened ? 180 : 0
            Behavior on rotation { NumberAnimation { duration: Token.motion_fast; easing.type: Easing.OutCubic } }
        }
    }
    HoverHandler { id: hover; cursorShape: Qt.PointingHandCursor }
    TapHandler {
        gesturePolicy: TapHandler.ReleaseWithinBounds
        onTapped: popup.opened ? popup.close() : popup.open()
    }

    Popup {
        id: popup
        y: root.height + 6
        width: 232
        padding: 5
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        transformOrigin: Popup.Top
        enter: Transition {
            NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Token.motion_fast; easing.type: Easing.OutCubic }
            NumberAnimation { property: "scale"; from: 0.96; to: 1; duration: Token.motion_normal; easing.type: Easing.OutBack; easing.overshoot: 1.1 }
        }
        exit: Transition {
            NumberAnimation { property: "opacity"; from: 1; to: 0; duration: Token.motion_fast; easing.type: Easing.InCubic }
            NumberAnimation { property: "scale"; from: 1; to: 0.98; duration: Token.motion_fast }
        }
        background: Rectangle {
            radius: Token.dimension_radius_md
            color: Token.color_ui_glassStrong
            border.width: 1
            border.color: Token.color_ui_line
        }
        contentItem: Column {
            spacing: 0
            Repeater {
                model: root.items
                delegate: Item {
                    id: row
                    required property var modelData
                    readonly property bool isSep: modelData.sep === true
                    width: popup.availableWidth
                    height: isSep ? 11 : 28
                    Rectangle {
                        visible: row.isSep
                        anchors.centerIn: parent
                        width: parent.width - 12; height: 1
                        color: Token.color_ui_line
                    }
                    Rectangle {
                        visible: !row.isSep
                        anchors.fill: parent
                        radius: Token.dimension_radius_sm - 1
                        color: rowHover.hovered ? Token.color_accent_primary : "transparent"
                        Icon {
                            visible: !!row.modelData.icon
                            anchors.left: parent.left
                            anchors.leftMargin: 9
                            anchors.verticalCenter: parent.verticalCenter
                            name: row.modelData.icon || ""; size: 15; weight: 1.5
                            color: rowHover.hovered ? "#FFFFFF" : row.modelData.danger ? Token.color_status_danger : Token.color_ui_textDim
                        }
                        Text {
                            anchors.left: parent.left
                            anchors.leftMargin: row.modelData.icon ? 32 : 10
                            anchors.verticalCenter: parent.verticalCenter
                            text: row.modelData.text || ""
                            font.pixelSize: 13
                            color: rowHover.hovered ? "#FFFFFF" : row.modelData.danger ? Token.color_status_danger : Token.color_ui_text
                        }
                    }
                    HoverHandler { id: rowHover; enabled: !row.isSep; cursorShape: Qt.PointingHandCursor }
                    TapHandler {
                        enabled: !row.isSep
                        gesturePolicy: TapHandler.ReleaseWithinBounds
                        onTapped: { popup.close(); root.action(row.modelData.action) }
                    }
                }
            }
        }
    }
}
