import QtQuick

// Feedback for every vehicle command. Before this, Vehicle.lastActionResult was
// never read by the UI: ARM / TAKEOFF / mode changes that the vehicle (or the
// command guard) refused failed silently.
Rectangle {
    id: root
    property var source: Vehicle.lastActionResult        // {command, result}
    property string text: ""
    property bool ok: true

    visible: text !== ""
    implicitWidth: label.implicitWidth + 32
    implicitHeight: 30
    width: implicitWidth; height: implicitHeight
    radius: 8
    color: Token.color_ui_glassStrong
    border.width: 1
    border.color: ok ? Token.color_ui_okLine : Token.color_ui_dangerLine

    onSourceChanged: {
        var r = source ? source.result : null
        if (!source || !source.command || !r) return
        var err = r.error
        ok = !err
        var detail = err ? err : (r.status ? r.status : "done")
        text = source.command + "  ·  " + detail
        hideTimer.restart()
    }
    Timer { id: hideTimer; interval: 4500; onTriggered: root.text = "" }

    Row {
        anchors.centerIn: parent
        spacing: 8
        Rectangle { width: 6; height: 6; radius: 3; anchors.verticalCenter: parent.verticalCenter
                    color: root.ok ? Token.color_status_ok : Token.color_status_danger }
        Text {
            id: label
            text: root.text
            font.family: Token.typography_familyMono
            font.pixelSize: 10
            font.letterSpacing: 1
            color: root.ok ? Token.color_status_ok : "#FF8A8A"
        }
    }
    TapHandler { onTapped: root.text = "" }
}
