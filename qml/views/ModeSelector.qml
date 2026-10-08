import QtQuick
import QtQuick.Controls

// Flight-mode chip + grouped popover (MANUAL / ASSISTED / AUTO / ADVANCED).
// Modes come from the detected firmware (Vehicle.availableModes). "Takeoff"
// runs the backend's guarded mode -> arm -> takeoff sequence instead of the old
// QML timer chain, and the chip only claims a mode once the vehicle reports it.
Item {
    id: root
    objectName: "modeChip"
    readonly property var tm: Telemetry.telemetry
    readonly property bool linked: tm.connected
    property string pendingMode: ""
    readonly property bool open: popup.opened

    implicitWidth: chip.width
    implicitHeight: 38

    function pick(modeId) {
        popup.close()
        if (modeId === "TAKEOFF") {
            Vehicle.takeoff(Vehicle.takeoffAltitude)
            return
        }
        pendingMode = modeId
        pendingTimer.restart()
        Vehicle.setMode(modeId)
    }
    Timer { id: pendingTimer; interval: 4000; onTriggered: root.pendingMode = "" }
    Connections {
        target: Telemetry
        function onTelemetryChanged() {
            if (root.pendingMode !== "" && root.tm.mode === root.pendingMode) root.pendingMode = ""
        }
    }
    function colorFor(c) {
        return c === "lime" ? "#7CF04A" : c === "warn" ? "#FFB547" : c === "danger" ? "#FF7A7A"
             : c === "info" ? "#5AA9FF" : Token.color_ui_text
    }

    Rectangle {
        id: chip
        height: 38
        width: Math.max(104, modeRow.implicitWidth + 24)
        radius: 8
        color: popup.opened || hover.hovered ? Token.color_ui_accentSoft : Qt.rgba(1, 1, 1, 0.04)
        border.width: 1
        border.color: popup.opened ? Token.color_ui_accentLine : Token.color_ui_line
        Row {
            id: modeRow
            anchors.centerIn: parent
            spacing: 10
            Column {
                anchors.verticalCenter: parent.verticalCenter
                spacing: 2
                Text {
                    text: "MODE"
                    font.family: Token.typography_familyMono
                    font.pixelSize: 9
                    font.letterSpacing: 1.4
                    font.weight: Font.DemiBold
                    color: Token.color_ui_textDim
                }
                Text {
                    text: !root.linked ? "—" : root.pendingMode !== "" ? root.pendingMode + " …" : root.tm.mode
                    font.family: Token.typography_familyMono
                    font.pixelSize: 13
                    font.weight: Font.Bold
                    color: !root.linked ? Token.color_text_muted
                         : root.pendingMode !== "" ? Token.color_status_warn : Token.color_status_ok
                }
            }
            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: popup.opened ? "▴" : "▾"
                font.pixelSize: 10
                color: Token.color_ui_textDim
            }
        }
    }
    HoverHandler { id: hover; cursorShape: Qt.PointingHandCursor }
    TapHandler {
        enabled: root.linked
        gesturePolicy: TapHandler.ReleaseWithinBounds
        onTapped: popup.opened ? popup.close() : popup.open()
    }

    Popup {
        id: popup
        y: root.height + 8
        width: 224
        padding: 4
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        background: Rectangle {
            radius: 12
            color: Token.color_ui_glassStrong
            border.width: 1
            border.color: Token.color_ui_lineStrong
        }
        contentItem: Item {
            implicitHeight: Math.min(420, Math.max(60, modeList.contentHeight))
            Text {
                visible: Vehicle.availableModes.length === 0
                anchors.centerIn: parent
                text: "Reading firmware…"
                font.family: Token.typography_familyMono
                font.pixelSize: 10
                color: Token.color_text_muted
            }
            ListView {
                id: modeList
                anchors.fill: parent
                clip: true
                model: Vehicle.availableModes
                boundsBehavior: Flickable.StopAtBounds
                section.property: "group"
                section.criteria: ViewSection.FullString
                section.delegate: Item {
                    required property string section
                    width: modeList.width; height: 26
                    Text {
                        anchors.left: parent.left
                        anchors.leftMargin: 10
                        anchors.bottom: parent.bottom
                        anchors.bottomMargin: 3
                        text: section
                        font.family: Token.typography_familyMono
                        font.pixelSize: 9
                        font.letterSpacing: 1.6
                        font.weight: Font.DemiBold
                        color: Token.color_text_muted
                    }
                }
                delegate: Item {
                    id: row
                    required property var modelData
                    readonly property bool current: modelData.id === root.tm.mode
                    width: modeList.width
                    height: 30
                    Rectangle {
                        anchors.fill: parent
                        radius: 6
                        color: current ? Token.color_ui_accentSoft : (rowHover.hovered ? Qt.rgba(1, 1, 1, 0.07) : "transparent")
                    }
                    Text {
                        anchors.left: parent.left
                        anchors.leftMargin: 10
                        anchors.verticalCenter: parent.verticalCenter
                        text: row.modelData.label
                        font.family: Token.typography_familyUi
                        font.pixelSize: 12
                        color: root.colorFor(row.modelData.color)
                    }
                    Rectangle {
                        visible: row.current
                        anchors.right: parent.right
                        anchors.rightMargin: 12
                        anchors.verticalCenter: parent.verticalCenter
                        width: 6; height: 6; radius: 3
                        color: Token.color_accent_primary
                    }
                    HoverHandler { id: rowHover; cursorShape: Qt.PointingHandCursor }
                    TapHandler { gesturePolicy: TapHandler.ReleaseWithinBounds; onTapped: root.pick(row.modelData.id) }
                }
            }
        }
    }
}
