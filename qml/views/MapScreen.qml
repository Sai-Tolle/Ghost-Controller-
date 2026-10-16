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
        width: 220
        height: fdCol.implicitHeight + 24
        radius: Token.dimension_radius_lg
        color: Token.color_ui_glass
        border.width: 1
        border.color: Token.color_ui_line
        z: 5
        SoftShadow {}
        Column {
            id: fdCol
            anchors.fill: parent
            anchors.margins: 14
            anchors.topMargin: 12
            spacing: 0
            Text {
                text: "Flight Data"
                font.pixelSize: Token.typography_size_lg; font.weight: Font.DemiBold
                color: Token.color_ui_text
                bottomPadding: 6
            }
            Repeater {
                model: [
                    { label: "Altitude",     value: root.tm.altitude.toFixed(1),   unit: " m" },
                    { label: "Speed",   value: root.tm.speed.toFixed(1),      unit: " m/s" },
                    { label: "Climb",   value: (root.tm.climb >= 0 ? "+" : "") + root.tm.climb.toFixed(1), unit: " m/s" },
                    { label: "Heading", value: root.tm.heading.toFixed(1),    unit: "°" },
                    { label: "Roll",    value: root.tm.roll.toFixed(1),       unit: "°" },
                    { label: "Pitch",   value: root.tm.pitch.toFixed(1),      unit: "°" },
                    { label: "Yaw",     value: root.tm.heading.toFixed(1),    unit: "°" },
                ]
                delegate: Item {
                    id: fdRow
                    required property var modelData
                    required property int index
                    width: fdCol.width; height: 28
                    Rectangle { visible: fdRow.index > 0; anchors.top: parent.top; width: parent.width; height: 1; color: Token.color_ui_line }
                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        text: fdRow.modelData.label
                        font.pixelSize: 13
                        color: Token.color_ui_textDim
                    }
                    Text {
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        text: root.tm.connected ? fdRow.modelData.value + fdRow.modelData.unit : "—"
                        font.features: { "tnum": 1 }
                        font.pixelSize: 13; font.weight: Font.DemiBold
                        color: Token.color_ui_text
                    }
                }
            }
        }
    }

    // ---- speed / heading pill (bottom left; top centre belongs to the alert banner) -------------
    Rectangle {
        anchors.bottom: parent.bottom; anchors.bottomMargin: 16
        anchors.left: parent.left; anchors.leftMargin: 12
        width: hudRow.implicitWidth + 28; height: 34; radius: 17
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
                text: (root.tm.connected ? root.tm.speed.toFixed(1) + " m/s" : "—")
                      + "   " + Math.round((root.tm.heading % 360 + 360) % 360) + "°"
                font.pixelSize: 13; font.weight: Font.Medium
                color: Token.color_ui_text
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
            width: offRow.implicitWidth + 28; height: 36; radius: 18
            color: offHover.hovered || uploadPanel.visible ? Token.color_ui_glassStrong : Token.color_ui_glass
            border.width: 1
            border.color: Token.color_ui_line
            Row {
                id: offRow
                anchors.centerIn: parent
                spacing: 6
                Icon { anchors.verticalCenter: parent.verticalCenter; name: "layers"; size: 16
                       color: MapBridge.overlayActive ? Token.color_accent_primary : Token.color_ui_text }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: MapBridge.overlayActive ? "Custom Map" : "Offline Map"
                    font.pixelSize: 13; font.weight: Font.Medium
                    color: MapBridge.overlayActive ? Token.color_accent_primary : Token.color_ui_textDim
                }
            }
            HoverHandler { id: offHover; cursorShape: Qt.PointingHandCursor }
            TapHandler { gesturePolicy: TapHandler.ReleaseWithinBounds; onTapped: uploadPanel.visible = !uploadPanel.visible }
        }
        Rectangle {
            objectName: "mapCollapse"
            width: 36; height: 36; radius: 18
            color: collapseHover.hovered ? Token.color_ui_glassStrong : Token.color_ui_glass
            border.width: 1
            border.color: Token.color_ui_line
            Icon { anchors.centerIn: parent; name: "collapse"; size: 17; color: Token.color_ui_text }
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
        width: 280
        height: upCol.implicitHeight + 32
        radius: Token.dimension_radius_lg
        color: Token.color_ui_glassStrong
        border.width: 1
        border.color: Token.color_ui_line
        z: 20
        SoftShadow {}

        Column {
            id: upCol
            anchors.fill: parent
            anchors.margins: 16
            spacing: 12
            PanelTitle { text: "Offline Map"; onClosed: uploadPanel.visible = false }
            TextButton {
                width: parent.width; height: 30
                label: root.pendingImage.toString() !== "" ? "Image selected ✓" : (MapBridge.overlayActive ? (MapBridge.overlay.label || "Image loaded ✓") : "Choose Image…")
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
                font.pixelSize: 11
                color: Token.color_status_danger
            }
            Row {
                spacing: 8
                TextButton {
                    label: "Save"; tone: "primary"; width: 120
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
                    label: "Clear"; tone: "danger"
                    onClicked: { MapBridge.setOverlayImage("", "", "", "", "", ""); root.pendingImage = ""; uploadPanel.visible = false }
                }
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
        text: (MapBridge.fallbackGrid ? "No Basemap" : MapBridge.statusText) + " · z" + map.zoom
        font.pixelSize: 11
        color: Token.color_text_muted
    }
}
