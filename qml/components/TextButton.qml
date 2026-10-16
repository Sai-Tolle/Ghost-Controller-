import QtQuick

// Generic button. tone: "neutral" | "primary" | "danger" | "ok".
// primary = filled system blue; others = tinted fill with coloured label.
Rectangle {
    id: root
    property string label: ""
    property string icon: ""
    property string tone: "neutral"
    signal clicked()
    implicitWidth: content.implicitWidth + 28
    implicitHeight: 32
    radius: Token.dimension_radius_sm + 2
    readonly property color toneColor: tone === "primary" ? Token.color_accent_primary
                                     : tone === "danger" ? Token.color_status_danger
                                     : tone === "ok" ? Token.color_status_ok : Token.color_ui_text
    readonly property color base: tone === "primary" ? Token.color_accent_primary
                                : tone === "neutral" ? Token.color_ui_fill : Qt.alpha(toneColor, 0.16)
    color: !enabled ? base
         : tap.pressed ? (tone === "primary" ? Qt.darker(base, 1.15) : tone === "neutral" ? Token.color_ui_fillPressed : Qt.alpha(toneColor, 0.3))
         : hover.hovered ? (tone === "primary" ? Qt.lighter(base, 1.1) : tone === "neutral" ? Token.color_ui_fillHover : Qt.alpha(toneColor, 0.24)) : base
    opacity: enabled ? 1 : Token.opacity_disabled
    scale: tap.pressed ? 0.97 : 1.0
    Behavior on color { ColorAnimation { duration: Token.motion_fast } }
    Behavior on scale { NumberAnimation { duration: Token.motion_fast; easing.type: Easing.OutCubic } }
    Row {
        id: content
        anchors.centerIn: parent
        spacing: 6
        Icon {
            visible: root.icon !== ""
            anchors.verticalCenter: parent.verticalCenter
            name: root.icon; size: 15; weight: 1.6
            color: lbl.color
        }
        Text {
            id: lbl
            anchors.verticalCenter: parent.verticalCenter
            text: root.label
            font.pixelSize: Token.typography_size_md
            font.weight: Font.Medium
            color: root.tone === "primary" ? Token.color_ui_onTint : root.tone === "neutral" ? Token.color_ui_text : root.toneColor
        }
    }
    HoverHandler { id: hover; cursorShape: Qt.PointingHandCursor }
    TapHandler { id: tap; enabled: root.enabled; gesturePolicy: TapHandler.ReleaseWithinBounds; onTapped: root.clicked() }
}
