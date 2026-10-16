import QtQuick
import QtQuick.Controls
import "../components"

// Top-bar battery chip. Click to open BATTERY SETUP: choose where the % comes
// from (vehicle vs measured pack voltage), the pack (chemistry, cells, usable
// voltage window) and the warning / critical levels. Settings persist and are
// pushed to the backend so failsafe, pre-arm checks and the HUD agree.
Item {
    id: root
    objectName: "batteryChip"
    readonly property var tm: Telemetry.telemetry
    readonly property bool linked: tm.connected
    readonly property real pct: tm.battery_pct
    readonly property bool known: linked && pct >= 0
    readonly property real warnAt: tm.battery_warn
    readonly property real critAt: tm.battery_crit
    readonly property bool critical: known && pct < critAt
    readonly property bool low: known && pct < warnAt
    readonly property color tone: !known ? Token.color_text_muted
                                : critical ? Token.color_status_danger
                                : low ? Token.color_status_warn : Token.color_status_ok
    readonly property bool open: popup.opened

    implicitWidth: chip.width
    implicitHeight: 38

    Rectangle {
        id: chip
        height: 38
        width: chipRow.implicitWidth + 24
        radius: Token.dimension_radius_md
        color: popup.opened ? Token.color_ui_fillPressed : hover.hovered ? Token.color_ui_fill : "transparent"
        Behavior on color { ColorAnimation { duration: Token.motion_fast } }
        Row {
            id: chipRow
            anchors.centerIn: parent
            spacing: 10
            BatteryIcon {
                anchors.verticalCenter: parent.verticalCenter
                fraction: root.known ? Math.max(0, Math.min(1, root.pct / 100.0)) : -1
                critical: root.critical
            }
            Column {
                anchors.verticalCenter: parent.verticalCenter
                spacing: 2
                Text {
                    text: "Battery" + (root.known && root.tm.battery_v > 0 ? " · " + root.tm.battery_v.toFixed(1) + " V" : "")
                          + (root.tm.battery_source === "voltage" ? " · EST" : "")
                    font.pixelSize: 11
                    color: root.critical || root.low ? root.tone : Token.color_ui_textDim
                }
                Text {
                    text: root.known ? root.pct.toFixed(0) + "%" : "N/A"
                    font.features: { "tnum": 1 }
                    font.pixelSize: 13; font.weight: Font.DemiBold
                    color: root.known ? Token.color_ui_text : Token.color_text_muted
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

    // ---- editable copy of the profile (APPLY commits) ---------------------------------
    property string fSource: "vehicle"
    property string fChem: "lipo"
    property int fCells: 0
    property string errorText: ""
    function loadProfile() {
        var p = Battery.profile
        fSource = p.source; fChem = p.chemistry; fCells = p.cells
        fullField.text = Number(p.full_v).toFixed(2); emptyField.text = Number(p.empty_v).toFixed(2)
        warnField.text = String(Math.round(p.warn_pct)); critField.text = String(Math.round(p.crit_pct))
        capField.text = p.capacity_mah > 0 ? String(p.capacity_mah) : ""
        errorText = ""
        Battery.cancelVehicleSync()
    }
    function applyPreset(id) {
        for (var i = 0; i < Battery.presets.length; i++) {
            var pr = Battery.presets[i]
            if (pr.id === id) { fullField.text = pr.full_v.toFixed(2); emptyField.text = pr.empty_v.toFixed(2) }
        }
        fChem = id
    }
    function commit(closeAfter) {
        var res = Battery.apply({ source: fSource, chemistry: fChem, cells: fCells,
                                  full_v: fullField.text, empty_v: emptyField.text,
                                  warn_pct: warnField.text, crit_pct: critField.text,
                                  capacity_mah: capField.text === "" ? 0 : capField.text })
        if (!res.ok) { errorText = res.error; return false }
        errorText = ""
        if (closeAfter !== false) popup.close()
        return true
    }
    readonly property var sync: Battery.vehicleSync
    readonly property bool syncBusy: sync.state === "reading" || sync.state === "writing"

    component Field: Column {
        id: fld
        property string title: ""
        property alias text: input.text
        property alias field: input
        property string suffix: ""
        spacing: 4
        Text { text: fld.title; font.pixelSize: 11
               color: Token.color_ui_textDim }
        TextField {
            id: input
            width: 100; height: 30
            color: Token.color_ui_text
            selectByMouse: true
            font.pixelSize: 13
            leftPadding: 9
            inputMethodHints: Qt.ImhFormattedNumbersOnly
            background: Rectangle {
                radius: 7; color: Token.color_ui_fill
                border.width: input.activeFocus ? 2 : 0
                border.color: Qt.alpha(Token.color_accent_primary, 0.8)
            }
        }
    }
    component Seg: SegControl {}

    Popup {
        id: popup
        y: root.height + 8
        width: 316
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
        onAboutToShow: root.loadProfile()
        background: Rectangle { radius: Token.dimension_radius_xl; color: Token.color_ui_glassStrong
                                border.width: 1; border.color: Token.color_ui_line }
        // Scrolls inside the window on short screens (the FC preview adds rows).
        height: Math.min(contentCol.implicitHeight + 2 * padding, Math.max(240, root.Window.height - 64))
        contentItem: Flickable {
            id: flick
            clip: true
            contentWidth: width
            contentHeight: contentCol.implicitHeight
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar { policy: flick.contentHeight > flick.height ? ScrollBar.AlwaysOn : ScrollBar.AsNeeded }
          Column {
            id: contentCol
            width: flick.width - (flick.contentHeight > flick.height ? 10 : 0)
            spacing: 10
            Text { text: "Battery"; font.pixelSize: 17
                   font.weight: Font.DemiBold; color: Token.color_ui_text }

            Rectangle {                                                    // live readout
                width: parent.width; height: 54; radius: 10
                color: Token.color_ui_fill
                Row {
                    anchors.centerIn: parent
                    spacing: 18
                    Repeater {
                        model: [
                            { k: "Pack",    v: root.linked && root.tm.battery_v > 0 ? root.tm.battery_v.toFixed(2) + " V" : "–" },
                            { k: "Per Cell", v: root.linked && root.tm.battery_cell_v ? root.tm.battery_cell_v.toFixed(2) + " V" : "–" },
                            { k: "Shown",   v: root.known ? root.pct.toFixed(0) + "%" : "–" },
                            { k: "Vehicle", v: root.linked && root.tm.battery_pct_vehicle >= 0 ? root.tm.battery_pct_vehicle.toFixed(0) + "%" : "–" }
                        ]
                        delegate: Column {
                            required property var modelData
                            spacing: 2
                            Text { text: modelData.k; font.pixelSize: 10
                                   color: Token.color_ui_textDim }
                            Text { text: modelData.v; font.pixelSize: 13
                                   font.weight: Font.DemiBold; color: Token.color_ui_text }
                        }
                    }
                }
            }

            Text { text: "Percentage Source"; font.pixelSize: 11
                   color: Token.color_ui_textDim }
            Seg {
                width: parent.width
                options: [{ id: "vehicle", label: "Vehicle %" }, { id: "voltage", label: "From Voltage" }]
                current: root.fSource
                onPicked: function(id) { root.fSource = id }
            }

            Text { text: "Pack"; font.pixelSize: 11
                   color: Token.color_ui_textDim }
            Seg {
                width: parent.width
                options: [{ id: "lipo", label: "LiPo" }, { id: "lihv", label: "LiHV" },
                          { id: "liion", label: "Li-ion" }, { id: "custom", label: "Custom" }]
                current: root.fChem
                onPicked: function(id) { if (id === "custom") root.fChem = "custom"; else root.applyPreset(id) }
            }
            Row {
                spacing: 10
                Column {
                    spacing: 4
                    Text { text: "Cells (S)"; font.pixelSize: 11
                           color: Token.color_ui_textDim }
                    Row {
                        spacing: 4
                        TextButton { label: "−"; width: 30; height: 30; onClicked: root.fCells = Math.max(0, root.fCells - 1) }
                        Rectangle {
                            width: 44; height: 30; radius: 6; color: Token.color_ui_fill
                            border.width: 1; border.color: Token.color_ui_line
                            Text { anchors.centerIn: parent; text: root.fCells > 0 ? root.fCells + "S" : "–"
                                   font.pixelSize: 13; font.weight: Font.DemiBold
                                   color: Token.color_ui_text }
                        }
                        TextButton { label: "+"; width: 30; height: 30; onClicked: root.fCells = Math.min(14, root.fCells + 1) }
                    }
                }
                Column {
                    spacing: 4
                    Text { text: " "; font.pixelSize: 11 }
                    TextButton {
                        label: "Detect"; height: 30; width: 78
                        enabled: root.linked && root.tm.battery_v > 3
                        onClicked: {
                            var n = Battery.detectCells(root.tm.battery_v, parseFloat(fullField.text) || 4.2)
                            if (n > 0) root.fCells = n
                        }
                    }
                }
            }
            Row {
                spacing: 10
                Field { id: fullField;  title: "Full V / Cell";  onTextChanged: if (field.activeFocus) root.fChem = "custom" }
                Field { id: emptyField; title: "Empty V / Cell"; onTextChanged: if (field.activeFocus) root.fChem = "custom" }
            }
            Row {
                spacing: 10
                Field { id: warnField; title: "Warning %" }
                Field { id: critField; title: "Critical %" }
            }
            Row {
                spacing: 10
                Field { id: capField; objectName: "batteryCapacity"; title: "Capacity (mAh)"; field.placeholderText: "not set"
                        field.placeholderTextColor: Token.color_text_disabled }
            }
            Text {
                visible: root.errorText !== ""
                width: parent.width; wrapMode: Text.WordWrap
                text: root.errorText
                font.pixelSize: 11; color: Token.color_status_danger
            }
            Row {
                spacing: 8
                TextButton { label: "Apply"; tone: "primary"; width: 96; onClicked: root.commit(true) }
                TextButton { label: "Reset"; width: 80; onClicked: { Battery.resetDefaults(); root.loadProfile() } }
                TextButton { label: "Cancel"; width: 80; onClicked: popup.close() }
            }

            // ---- flight controller ----------------------------------------------------------
            Rectangle { width: parent.width; height: 1; color: Token.color_ui_line; visible: Battery.canSyncVehicle }
            Column {
                visible: Battery.canSyncVehicle
                width: parent.width
                spacing: 8
                Text { text: "Flight Controller" + (root.sync.autopilot ? " · " + root.sync.autopilot : "")
                       font.pixelSize: 11
                       color: Token.color_ui_textDim }
                TextButton {
                    objectName: "batterySyncBtn"
                    visible: root.sync.state === "idle" || root.sync.state === "done" || root.sync.state === "error"
                    label: "Write to vehicle…"
                    width: parent.width
                    enabled: root.linked && !root.tm.armed
                    onClicked: if (root.commit(false)) Battery.prepareVehicleSync()
                }
                Text {
                    visible: root.sync.message !== ""
                    width: parent.width; wrapMode: Text.WordWrap
                    text: root.sync.message
                    font.pixelSize: 11; font.weight: Font.DemiBold
                    color: root.sync.state === "error" ? Token.color_status_danger
                         : root.sync.state === "done" ? Token.color_status_ok : Token.color_ui_text
                }
                Repeater {
                    model: root.sync.rows || []
                    delegate: Rectangle {
                        required property var modelData
                        width: parent.width; height: 34; radius: 6
                        color: modelData.status !== "" && !modelData.ok ? Token.color_ui_dangerSoft
                             : modelData.change ? Token.color_ui_fill : "transparent"
                        border.width: 1; border.color: Token.color_ui_line
                        Column {
                            anchors.left: parent.left; anchors.leftMargin: 8
                            anchors.verticalCenter: parent.verticalCenter
                            spacing: 1
                            Text { text: modelData.name; font.pixelSize: 11
                                   font.weight: Font.DemiBold; color: modelData.change ? Token.color_ui_text : Token.color_ui_textDim }
                            Text { text: modelData.status !== "" && !modelData.ok ? modelData.status : modelData.note
                                   font.pixelSize: 10
                                   width: 150; elide: Text.ElideRight
                                   color: modelData.status !== "" && !modelData.ok ? Token.color_status_danger : Token.color_text_muted }
                        }
                        Text {
                            anchors.right: parent.right; anchors.rightMargin: 8
                            anchors.verticalCenter: parent.verticalCenter
                            text: !modelData.change ? modelData.current + "  ✓"
                                : modelData.ok ? modelData.target + "  ✓"
                                : modelData.current + " → " + modelData.target
                            font.pixelSize: 11; font.weight: Font.DemiBold
                            color: modelData.ok || !modelData.change ? Token.color_status_ok : Token.color_status_warn
                        }
                    }
                }
                Row {
                    visible: root.sync.state === "preview" || root.syncBusy
                    spacing: 8
                    TextButton {
                        objectName: "batterySyncConfirm"
                        label: root.sync.state === "writing" ? "Writing…" : root.sync.state === "reading" ? "Reading…" : "Confirm Write"
                        tone: "primary"; width: 150
                        enabled: root.sync.state === "preview" && !root.tm.armed
                                 && (root.sync.rows || []).some(function(r) { return r.change })
                        onClicked: Battery.confirmVehicleSync()
                    }
                    TextButton { label: "Cancel"; width: 80; enabled: !root.syncBusy; onClicked: Battery.cancelVehicleSync() }
                }
            }
          }
        }
    }
}
