import QtQuick
import QtQuick.Controls
import "../components"

// Top-bar GPS chip. Click opens the full GPS STATUS popover: fix, satellites,
// HDOP/VDOP, course over ground, ground speed, position and a threshold key.
Item {
    id: root
    objectName: "gpsChip"
    readonly property var tm: Telemetry.telemetry
    readonly property bool linked: tm.connected
    readonly property int fixType: tm.gps_fix
    readonly property int sats: tm.sats
    readonly property var fixLabels: [
        { label: "No GPS", tone: "dim" }, { label: "No Fix", tone: "bad" },
        { label: "2D Fix", tone: "warn" }, { label: "3D Fix", tone: "ok" },
        { label: "DGPS", tone: "ok" }, { label: "RTK Float", tone: "info" },
        { label: "RTK Fixed", tone: "info" }, { label: "Static", tone: "ok" }, { label: "PPP", tone: "ok" }
    ]
    readonly property var fix: fixLabels[Math.max(0, Math.min(fixType, fixLabels.length - 1))]
    readonly property string tone: !linked ? "dim"
                                 : (fix.tone === "ok" || fix.tone === "info") && sats >= 6 ? fix.tone
                                 : fix.tone === "bad" || fix.tone === "dim" ? "bad"
                                 : "warn"
    function toneColor(t) {
        return t === "ok" ? Token.color_status_ok : t === "info" ? Token.color_status_info
             : t === "warn" ? Token.color_status_warn : t === "bad" ? Token.color_status_danger
             : Token.color_text_muted
    }
    function toneSoft(t) {
        return t === "ok" ? Token.color_ui_okSoft : t === "warn" ? Token.color_ui_warnSoft
             : t === "bad" ? Token.color_ui_dangerSoft : t === "info" ? Token.color_ui_accentSoft
             : Token.color_ui_fill
    }
    readonly property color accent: toneColor(tone)
    readonly property bool open: popup.opened

    implicitWidth: chip.width
    implicitHeight: 38

    Rectangle {
        id: chip
        height: 38
        width: row.implicitWidth + 24
        radius: Token.dimension_radius_md
        color: popup.opened ? Token.color_ui_fillPressed : hover.hovered ? Token.color_ui_fill : "transparent"
        Behavior on color { ColorAnimation { duration: Token.motion_fast } }
        Row {
            id: row
            anchors.centerIn: parent
            spacing: 10
            SignalBars {
                anchors.verticalCenter: parent.verticalCenter
                tone: root.accent
                level: root.linked && root.fixType >= 3 ? Math.min(5, Math.floor(root.sats / 4)) : 0
            }
            Column {
                anchors.verticalCenter: parent.verticalCenter
                spacing: 2
                Text {
                    text: "GPS · " + (root.linked ? root.fix.label : "—")
                    font.pixelSize: 11
                    color: root.tone === "bad" || root.tone === "warn" ? root.accent : Token.color_ui_textDim
                }
                Row {
                    spacing: 6
                    Text {
                        text: root.linked ? root.sats + " sats" : "–"
                        font.features: { "tnum": 1 }
                        font.pixelSize: 13
                        font.weight: Font.DemiBold
                        color: root.linked ? Token.color_ui_text : Token.color_text_muted
                    }
                    Text {
                        visible: root.linked && root.tm.hdop !== null && root.tm.hdop !== undefined
                        anchors.verticalCenter: parent.verticalCenter
                        text: "HDOP " + Number(root.tm.hdop).toFixed(1)
                        font.pixelSize: 11
                        color: Token.color_ui_textDim
                    }
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
    TapHandler { gesturePolicy: TapHandler.ReleaseWithinBounds; onTapped: popup.opened ? popup.close() : popup.open() }

    // ---- status popover -------------------------------------------------------
    component Line: Item {
        property string label: ""
        property string value: "–"
        property color valueColor: Token.color_ui_text
        property string note: ""
        width: parent ? parent.width : 240
        height: 24
        Text {
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            text: parent.label
            font.pixelSize: 13
            color: Token.color_ui_textDim
        }
        Row {
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            spacing: 6
            Text {
                visible: parent.parent.note !== ""
                anchors.verticalCenter: parent.verticalCenter
                text: parent.parent.note
                font.pixelSize: 11
                color: Token.color_text_muted
            }
            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: parent.parent.value
                font.features: { "tnum": 1 }
                font.pixelSize: 13
                font.weight: Font.DemiBold
                color: parent.parent.valueColor
            }
        }
    }
    component Rule: Rectangle { width: parent ? parent.width : 240; height: 1; color: Token.color_ui_line }

    function dopColor(v, good, fair) {
        return v === null || v === undefined ? Token.color_text_muted
             : v <= good ? Token.color_status_ok : v <= fair ? Token.color_status_warn : Token.color_status_danger
    }
    function num(v, d, unit) { return v === null || v === undefined ? "–" : Number(v).toFixed(d) + (unit || "") }

    Popup {
        id: popup
        y: root.height + 8
        width: 276
        padding: 14
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
        contentItem: Column {
            spacing: 4
            Item {
                width: parent.width; height: 28
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: "GPS"
                    font.pixelSize: 15
                    font.weight: Font.DemiBold
                    color: Token.color_ui_text
                }
                Rectangle {
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    width: badge.implicitWidth + 16; height: 20; radius: 10
                    color: Qt.alpha(root.accent, 0.18)
                    Text {
                        id: badge
                        anchors.centerIn: parent
                        text: root.linked ? root.fix.label : "No Link"
                        font.pixelSize: 11; font.weight: Font.DemiBold
                        color: root.accent
                    }
                }
            }
            Rule {}
            Line { label: "Fix Type"; value: root.linked ? root.fix.label : "–"; valueColor: root.accent }
            Line { label: "Satellites"; value: root.linked ? String(root.sats) : "–"
                   valueColor: !root.linked ? Token.color_text_muted
                             : root.sats >= 6 ? Token.color_status_ok : root.sats >= 4 ? Token.color_status_warn : Token.color_status_danger }
            Rule {}
            Line { label: "HDOP"; value: root.num(root.tm.hdop, 2); valueColor: root.dopColor(root.tm.hdop, 1.0, 2.0) }
            Line { label: "VDOP"; value: root.num(root.tm.vdop, 2); valueColor: root.dopColor(root.tm.vdop, 1.5, 3.0) }
            Rule {}
            Line { label: "COG"; value: root.num(root.tm.cog, 1, "°") }
            Line { label: "Speed"; value: root.num(root.tm.gps_vel, 1, " m/s") }
            Rule {}
            Line { label: "Latitude"; value: root.linked ? root.num(root.tm.lat, 7) : "–" }
            Line { label: "Longitude"; value: root.linked ? root.num(root.tm.lon, 7) : "–" }
            Line { label: "Altitude"; value: root.linked ? root.num(root.tm.altitude, 1, " m") : "–" }
        }
    }
}
