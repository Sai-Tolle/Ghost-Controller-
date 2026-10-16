import QtQuick

// Top-centre alert. Colour follows the alert's LEVEL (danger/warn). It used to
// be derived from keywords in the text, so a `danger` alert such as
// "Battery critical 12%" (no keyword) rendered in the OK green.
Rectangle {
    id: root
    property var alerts: Telemetry.alerts
    readonly property var shown: {
        var danger = null, warn = null
        for (var i = 0; i < alerts.length; i++) {
            var a = alerts[i]
            if (a.level === "danger") { if (danger === null) danger = a }
            else if (warn === null) warn = a
        }
        return danger !== null ? danger : warn
    }
    readonly property bool isDanger: shown !== null && shown.level === "danger"

    visible: shown !== null
    implicitWidth: label.implicitWidth + 36
    implicitHeight: 36
    width: implicitWidth; height: implicitHeight
    radius: height / 2
    color: isDanger ? Token.color_status_danger : Token.color_status_warn

    Row {
        anchors.centerIn: parent
        spacing: 8
        Icon { name: "warning"; size: 16; weight: 1.7; color: root.isDanger ? "#FFFFFF" : "#1C1C1E"; anchors.verticalCenter: parent.verticalCenter }
        Text {
            id: label
            text: root.shown ? root.shown.text : ""
            font.pixelSize: Token.typography_size_md
            font.weight: Font.DemiBold
            color: root.isDanger ? "#FFFFFF" : "#1C1C1E"
        }
    }
    HoverHandler { cursorShape: Qt.PointingHandCursor }
    TapHandler {
        gesturePolicy: TapHandler.ReleaseWithinBounds
        onTapped: if (root.shown && root.shown.id !== undefined) Telemetry.retireAlert(root.shown.id)
    }
}
