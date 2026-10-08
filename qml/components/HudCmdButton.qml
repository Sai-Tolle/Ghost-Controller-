import QtQuick

// Command-dock button. Fixed geometry: the size NEVER depends on the label.
// (The old version bound width to the text, so ARM -> DISARM re-evaluated the
// width and the button shrank out of the layout the moment it was clicked.)
// tone: "neutral" | "primary" | "danger".
Rectangle {
    id: root

    property string label: ""
    property string sublabel: ""
    property string tone: "neutral"
    property bool busy: false
    readonly property bool hovered: hover.hovered
    readonly property bool pressed: tap.pressed
    signal clicked()
    signal doubleClicked()

    implicitWidth: 108
    implicitHeight: 36
    radius: 8

    readonly property color base: tone === "primary" ? "#2F7DF6"
                                : tone === "danger"  ? Token.color_ui_dangerSoft
                                : Qt.rgba(0.04, 0.05, 0.075, 0.74)
    color: !enabled ? base
         : pressed ? Qt.lighter(base, 1.25)
         : hovered ? Qt.lighter(base, 1.12) : base
    border.width: 1
    border.color: tone === "primary" ? Token.color_accent_primary
                : tone === "danger"  ? Token.color_ui_dangerLine
                : hovered ? Token.color_ui_lineStrong : Token.color_ui_line
    opacity: enabled ? 1.0 : 0.4
    Behavior on color { ColorAnimation { duration: Token.motion_fast } }

    Row {
        anchors.centerIn: parent
        spacing: 8
        Text {
            anchors.verticalCenter: parent.verticalCenter
            text: root.busy ? "…" : root.label
            width: Math.min(implicitWidth, root.width - 16)
            elide: Text.ElideRight
            font.family: Token.typography_familyMono
            font.pixelSize: 11
            font.weight: Font.DemiBold
            font.letterSpacing: 1.4
            color: root.tone === "danger" ? Token.color_status_danger
                 : root.tone === "primary" ? "#FFFFFF" : "#DCE6F4"
        }
        Text {
            visible: root.sublabel !== ""
            anchors.verticalCenter: parent.verticalCenter
            text: root.sublabel
            font.family: Token.typography_familyMono
            font.pixelSize: 9
            color: Qt.alpha(parent.children[0].color, 0.65)
        }
    }

    HoverHandler { id: hover; cursorShape: root.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor }
    TapHandler {
        id: tap
        enabled: root.enabled
        gesturePolicy: TapHandler.ReleaseWithinBounds
        onTapped: root.clicked()
        onDoubleTapped: root.doubleClicked()
    }
}
