import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs
import "../components"

// Expanded map: full-bleed map with FLIGHT DATA (top-left), MAP HUD pill
// (top-centre), OFFLINE + collapse (top-right) and the heading compass
// (bottom-centre, drawn by MapView — there used to be a SECOND, broken compass
// here stacked on top of it).
Item {
    id: root
    signal closeRequested()

    readonly property var tm: Telemetry.telemetry
    readonly property real topInset: Token.dimension_hud_topBarHeight
    property string uploadError: ""
    property url pendingImage: ""

    MapView { id: map; anchors.fill: parent }

    // ---- custom image overlay (offline fallback) -----------------------------------
    Image {
        readonly property var cfg: MapBridge.overlay
        visible: MapBridge.overlayActive && cfg.url !== undefined
        source: visible ? cfg.url : ""
        fillMode: Image.Stretch
        x: visible ? map.toScreen(cfg.neLat, cfg.swLon).x : 0
        y: visible ? map.toScreen(cfg.neLat, cfg.swLon).y : 0
        width: visible ? Math.abs(map.toScreen(cfg.neLat, cfg.neLon).x - map.toScreen(cfg.neLat, cfg.swLon).x) : 0
        height: visible ? Math.abs(map.toScreen(cfg.swLat, cfg.swLon).y - map.toScreen(cfg.neLat, cfg.swLon).y) : 0
        z: 0.5
    }

    // ---- FLIGHT DATA (top left) ------------------------------------------------------------
    Rectangle {
        anchors.top: parent.top; anchors.topMargin: root.topInset + 12
        anchors.left: parent.left; anchors.leftMargin: 12
        width: 204
        height: fdCol.implicitHeight + 24
        radius: 12
        color: Token.color_ui_glass
        border.width: 1
        border.color: Token.color_ui_line
        z: 5
        Column {
            id: fdCol
            anchors.fill: parent
            anchors.margins: 12
            spacing: 0
            Text {
                text: "FLIGHT DATA"
                font.family: Token.typography_familyMono
                font.pixelSize: 10; font.weight: Font.Bold; font.letterSpacing: 2
                color: Token.color_accent_primary
                bottomPadding: 8
            }
            Rectangle { width: parent.width; height: 1; color: Token.color_ui_line }
            Repeater {
                model: [
                    { label: "ALT",     value: root.tm.altitude.toFixed(1),   unit: " m" },
                    { label: "SPEED",   value: root.tm.speed.toFixed(1),      unit: " m/s" },
                    { label: "CLIMB",   value: (root.tm.climb >= 0 ? "+" : "") + root.tm.climb.toFixed(1), unit: " m/s" },
                    { label: "HEADING", value: root.tm.heading.toFixed(1),    unit: "°" },
                    { label: "ROLL",    value: root.tm.roll.toFixed(1),       unit: "°" },
                    { label: "PITCH",   value: root.tm.pitch.toFixed(1),      unit: "°" },
                    { label: "YAW",     value: root.tm.heading.toFixed(1),    unit: "°" },
                ]
                delegate: Item {
                    id: fdRow
                    required property var modelData
                    width: fdCol.width; height: 24
                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        text: fdRow.modelData.label
                        font.family: Token.typography_familyMono
                        font.pixelSize: 9; font.letterSpacing: 1.2
                        color: Token.color_ui_textDim
                    }
                    Text {
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        text: root.tm.connected ? fdRow.modelData.value + fdRow.modelData.unit : "—"
                        font.family: Token.typography_familyMono
                        font.pixelSize: 12; font.weight: Font.Bold
                        color: "#FFFFFF"
                    }
                    Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Token.color_ui_line; opacity: 0.5 }
                }
            }
        }
    }

    // ---- MAP HUD pill (top centre) ---------------------------------------------------------
    Rectangle {
        anchors.top: parent.top; anchors.topMargin: root.topInset + 12
        anchors.horizontalCenter: parent.horizontalCenter
        width: hudRow.implicitWidth + 28; height: 32; radius: 16
        color: Token.color_ui_glass
        border.width: 1
        border.color: Token.color_ui_line
        z: 5
        Row {
            id: hudRow
            anchors.centerIn: parent
            spacing: 12
            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: "MAP HUD  ·  " + (root.tm.connected ? root.tm.speed.toFixed(1) + " m/s" : "—")
                      + "  ·  " + Math.round((root.tm.heading % 360 + 360) % 360) + "°"
                font.family: Token.typography_familyMono
                font.pixelSize: 11; font.letterSpacing: 1
                color: Token.color_ui_text
            }
            Text {
                visible: text !== ""
                anchors.verticalCenter: parent.verticalCenter
                text: root.tm.extra && root.tm.extra.velocity && root.tm.extra.velocity.source ? root.tm.extra.velocity.source : ""
                font.family: Token.typography_familyMono
                font.pixelSize: 9
                color: Token.color_text_muted
            }
        }
    }

    // ---- OFFLINE + collapse (top right) --------------------------------------------------------
    Row {
        anchors.top: parent.top; anchors.topMargin: root.topInset + 12
        anchors.right: parent.right; anchors.rightMargin: 12
        spacing: 8
        z: 5
        Rectangle {
            width: offRow.implicitWidth + 24; height: 36; radius: 9
            color: Token.color_ui_glass
            border.width: 1
            border.color: MapBridge.overlayActive ? Token.color_ui_accentLine : Token.color_ui_line
            Row {
                id: offRow
                anchors.centerIn: parent
                spacing: 6
                Text { anchors.verticalCenter: parent.verticalCenter; text: "⤒"; font.pixelSize: 12
                       color: MapBridge.overlayActive ? Token.color_accent_primary : Token.color_ui_textDim }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: MapBridge.overlayActive ? "MAP ✓" : "OFFLINE"
                    font.family: Token.typography_familyMono
                    font.pixelSize: 10; font.letterSpacing: 1.2
                    color: MapBridge.overlayActive ? Token.color_accent_primary : Token.color_ui_textDim
                }
            }
            HoverHandler { cursorShape: Qt.PointingHandCursor }
            TapHandler { gesturePolicy: TapHandler.ReleaseWithinBounds; onTapped: uploadPanel.visible = !uploadPanel.visible }
        }
        Rectangle {
            objectName: "mapCollapse"
            width: 36; height: 36; radius: 9
            color: collapseHover.hovered ? Token.color_ui_accentSoft : Token.color_ui_glass
            border.width: 1
            border.color: Token.color_ui_lineStrong
            Canvas {
                anchors.centerIn: parent; width: 16; height: 16
                onPaint: {
                    var c = getContext("2d"); c.reset()
                    c.strokeStyle = "#A9D2FF"; c.lineWidth = 1.8; c.lineCap = "round"
                    c.beginPath(); c.moveTo(2, 9); c.lineTo(7, 9); c.lineTo(7, 14)
                    c.moveTo(14, 7); c.lineTo(9, 7); c.lineTo(9, 2); c.stroke()
                }
            }
            HoverHandler { id: collapseHover; cursorShape: Qt.PointingHandCursor }
            TapHandler { gesturePolicy: TapHandler.ReleaseWithinBounds; onTapped: root.closeRequested() }
        }
    }

    // ---- offline map config -----------------------------------------------------------------------
    Rectangle {
        id: uploadPanel
        visible: false
        anchors.top: parent.top; anchors.topMargin: root.topInset + 56
        anchors.right: parent.right; anchors.rightMargin: 12
        width: 264
        height: upCol.implicitHeight + 28
        radius: 12
        color: Token.color_ui_glassStrong
        border.width: 1
        border.color: Token.color_ui_lineStrong
        z: 20

        Column {
            id: upCol
            anchors.fill: parent
            anchors.margins: 14
            spacing: 10
            Item {
                width: parent.width; height: 20
                Text { text: "OFFLINE MAP CONFIG"; font.family: Token.typography_familyMono
                       font.pixelSize: 10; font.weight: Font.Bold; font.letterSpacing: 1.6; color: Token.color_ui_text }
                Text { anchors.right: parent.right; text: "✕"; font.pixelSize: 13; color: Token.color_ui_textDim
                       TapHandler { onTapped: uploadPanel.visible = false } }
            }
            TextButton {
                width: parent.width; height: 30
                label: root.pendingImage.toString() !== "" ? "Image selected ✓" : (MapBridge.overlayActive ? (MapBridge.overlay.label || "Image loaded ✓") : "+ CHOOSE IMAGE")
                onClicked: fileDialog.open()
            }
            GridLayout {
                width: parent.width
                columns: 2; columnSpacing: 8; rowSpacing: 8
                LabeledNumber { id: swLat; title: "SW lat"; Layout.fillWidth: true; value: MapBridge.overlayActive ? MapBridge.overlay.swLat : "" }
                LabeledNumber { id: swLon; title: "SW lon"; Layout.fillWidth: true; value: MapBridge.overlayActive ? MapBridge.overlay.swLon : "" }
                LabeledNumber { id: neLat; title: "NE lat"; Layout.fillWidth: true; value: MapBridge.overlayActive ? MapBridge.overlay.neLat : "" }
                LabeledNumber { id: neLon; title: "NE lon"; Layout.fillWidth: true; value: MapBridge.overlayActive ? MapBridge.overlay.neLon : "" }
            }
            Text {
                visible: root.uploadError !== ""
                width: parent.width
                text: root.uploadError
                wrapMode: Text.WordWrap
                font.family: Token.typography_familyMono
                font.pixelSize: 9
                color: Token.color_status_danger
            }
            Row {
                spacing: 8
                TextButton {
                    label: "SAVE"; tone: "primary"; width: 120
                    onClicked: {
                        var img = root.pendingImage.toString() !== "" ? root.pendingImage.toString()
                                 : (MapBridge.overlayActive ? MapBridge.overlay.url : "")
                        if (img === "") { root.uploadError = "Choose a map image first."; return }
                        var ok = MapBridge.setOverlayImage(img, swLat.value, swLon.value, neLat.value, neLon.value,
                                                           MapBridge.overlayActive ? MapBridge.overlay.label : "Custom Map")
                        if (!ok) root.uploadError = "All 4 coordinates must be valid numbers and the image must exist."
                        else { root.uploadError = ""; root.pendingImage = ""; uploadPanel.visible = false }
                    }
                }
                TextButton {
                    visible: MapBridge.overlayActive
                    label: "CLEAR"; tone: "danger"
                    onClicked: { MapBridge.setOverlayImage("", "", "", "", "", ""); root.pendingImage = ""; uploadPanel.visible = false }
                }
            }
            Text {
                width: parent.width
                text: "Used when no basemap tiles can load.\nCopy corner coordinates from any online map."
                wrapMode: Text.WordWrap
                font.family: Token.typography_familyMono
                font.pixelSize: 9
                color: Token.color_text_muted
            }
        }
    }

    FileDialog {
        id: fileDialog
        title: "Choose a map image"
        nameFilters: ["Images (*.png *.jpg *.jpeg)"]
        onAccepted: root.pendingImage = selectedFile
    }

    // ---- tile status -----------------------------------------------------------------------------------
    Text {
        anchors.bottom: parent.bottom; anchors.bottomMargin: 4
        anchors.right: parent.right; anchors.rightMargin: 12
        z: 5
        text: (MapBridge.fallbackGrid ? "NO BASEMAP" : MapBridge.statusText) + " · z" + map.zoom
        font.family: Token.typography_familyMono
        font.pixelSize: 9
        color: Token.color_text_muted
    }
}
