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
    implicitHeight: 32
    width: implicitWidth; height: implicitHeight
    radius: 8
    color: isDanger ? Qt.rgba(0.80, 0.16, 0.16, 0.94) : Qt.rgba(0.72, 0.45, 0.05, 0.94)
    border.width: 1
    border.color: isDanger ? "#FF8A8A" : "#FFC970"

    Row {
        anchors.centerIn: parent
        spacing: 8
        Rectangle { width: 7; height: 7; radius: 3.5; color: "#FFFFFF"; anchors.verticalCenter: parent.verticalCenter }
        Text {
            id: label
            text: root.shown ? root.shown.text.toUpperCase() : ""
            font.family: Token.typography_familyMono
            font.pixelSize: 11
            font.weight: Font.Bold
            font.letterSpacing: 1.6
            color: "#FFFFFF"
        }
    }
    HoverHandler { cursorShape: Qt.PointingHandCursor }
    TapHandler {
        gesturePolicy: TapHandler.ReleaseWithinBounds
        onTapped: if (root.shown && root.shown.id !== undefined) Telemetry.retireAlert(root.shown.id)
    }
}
