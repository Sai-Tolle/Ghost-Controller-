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
    implicitHeight: 36
    width: implicitWidth; height: implicitHeight
    radius: height / 2
    color: Token.color_ui_glassStrong
    border.width: 1
    border.color: Token.color_ui_line

    onSourceChanged: {
        var r = source ? source.result : null
        if (!source || !source.command || !r) return
        var err = r.error
        ok = !err
        var detail = err ? err : (r.status ? r.status : "done")
        text = source.command + " — " + detail
        hideTimer.restart()
    }
    Timer { id: hideTimer; interval: 4500; onTriggered: root.text = "" }

    Row {
        anchors.centerIn: parent
        spacing: 8
        Rectangle { width: 8; height: 8; radius: 4; anchors.verticalCenter: parent.verticalCenter
                    color: root.ok ? Token.color_status_ok : Token.color_status_danger }
        Text {
            id: label
            text: root.text
            font.pixelSize: Token.typography_size_md
            font.weight: Font.Medium
            color: Token.color_ui_text
        }
    }
    TapHandler { onTapped: root.text = "" }
}
