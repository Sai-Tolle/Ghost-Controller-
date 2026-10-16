import QtQuick
import QtQuick.Controls
import "../components"

// CONNECTION settings: link type (auto / UDP / TCP / serial), its target,
// auto-connect at startup, and live CONNECT / DISCONNECT. Opened from the
// GCS ▾ menu or by clicking the link pill in the top bar.
Popup {
    id: root
    objectName: "linkDialog"
    modal: true
    focus: true
    width: 470
    padding: 18
    anchors.centerIn: Overlay.overlay
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
    enter: Transition {
        NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Token.motion_fast; easing.type: Easing.OutCubic }
        NumberAnimation { property: "scale"; from: 0.94; to: 1; duration: Token.motion_normal; easing.type: Easing.OutBack; easing.overshoot: 1.1 }
    }
    exit: Transition {
        NumberAnimation { property: "opacity"; from: 1; to: 0; duration: Token.motion_fast; easing.type: Easing.InCubic }
        NumberAnimation { property: "scale"; from: 1; to: 0.98; duration: Token.motion_fast }
    }

    // ---- editable copy of the config ---------------------------------------------------
    property string fMode: "auto"
    property string fRole: "udpin"
    property bool fAuto: true
    property string errorText: ""
    property string savedText: ""

    function load() {
        var c = Link.config
        fMode = c.mode; fRole = c.udp_role; fAuto = c.auto_connect
        udpHost.text = c.udp_host; udpPort.text = String(c.udp_port)
        tcpHost.text = c.tcp_host; tcpPort.text = String(c.tcp_port)
        serialPort.text = c.serial_port; baud.text = String(c.baud)
        errorText = ""; savedText = ""
        Link.refreshPorts()
    }
    function form() {
        return { mode: fMode, udp_role: fRole, udp_host: udpHost.text, udp_port: udpPort.text,
                 tcp_host: tcpHost.text, tcp_port: tcpPort.text, serial_port: serialPort.text,
                 baud: baud.text, auto_connect: fAuto }
    }
    function commit(connectNow) {
        var res = Link.apply(form(), connectNow)
        if (!res.ok) { errorText = res.error; savedText = ""; return }
        errorText = ""
        savedText = connectNow ? "Saved — connecting on the new link" : "Saved"
    }
    onAboutToShow: load()

    readonly property color statusTone: Link.status === "connected" ? Token.color_status_ok
                                      : Link.status === "disconnected" || Link.status === "unavailable" ? Token.color_text_muted
                                      : Link.status === "retrying" ? Token.color_status_danger : Token.color_status_warn
    readonly property string statusText: Link.status === "connected" ? "Connected"
                                       : Link.status === "waiting" ? "Waiting for heartbeat"
                                       : Link.status === "retrying" ? "Retrying"
                                       : Link.status === "disconnected" ? "Disconnected"
                                       : Link.status === "unavailable" ? "Unavailable" : "Connecting"

    background: Rectangle {
        radius: Token.dimension_radius_xl; color: Token.color_ui_glassStrong
        border.width: 1; border.color: Token.color_ui_line
    }
    Overlay.modal: Rectangle { color: Qt.rgba(0, 0, 0, 0.45) }

    contentItem: Column {
        spacing: 12

        PanelTitle { width: parent.width; text: "Connection"; onClosed: root.close() }

        // ---- live status ------------------------------------------------------------------
        Rectangle {
            width: parent.width; height: statusCol.implicitHeight + 24; radius: 10
            color: Token.color_ui_fill
            Column {
                id: statusCol
                anchors.left: parent.left; anchors.leftMargin: 12
                anchors.right: linkBtn.left; anchors.rightMargin: 10
                anchors.verticalCenter: parent.verticalCenter
                spacing: 3
                Row {
                    spacing: 7
                    Rectangle { width: 7; height: 7; radius: 3.5; color: root.statusTone
                                anchors.verticalCenter: parent.verticalCenter }
                    Text {
                        objectName: "linkStatusText"
                        text: root.statusText
                        font.pixelSize: 13
                        font.weight: Font.DemiBold; color: Token.color_ui_text
                    }
                }
                Text {
                    width: parent.width; elide: Text.ElideMiddle
                    text: Link.target !== "" ? Link.target : "—"
                    font.pixelSize: 12; color: Token.color_ui_textDim
                }
                Text {
                    visible: Link.error !== "" && Link.status !== "connected"
                    width: parent.width; wrapMode: Text.WordWrap; maximumLineCount: 2; elide: Text.ElideRight
                    text: Link.error
                    font.pixelSize: 12; color: Token.color_status_danger
                }
            }
            TextButton {
                id: linkBtn
                objectName: "linkToggleBtn"
                anchors.right: parent.right; anchors.rightMargin: 10
                anchors.verticalCenter: parent.verticalCenter
                width: 112
                enabled: Link.available
                label: Link.enabled ? "Disconnect" : "Connect"
                tone: Link.enabled ? "danger" : "ok"
                onClicked: Link.enabled ? Link.disconnectLink() : Link.connectLink()
            }
        }

        // ---- link type ------------------------------------------------------------------------
        SectionLabel { text: "Link Type" }
        SegControl {
            width: parent.width
            options: [{ id: "auto", label: "Auto" }, { id: "udp", label: "UDP" },
                      { id: "tcp", label: "TCP" }, { id: "serial", label: "Serial" }]
            current: root.fMode
            onPicked: function(id) { root.fMode = id }
        }

        // AUTO

        // UDP
        Column {
            visible: root.fMode === "udp"
            width: parent.width
            spacing: 10
            SegControl {
                width: parent.width
                options: [{ id: "udpin", label: "Listen (udpin)" }, { id: "udpout", label: "Send To (udpout)" }]
                current: root.fRole
                onPicked: function(id) {
                    if (id === "udpin" && udpHost.text === "127.0.0.1") udpHost.text = "0.0.0.0"
                    root.fRole = id
                }
            }
            Row {
                spacing: 10
                FormField { id: udpHost; objectName: "udpHost"; title: root.fRole === "udpin" ? "Listen Address" : "Vehicle Host / IP"; fieldWidth: 250 }
                FormField { id: udpPort; objectName: "udpPort"; title: "Port"; fieldWidth: 90 }
            }
        }

        // TCP
        Column {
            visible: root.fMode === "tcp"
            width: parent.width
            spacing: 10
            Row {
                spacing: 10
                FormField { id: tcpHost; title: "Host / IP"; fieldWidth: 250 }
                FormField { id: tcpPort; title: "Port"; fieldWidth: 90 }
            }
        }

        // SERIAL
        Column {
            visible: root.fMode === "serial"
            width: parent.width
            spacing: 8
            Row {
                spacing: 10
                FormField { id: serialPort; title: "Port"; fieldWidth: 250; placeholder: "/dev/ttyACM0" }
                FormField { id: baud; title: "Baud"; fieldWidth: 90 }
            }
            Flow {
                width: parent.width; spacing: 4
                Repeater {
                    model: [57600, 115200, 460800, 921600]
                    delegate: TextButton {
                        required property var modelData
                        label: String(modelData); height: 24
                        tone: baud.text === String(modelData) ? "primary" : "neutral"
                        onClicked: baud.text = String(modelData)
                    }
                }
            }
            Row {
                spacing: 8
                SectionLabel { text: "Detected Ports"; anchors.verticalCenter: parent.verticalCenter }
                TextButton { label: "Rescan"; height: 22; onClicked: Link.refreshPorts() }
            }
            Column {
                width: parent.width
                spacing: 4
                Text {
                    visible: Link.serialPorts.length === 0
                    text: "No serial devices found"
                    width: parent.width; wrapMode: Text.WordWrap
                    font.pixelSize: 11; color: Token.color_text_muted
                }
                Repeater {
                    model: Link.serialPorts
                    delegate: Rectangle {
                        required property var modelData
                        readonly property bool on: serialPort.text === modelData.device
                        width: parent.width; height: 28; radius: 6
                        color: on ? Token.color_ui_accentSoft : (pHover.hovered ? Token.color_ui_fill : "transparent")
                        border.width: 1; border.color: on ? Token.color_ui_accentLine : Token.color_ui_line
                        Text {
                            anchors.left: parent.left; anchors.leftMargin: 10
                            anchors.right: parent.right; anchors.rightMargin: 10
                            anchors.verticalCenter: parent.verticalCenter
                            elide: Text.ElideRight
                            text: modelData.device + (modelData.description ? "   " + modelData.description : "")
                            font.pixelSize: 11
                            color: on ? Token.color_accent_primary : Token.color_ui_text
                        }
                        HoverHandler { id: pHover; cursorShape: Qt.PointingHandCursor }
                        TapHandler { onTapped: serialPort.text = modelData.device }
                    }
                }
            }
        }

        Rectangle { width: parent.width; height: 1; color: Token.color_ui_line }

        // ---- auto-connect --------------------------------------------------------------------------
        Item {
            width: parent.width; height: 34
            Column {
                anchors.left: parent.left; anchors.verticalCenter: parent.verticalCenter
                width: parent.width - sw.width - 10
                spacing: 2
                Text { text: "Connect automatically"; font.pixelSize: 13
                       color: Token.color_ui_text }
            }
            Rectangle {                                       // toggle switch
                id: sw
                objectName: "autoConnectSwitch"
                anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                width: 44; height: 26; radius: 13
                color: root.fAuto ? Token.color_status_ok : Token.color_ui_fillPressed
                Behavior on color { ColorAnimation { duration: Token.motion_fast } }
                Rectangle {                                   // iOS-style knob
                    width: 22; height: 22; radius: 11
                    anchors.verticalCenter: parent.verticalCenter
                    x: root.fAuto ? parent.width - width - 2 : 2
                    color: "#FFFFFF"
                    Behavior on x { NumberAnimation { duration: Token.motion_normal; easing.type: Easing.OutCubic } }
                }
                HoverHandler { cursorShape: Qt.PointingHandCursor }
                TapHandler { onTapped: root.fAuto = !root.fAuto }
            }
        }

        // ---- result + actions ------------------------------------------------------------------------
        Text {
            visible: root.errorText !== "" || root.savedText !== ""
            width: parent.width; wrapMode: Text.WordWrap
            text: root.errorText !== "" ? root.errorText : root.savedText
            font.pixelSize: 11
            color: root.errorText !== "" ? Token.color_status_danger : Token.color_status_ok
        }
        Row {
            spacing: 8
            TextButton { objectName: "linkApplyBtn"; label: "Apply & Connect"; tone: "primary"; width: 140
                         enabled: Link.available; onClicked: root.commit(true) }
            TextButton { label: "Save"; width: 80; onClicked: root.commit(false) }
            TextButton { label: "Close"; width: 80; onClicked: root.close() }
        }
    }
}
