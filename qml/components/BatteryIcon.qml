import QtQuick

// iOS-style battery glyph: hairline capsule, one continuous fill, terminal nub
// on the right. White when healthy; orange when low, red when critical.
// fraction < 0 means "unknown".
Item {
    id: root
    property real fraction: 0
    property bool critical: false
    readonly property bool known: fraction >= 0
    readonly property color tone: !known ? Token.color_text_muted
                                : critical ? Token.color_status_danger
                                : fraction < 0.3 ? Token.color_status_warn
                                : Token.color_ui_text
    implicitWidth: 27
    implicitHeight: 13
    width: implicitWidth; height: implicitHeight

    Rectangle {
        id: body
        width: parent.width - 3; height: parent.height
        radius: 4
        color: "transparent"
        border.width: 1
        border.color: Qt.alpha(Token.color_ui_text, 0.4)
        Rectangle {
            x: 2; y: 2
            height: parent.height - 4
            width: root.known ? Math.max(2, (parent.width - 4) * Math.min(1, root.fraction)) : 0
            radius: 2
            color: root.tone
            Behavior on width { NumberAnimation { duration: Token.motion_normal } }
        }
    }
    Rectangle {
        anchors.left: body.right
        anchors.leftMargin: 1
        anchors.verticalCenter: parent.verticalCenter
        width: 1.5; height: 4.5; radius: 1
        color: Qt.alpha(Token.color_ui_text, 0.4)
    }
}
