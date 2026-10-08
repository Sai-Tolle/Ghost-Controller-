import QtQuick

// Generic button. tone: "neutral" | "primary" | "danger" | "ok".
Rectangle {
    id: root
    property string label: ""
    property string tone: "neutral"
    signal clicked()
    implicitWidth: lbl.implicitWidth + 24
    implicitHeight: 30
    radius: 7
    readonly property color toneColor: tone === "primary" ? Token.color_accent_primary
                                     : tone === "danger" ? Token.color_status_danger
                                     : tone === "ok" ? Token.color_status_ok : Token.color_ui_text
    color: !enabled ? "transparent"
         : tap.pressed ? Qt.alpha(toneColor, 0.28)
         : hover.hovered ? Qt.alpha(toneColor, 0.16) : Qt.alpha(toneColor, tone === "neutral" ? 0.04 : 0.1)
    border.width: 1
    border.color: tone === "neutral" ? Token.color_ui_lineStrong : Qt.alpha(toneColor, 0.55)
    opacity: enabled ? 1 : 0.4
    Text {
        id: lbl
        anchors.centerIn: parent
        text: root.label
        font.family: Token.typography_familyMono
        font.pixelSize: 10
        font.weight: Font.DemiBold
        font.letterSpacing: 1.2
        color: root.toneColor
    }
    HoverHandler { id: hover; cursorShape: Qt.PointingHandCursor }
    TapHandler { id: tap; enabled: root.enabled; gesturePolicy: TapHandler.ReleaseWithinBounds; onTapped: root.clicked() }
}
