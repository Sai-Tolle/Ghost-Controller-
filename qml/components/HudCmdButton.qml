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
    implicitHeight: Token.dimension_hud_actionButtonHeight
    radius: Token.dimension_radius_md

    readonly property color base: tone === "primary" ? Token.color_accent_primary
                                : tone === "danger"  ? Token.color_ui_dangerSoft
                                : Token.color_ui_fill
    color: !enabled ? Qt.alpha(Token.color_ui_text, 0.06)
         : pressed ? (tone === "neutral" ? Token.color_ui_fillPressed : Qt.darker(base, 1.15))
         : hovered ? (tone === "neutral" ? Token.color_ui_fillHover : Qt.lighter(base, 1.12)) : base
    scale: pressed ? 0.97 : 1.0
    Behavior on color { ColorAnimation { duration: Token.motion_fast } }
    Behavior on scale { NumberAnimation { duration: Token.motion_fast; easing.type: Easing.OutCubic } }

    Row {
        anchors.centerIn: parent
        spacing: 6
        Text {
            anchors.verticalCenter: parent.verticalCenter
            text: root.busy ? "…" : root.label
            width: Math.min(implicitWidth, root.width - 16)
            elide: Text.ElideRight
            font.pixelSize: Token.typography_size_md
            font.weight: Font.DemiBold
            color: !root.enabled ? Token.color_ui_textTertiary
                 : root.tone === "danger" ? Token.color_status_danger : root.tone === "primary" ? Token.color_ui_onTint : Token.color_ui_text
        }
        Text {
            visible: root.sublabel !== ""
            anchors.verticalCenter: parent.verticalCenter
            text: root.sublabel
            font.pixelSize: Token.typography_size_sm
            color: !root.enabled ? Token.color_ui_textTertiary
                 : root.tone === "danger" ? Qt.alpha(Token.color_status_danger, 0.7) : Token.color_ui_textDim
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
