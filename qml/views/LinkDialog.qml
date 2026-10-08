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
    readonly property string statusText: Link.status === "connected" ? "CONNECTED"
                                       : Link.status === "waiting" ? "WAITING FOR HEARTBEAT"
                                       : Link.status === "retrying" ? "RETRYING"
                                       : Link.status === "disconnected" ? "DISCONNECTED"
                                       : Link.status === "unavailable" ? "UNAVAILABLE" : "CONNECTING"

    background: Rectangle {
        radius: 12; color: Token.color_ui_glassStrong
        border.width: 1; border.color: Token.color_ui_lineStrong
    }
    Overlay.modal: Rectangle { color: Qt.rgba(0, 0, 0, 0.45) }

    contentItem: Column {
        spacing: 12

        Row {
            width: parent.width
            Text {
                text: "CONNECTION"
                font.family: Token.typography_familyMono; font.pixelSize: 11
                font.weight: Font.Bold; font.letterSpacing: 2; color: Token.color_ui_text
                width: parent.width - closeX.width
            }
            Text {
                id: closeX
                text: "✕"; font.pixelSize: 13; color: Token.color_ui_textDim
                HoverHandler { cursorShape: Qt.PointingHandCursor }
                TapHandler { onTapped: root.close() }
            }
        }
        Rectangle { width: parent.width; height: 1; color: Token.color_ui_line }

        // ---- live status ------------------------------------------------------------------
        Rectangle {
            width: parent.width; height: statusCol.implicitHeight + 20; radius: 8
            color: Qt.alpha(root.statusTone, 0.08)
            border.width: 1; border.color: Qt.alpha(root.statusTone, 0.45)
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
                        font.family: Token.typography_familyMono; font.pixelSize: 11
                        font.weight: Font.Bold; font.letterSpacing: 1.4; color: root.statusTone
                    }
                }
                Text {
                    width: parent.width; elide: Text.ElideMiddle
                    text: Link.target !== "" ? Link.target : "—"
                    font.family: Token.typography_familyMono; font.pixelSize: 10; color: Token.color_ui_text
                }
                Text {
                    visible: Link.error !== "" && Link.status !== "connected"
                    width: parent.width; wrapMode: Text.WordWrap; maximumLineCount: 2; elide: Text.ElideRight
                    text: Link.error
                    font.family: Token.typography_familyMono; font.pixelSize: 9; color: Token.color_text_muted
                }
            }
            TextButton {
                id: linkBtn
                objectName: "linkToggleBtn"
                anchors.right: parent.right; anchors.rightMargin: 10
                anchors.verticalCenter: parent.verticalCenter
                width: 112
                enabled: Link.available
                label: Link.enabled ? "DISCONNECT" : "CONNECT"
                tone: Link.enabled ? "danger" : "ok"
                onClicked: Link.enabled ? Link.disconnectLink() : Link.connectLink()
            }
        }

        // ---- link type ------------------------------------------------------------------------
        SectionLabel { text: "LINK TYPE" }
        SegControl {
            width: parent.width
            options: [{ id: "auto", label: "AUTO" }, { id: "udp", label: "UDP" },
                      { id: "tcp", label: "TCP" }, { id: "serial", label: "SERIAL" }]
            current: root.fMode
            onPicked: function(id) { root.fMode = id }
        }

        // AUTO
        Text {
            visible: root.fMode === "auto"
            width: parent.width; wrapMode: Text.WordWrap
            text: "Uses the first USB serial flight controller it finds, otherwise listens for UDP on 127.0.0.1:14550 (PX4 / ArduPilot SITL)."
            font.family: Token.typography_familyMono; font.pixelSize: 10; color: Token.color_text_muted
        }

        // UDP
        Column {
            visible: root.fMode === "udp"
            width: parent.width
            spacing: 10
            SegControl {
                width: parent.width
                options: [{ id: "udpin", label: "LISTEN (udpin)" }, { id: "udpout", label: "SEND TO (udpout)" }]
                current: root.fRole
                onPicked: function(id) {
                    if (id === "udpin" && udpHost.text === "127.0.0.1") udpHost.text = "0.0.0.0"
                    root.fRole = id
                }
            }
            Row {
                spacing: 10
                FormField { id: udpHost; objectName: "udpHost"; title: root.fRole === "udpin" ? "LISTEN ADDRESS" : "VEHICLE HOST / IP"; fieldWidth: 250 }
                FormField { id: udpPort; objectName: "udpPort"; title: "PORT"; fieldWidth: 90 }
            }
            Text {
                width: parent.width; wrapMode: Text.WordWrap
                text: root.fRole === "udpin"
                      ? "Listen: the vehicle / radio / SITL sends to this GCS. 0.0.0.0 accepts from any network interface."
                      : "Send to: this GCS initiates the link to a vehicle or companion computer at that address."
                font.family: Token.typography_familyMono; font.pixelSize: 9; color: Token.color_text_muted
            }
        }

        // TCP
        Column {
            visible: root.fMode === "tcp"
            width: parent.width
            spacing: 10
            Row {
                spacing: 10
                FormField { id: tcpHost; title: "HOST / IP"; fieldWidth: 250 }
                FormField { id: tcpPort; title: "PORT"; fieldWidth: 90 }
            }
            Text {
                width: parent.width; wrapMode: Text.WordWrap
                text: "ArduPilot SITL serves MAVLink on TCP 5760."
                font.family: Token.typography_familyMono; font.pixelSize: 9; color: Token.color_text_muted
            }
        }

        // SERIAL
        Column {
            visible: root.fMode === "serial"
            width: parent.width
            spacing: 8
            Row {
                spacing: 10
                FormField { id: serialPort; title: "PORT"; fieldWidth: 250; placeholder: "/dev/ttyACM0" }
                FormField { id: baud; title: "BAUD"; fieldWidth: 90 }
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
                SectionLabel { text: "DETECTED PORTS"; anchors.verticalCenter: parent.verticalCenter }
                TextButton { label: "RESCAN"; height: 22; onClicked: Link.refreshPorts() }
            }
            Column {
                width: parent.width
                spacing: 4
                Text {
                    visible: Link.serialPorts.length === 0
                    text: "No serial devices found — plug in the flight controller or radio and RESCAN."
                    width: parent.width; wrapMode: Text.WordWrap
                    font.family: Token.typography_familyMono; font.pixelSize: 9; color: Token.color_text_muted
                }
                Repeater {
                    model: Link.serialPorts
                    delegate: Rectangle {
                        required property var modelData
                        readonly property bool on: serialPort.text === modelData.device
                        width: parent.width; height: 28; radius: 6
                        color: on ? Token.color_ui_accentSoft : (pHover.hovered ? Qt.rgba(1, 1, 1, 0.05) : "transparent")
                        border.width: 1; border.color: on ? Token.color_ui_accentLine : Token.color_ui_line
                        Text {
                            anchors.left: parent.left; anchors.leftMargin: 10
                            anchors.right: parent.right; anchors.rightMargin: 10
                            anchors.verticalCenter: parent.verticalCenter
                            elide: Text.ElideRight
                            text: modelData.device + (modelData.description ? "   " + modelData.description : "")
                            font.family: Token.typography_familyMono; font.pixelSize: 10
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
                Text { text: "AUTO-CONNECT"; font.family: Token.typography_familyMono; font.pixelSize: 10
                       font.weight: Font.Bold; font.letterSpacing: 1.2; color: Token.color_ui_text }
                Text {
                    width: parent.width; wrapMode: Text.WordWrap
                    text: root.fAuto ? "Backend connects at startup and keeps reconnecting after a drop."
                                     : "App starts disconnected — press CONNECT when ready."
                    font.family: Token.typography_familyMono; font.pixelSize: 9; color: Token.color_text_muted
                }
            }
            Rectangle {                                       // toggle switch
                id: sw
                objectName: "autoConnectSwitch"
                anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                width: 42; height: 22; radius: 11
                color: root.fAuto ? Token.color_ui_okSoft : Qt.rgba(1, 1, 1, 0.06)
                border.width: 1; border.color: root.fAuto ? Token.color_ui_okLine : Token.color_ui_lineStrong
                Rectangle {
                    width: 16; height: 16; radius: 8
                    anchors.verticalCenter: parent.verticalCenter
                    x: root.fAuto ? parent.width - width - 3 : 3
                    color: root.fAuto ? Token.color_status_ok : Token.color_ui_textDim
                    Behavior on x { NumberAnimation { duration: Token.motion_fast } }
                }
                HoverHandler { cursorShape: Qt.PointingHandCursor }
                TapHandler { onTapped: root.fAuto = !root.fAuto }
            }
        }

        // ---- result + actions ------------------------------------------------------------------------
        Text {
            width: parent.width; elide: Text.ElideMiddle
            text: "→ " + Link.preview(root.form())
            font.family: Token.typography_familyMono; font.pixelSize: 9; color: Token.color_ui_textDim
        }
        Text {
            visible: root.errorText !== "" || root.savedText !== ""
            width: parent.width; wrapMode: Text.WordWrap
            text: root.errorText !== "" ? root.errorText : root.savedText
            font.family: Token.typography_familyMono; font.pixelSize: 10
            color: root.errorText !== "" ? Token.color_status_danger : Token.color_status_ok
        }
        Row {
            spacing: 8
            TextButton { objectName: "linkApplyBtn"; label: "APPLY & CONNECT"; tone: "primary"; width: 140
                         enabled: Link.available; onClicked: root.commit(true) }
            TextButton { label: "SAVE"; width: 80; onClicked: root.commit(false) }
            TextButton { label: "CLOSE"; width: 80; onClicked: root.close() }
        }
    }
}
