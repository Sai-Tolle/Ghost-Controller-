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

    readonly property color tone: cyan ? "#5ADBFF" : Token.color_accent_primary
    implicitWidth: btnText.implicitWidth + 28
    implicitHeight: 30

    Rectangle {
        anchors.fill: parent
        radius: 7
        color: popup.opened ? Qt.alpha(root.tone, 0.16) : (hover.hovered ? Qt.rgba(1,1,1,0.05) : "transparent")
        border.width: 1
        border.color: popup.opened ? root.tone : Token.color_ui_lineStrong
        Text {
            id: btnText
            anchors.centerIn: parent
            text: root.label + "  ▾"
            font.family: Token.typography_familyMono
            font.pixelSize: 11
            font.weight: Font.DemiBold
            font.letterSpacing: 1.4
            color: popup.opened ? root.tone : Token.color_ui_text
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
        width: 220
        padding: 4
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        background: Rectangle {
            radius: 10
            color: Token.color_ui_glassStrong
            border.width: 1
            border.color: Token.color_ui_lineStrong
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
                    height: isSep ? 9 : 30
                    Rectangle {
                        visible: row.isSep
                        anchors.centerIn: parent
                        width: parent.width - 12; height: 1
                        color: Token.color_ui_line
                    }
                    Rectangle {
                        visible: !row.isSep
                        anchors.fill: parent
                        radius: 6
                        color: rowHover.hovered ? Qt.rgba(1, 1, 1, 0.07) : "transparent"
                        Text {
                            anchors.left: parent.left
                            anchors.leftMargin: 10
                            anchors.verticalCenter: parent.verticalCenter
                            text: row.modelData.text || ""
                            font.family: Token.typography_familyUi
                            font.pixelSize: 12
                            color: row.modelData.danger ? Token.color_status_danger : Token.color_ui_text
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
