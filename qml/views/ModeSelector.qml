import QtQuick
import QtQuick.Controls
import "../components"

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
    // Human label for a mode id ("POSCTL" -> "Position"); unknown ids are title-cased.
    function labelFor(id) {
        var ms = Vehicle.availableModes
        for (var i = 0; i < ms.length; i++) if (ms[i].id === id) return ms[i].label
        if (!id) return "—"
        return String(id).toLowerCase().split("_").map(function (w) { return w.charAt(0).toUpperCase() + w.slice(1) }).join(" ")
    }
    function colorFor(c) {
        return c === "lime" ? Token.color_status_ok : c === "warn" ? Token.color_status_warn
             : c === "danger" ? Token.color_status_danger : c === "info" ? Token.color_status_info : Token.color_ui_textDim
    }

    Rectangle {
        id: chip
        height: 38
        width: Math.max(104, modeRow.implicitWidth + 24)
        radius: Token.dimension_radius_md
        color: popup.opened ? Token.color_ui_fillPressed : hover.hovered ? Token.color_ui_fill : "transparent"
        Behavior on color { ColorAnimation { duration: Token.motion_fast } }
        Row {
            id: modeRow
            anchors.centerIn: parent
            spacing: 10
            Column {
                anchors.verticalCenter: parent.verticalCenter
                spacing: 2
                Text {
                    text: "Mode"
                    font.pixelSize: 11
                    color: Token.color_ui_textDim
                }
                Text {
                    text: !root.linked ? "—" : root.pendingMode !== "" ? root.labelFor(root.pendingMode) + "…" : root.labelFor(root.tm.mode)
                    font.pixelSize: 13
                    font.weight: Font.DemiBold
                    color: !root.linked ? Token.color_text_muted
                         : root.pendingMode !== "" ? Token.color_status_warn : Token.color_ui_text
                }
            }
            Icon {
                anchors.verticalCenter: parent.verticalCenter
                name: "chevron.down"; size: 11; weight: 1.6
                color: Token.color_ui_textDim
                rotation: popup.opened ? 180 : 0
                Behavior on rotation { NumberAnimation { duration: Token.motion_fast; easing.type: Easing.OutCubic } }
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
        transformOrigin: Popup.Top
        enter: Transition {
            NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Token.motion_fast; easing.type: Easing.OutCubic }
            NumberAnimation { property: "scale"; from: 0.96; to: 1; duration: Token.motion_normal; easing.type: Easing.OutBack; easing.overshoot: 1.1 }
        }
        exit: Transition {
            NumberAnimation { property: "opacity"; from: 1; to: 0; duration: Token.motion_fast; easing.type: Easing.InCubic }
            NumberAnimation { property: "scale"; from: 1; to: 0.98; duration: Token.motion_fast }
        }
        background: Rectangle {
            radius: Token.dimension_radius_lg
            color: Token.color_ui_glassStrong
            border.width: 1
            border.color: Token.color_ui_line
        }
        contentItem: Item {
            implicitHeight: Math.min(420, Math.max(60, modeList.contentHeight))
            Text {
                visible: Vehicle.availableModes.length === 0
                anchors.centerIn: parent
                text: "Reading firmware…"
                font.pixelSize: 11
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
                        text: section.charAt(0) + section.slice(1).toLowerCase()
                        font.pixelSize: 11
                        font.weight: Font.DemiBold
                        color: Token.color_text_muted
                    }
                }
                delegate: Item {
                    id: row
                    required property var modelData
                    readonly property bool current: modelData.id === root.tm.mode
                    width: modeList.width
                    height: 28
                    Rectangle {
                        anchors.fill: parent
                        radius: 5
                        color: rowHover.hovered ? Token.color_accent_primary : "transparent"
                    }
                    Icon {                                // macOS menu checkmark column
                        visible: row.current
                        anchors.left: parent.left
                        anchors.leftMargin: 8
                        anchors.verticalCenter: parent.verticalCenter
                        name: "checkmark"; size: 13; weight: 2
                        color: rowHover.hovered ? Token.color_ui_onTint : Token.color_ui_text
                    }
                    Text {
                        anchors.left: parent.left
                        anchors.leftMargin: 26
                        anchors.verticalCenter: parent.verticalCenter
                        text: row.modelData.label
                        font.pixelSize: 13
                        color: rowHover.hovered ? Token.color_ui_onTint : Token.color_ui_text
                    }
                    Rectangle {                           // risk tint: a small dot, not coloured text
                        anchors.right: parent.right
                        anchors.rightMargin: 12
                        anchors.verticalCenter: parent.verticalCenter
                        width: 7; height: 7; radius: 3.5
                        color: root.colorFor(row.modelData.color)
                        opacity: 0.9
                    }
                    HoverHandler { id: rowHover; cursorShape: Qt.PointingHandCursor }
                    TapHandler { gesturePolicy: TapHandler.ReleaseWithinBounds; onTapped: root.pick(row.modelData.id) }
                }
            }
        }
    }
}
