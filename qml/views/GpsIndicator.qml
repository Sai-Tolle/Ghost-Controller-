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
        { label: "NO GPS", tone: "dim" }, { label: "NO FIX", tone: "bad" },
        { label: "2D FIX", tone: "warn" }, { label: "3D FIX", tone: "ok" },
        { label: "DGPS", tone: "ok" }, { label: "RTK FLOAT", tone: "info" },
        { label: "RTK FIXED", tone: "info" }, { label: "STATIC", tone: "ok" }, { label: "PPP", tone: "ok" }
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
             : Qt.rgba(1, 1, 1, 0.04)
    }
    readonly property color accent: toneColor(tone)
    readonly property bool open: popup.opened

    implicitWidth: chip.width
    implicitHeight: 38

    Rectangle {
        id: chip
        height: 38
        width: row.implicitWidth + 24
        radius: 8
        color: hover.hovered || popup.opened ? Qt.lighter(root.toneSoft(root.tone), 1.4) : root.toneSoft(root.tone)
        border.width: 1
        border.color: Qt.alpha(root.accent, 0.4)
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
                    font.family: Token.typography_familyMono
                    font.pixelSize: 9
                    font.weight: Font.DemiBold
                    font.letterSpacing: 1.4
                    color: root.accent
                }
                Row {
                    spacing: 6
                    Text {
                        text: root.linked ? root.sats + " sats" : "–"
                        font.family: Token.typography_familyMono
                        font.pixelSize: 13
                        font.weight: Font.Bold
                        color: root.linked ? "#FFFFFF" : Token.color_text_muted
                    }
                    Text {
                        visible: root.linked && root.tm.hdop !== null && root.tm.hdop !== undefined
                        anchors.verticalCenter: parent.verticalCenter
                        text: "HDOP " + Number(root.tm.hdop).toFixed(1)
                        font.family: Token.typography_familyMono
                        font.pixelSize: 10
                        color: Token.color_ui_textDim
                    }
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
            font.family: Token.typography_familyMono
            font.pixelSize: 10
            font.letterSpacing: 1.2
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
                font.family: Token.typography_familyMono
                font.pixelSize: 9
                color: Token.color_text_muted
            }
            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: parent.parent.value
                font.family: Token.typography_familyMono
                font.pixelSize: 12
                font.weight: Font.Bold
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
        background: Rectangle {
            radius: 12
            color: Token.color_ui_glassStrong
            border.width: 1
            border.color: Token.color_ui_lineStrong
        }
        contentItem: Column {
            spacing: 4
            Item {
                width: parent.width; height: 28
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: "GPS STATUS"
                    font.family: Token.typography_familyMono
                    font.pixelSize: 11
                    font.weight: Font.Bold
                    font.letterSpacing: 2
                    color: Token.color_ui_text
                }
                Rectangle {
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    width: badge.implicitWidth + 14; height: 18; radius: 4
                    color: "transparent"
                    border.width: 1
                    border.color: Qt.alpha(root.accent, 0.6)
                    Text {
                        id: badge
                        anchors.centerIn: parent
                        text: root.linked ? root.fix.label : "NO LINK"
                        font.family: Token.typography_familyMono
                        font.pixelSize: 9
                        font.letterSpacing: 1
                        color: root.accent
                    }
                }
            }
            Rule {}
            Line { label: "FIX TYPE"; value: root.linked ? root.fix.label : "–"; valueColor: root.accent }
            Line { label: "SATELLITES"; value: root.linked ? String(root.sats) : "–"
                   valueColor: !root.linked ? Token.color_text_muted
                             : root.sats >= 6 ? Token.color_status_ok : root.sats >= 4 ? Token.color_status_warn : Token.color_status_danger }
            Rule {}
            Line { label: "HDOP"; note: "horiz accuracy"; value: root.num(root.tm.hdop, 2); valueColor: root.dopColor(root.tm.hdop, 1.0, 2.0) }
            Line { label: "VDOP"; note: "vert accuracy"; value: root.num(root.tm.vdop, 2); valueColor: root.dopColor(root.tm.vdop, 1.5, 3.0) }
            Rule {}
            Line { label: "COG"; note: "course over ground"; value: root.num(root.tm.cog, 1, "°"); valueColor: Token.color_accent_primary }
            Line { label: "SPEED"; value: root.num(root.tm.gps_vel, 1, " m/s"); valueColor: Token.color_accent_primary }
            Rule {}
            Line { label: "LAT"; value: root.linked ? root.num(root.tm.lat, 7) : "–" }
            Line { label: "LON"; value: root.linked ? root.num(root.tm.lon, 7) : "–" }
            Line { label: "ALT"; value: root.linked ? root.num(root.tm.altitude, 1, " m") : "–" }
            Item { width: 1; height: 4 }
            Text {
                width: parent.width
                text: "HDOP ≤ 1.0 good · ≤ 2.0 fair · above is poor\nVDOP ≤ 1.5 good · ≤ 3.0 fair\nSats 6+ good · 4–5 fair"
                wrapMode: Text.WordWrap
                font.family: Token.typography_familyMono
                font.pixelSize: 9
                lineHeight: 1.4
                color: Token.color_text_muted
            }
        }
    }
}
