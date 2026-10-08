import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs
import "../components"

// Mission planner: full-screen map with its OWN top bar (MISSION / FENCE menus,
// Close), left Map Tools, one shared top-right context panel, status toast and
// fence count. Main.qml hides the app TopBar while this view is open — the app
// bar used to sit above this one (z:20) and swallow every click on Upload and
// Close.
Item {
    id: root
    signal closeRequested()

    readonly property var tm: Telemetry.telemetry
    readonly property real barH: 48

    // ---- tool state (one active tool; clicking it again turns it off) ----------------
    property string tool: ""        // "" | orbit | survey | waypoint | fence | deleteWp | deleteFence
    property bool surveyCenterSet: false
    property point surveyCenter: Qt.point(0, 0)      // x = lat, y = lon
    property int selectedFenceIndex: -1
    property string statusText: ""
    property bool statusOk: true
    readonly property bool anyToolActive: tool !== ""

    readonly property string contextKind:
        (tool === "survey" && surveyCenterSet) ? "survey"
        : tool === "orbit" ? "orbit"
        : (Mission.selectedIndex >= 0 && Mission.selectedIndex < Mission.waypoints.length) ? "waypoint"
        : (selectedFenceIndex >= 0 && selectedFenceIndex < Mission.fencePoints.length && tool !== "deleteFence") ? "fence"
        : ""

    function setTool(t) {
        tool = (tool === t) ? "" : t
        if (tool !== "survey") surveyCenterSet = false
        surveyCanvas.requestPaint()
    }
    function setStatus(msg, ok) {
        statusText = msg
        statusOk = (ok === undefined) ? true : ok
        statusTimer.restart()
    }
    Timer { id: statusTimer; interval: 5000; onTriggered: root.statusText = "" }

    Connections {
        target: Mission
        function onSelectionChanged() { if (Mission.selectedIndex >= 0) root.selectedFenceIndex = -1 }
        // The planner never showed vehicle results, so an upload that failed (or
        // succeeded) was invisible. Surface every planner command result.
        function onLastResultChanged() {
            var lr = Mission.lastResult
            if (!lr || !lr.command || !lr.result) return
            var r = lr.result
            var ok = r.success === true || (r.success === undefined && !r.error)
            var txt
            if (r.error === "MISSION_INVALID" && r.details && r.details.issues && r.details.issues.length)
                txt = "⚠ Mission rejected: " + r.details.issues[0].reason
            else if (r.error) txt = "⚠ " + lr.command.replace("_", " ") + ": " + r.error
            else if (lr.command === "MISSION_UPLOAD") txt = "✓ Mission uploaded"
            else if (lr.command === "MISSION_DOWNLOAD") txt = "✓ Mission downloaded (" + Mission.waypoints.length + " items)"
            else if (lr.command === "FENCE_UPLOAD") txt = "✓ Geofence uploaded"
            else if (lr.command === "FENCE_DOWNLOAD") txt = "✓ Geofence downloaded"
            else if (lr.command === "VALIDATE") txt = "⚠ " + (r.error || "Validation failed")
            else txt = "✓ " + lr.command.replace("_", " ") + (r.count !== undefined ? " (" + r.count + ")" : "")
            root.setStatus(txt, ok)
        }
    }

    // ---- map ------------------------------------------------------------------------------
    Rectangle { anchors.fill: parent; color: Token.color_hud_videoBg }
    MapView {
        id: map
        anchors.fill: parent
        plannerMode: true
        addWaypointArmed: root.tool === "waypoint"
        addFenceArmed: root.tool === "fence"
        deleteArmed: root.tool === "deleteWp" || root.tool === "deleteFence"
        zoom: 15
        onMapClicked: function(lat, lon) {
            if (root.tool === "orbit") {
                if (Mission.orbitAt(lat, lon)) root.setStatus("Orbit command sent", true)
                else root.setStatus("⚠ Orbit needs a vehicle link", false)
                root.setTool("")
            } else if (root.tool === "survey") {
                root.surveyCenter = Qt.point(lat, lon)
                root.surveyCenterSet = true
                surveyCanvas.requestPaint()
            } else if (root.tool === "") {
                Mission.selectWaypoint(-1)           // click empty map = deselect
                root.selectedFenceIndex = -1
            }
        }
        onFencePointClicked: function(index) {
            Mission.selectWaypoint(-1)
            root.selectedFenceIndex = index
        }
    }

    // survey footprint preview (the old handler used an undefined `ctx` and
    // passed the angle in the altitude slot, so it never drew or rotated)
    Canvas {
        id: surveyCanvas
        anchors.fill: parent
        visible: root.tool === "survey" && root.surveyCenterSet
        z: 3
        onPaint: {
            var ctx = getContext("2d"); ctx.reset()
            if (!visible) return
            var w = parseFloat(surveyWidth.value), h = parseFloat(surveyHeight.value)
            var ang = parseFloat(surveyAngle.value)
            if (!(w > 0 && h > 0)) return
            var corners = Mission.previewSurvey(root.surveyCenter.x, root.surveyCenter.y, w, h,
                                                parseFloat(surveySpacing.value) || 1, isNaN(ang) ? 0 : ang, 0)
            ctx.strokeStyle = "#5AA9FF"; ctx.lineWidth = 2; ctx.setLineDash([6, 5])
            ctx.fillStyle = "rgba(90,169,255,0.10)"
            ctx.beginPath()
            for (var i = 0; i < corners.length; i++) {
                var p = map.toScreen(corners[i][0], corners[i][1])
                if (i === 0) ctx.moveTo(p.x, p.y); else ctx.lineTo(p.x, p.y)
            }
            ctx.closePath(); ctx.fill(); ctx.stroke()
        }
        onVisibleChanged: if (visible) requestPaint()
        Connections {
            target: map
            function onCenterLatChanged() { surveyCanvas.requestPaint() }
            function onCenterLonChanged() { surveyCanvas.requestPaint() }
            function onZoomChanged() { surveyCanvas.requestPaint() }
        }
    }

    // ---- TOP BAR ---------------------------------------------------------------------------------
    Rectangle {
        id: topBar
        anchors { top: parent.top; left: parent.left; right: parent.right }
        height: root.barH
        color: Token.color_hud_topbarBg
        z: 30
        Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Token.color_ui_line }

        Row {
            anchors.left: parent.left; anchors.leftMargin: 16
            anchors.verticalCenter: parent.verticalCenter
            spacing: 12
            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: "MISSION PLANNER"
                font.family: Token.typography_familyMono
                font.pixelSize: 11; font.weight: Font.Bold; font.letterSpacing: 2.2
                color: Token.color_accent_primary
            }
            Rectangle { width: 1; height: 20; anchors.verticalCenter: parent.verticalCenter; color: Token.color_ui_line }

            PlannerDropdown {
                objectName: "dropMission"
                label: "MISSION"
                anchors.verticalCenter: parent.verticalCenter
                items: [
                    { text: "↑  Import waypoints", action: "importMission" },
                    { text: "↓  Export waypoints", action: "exportMission" },
                    { sep: true },
                    { text: "⬆  Upload to vehicle", action: "upload" },
                    { text: "⬇  Download from vehicle", action: "download" },
                    { sep: true },
                    { text: "✕  Clear mission", action: "clearMission", danger: true }
                ]
                onAction: function(name) {
                    if (name === "importMission") missionImportDialog.open()
                    else if (name === "exportMission") root.exportMission()
                    else if (name === "upload") root.uploadMission()
                    else if (name === "download") { Mission.download(); root.setStatus("Requesting mission…") }
                    else if (name === "clearMission") confirm.ask("Clear the planned mission?", function() {
                        Mission.clearMission(); root.setStatus("Mission cleared") })
                }
            }
            PlannerDropdown {
                label: "FENCE"
                cyan: true
                anchors.verticalCenter: parent.verticalCenter
                items: [
                    { text: "↑  Import fence", action: "importFence" },
                    { text: "↓  Export fence", action: "exportFence" },
                    { sep: true },
                    { text: "⬆  Upload to vehicle", action: "uploadFence" },
                    { text: "⬇  Download from vehicle", action: "downloadFence" },
                    { sep: true },
                    { text: "✕  Clear fence", action: "clearFence", danger: true }
                ]
                onAction: function(name) {
                    if (name === "importFence") fenceImportDialog.open()
                    else if (name === "exportFence") root.exportFence()
                    else if (name === "uploadFence") root.uploadFence()
                    else if (name === "downloadFence") { Mission.downloadFence(); root.setStatus("Requesting fence from vehicle…") }
                    else if (name === "clearFence") confirm.ask("Clear the geofence here AND on the vehicle?", function() {
                        Mission.clearFence(); Mission.clearFenceOnVehicle(); root.setStatus("Clearing fence on vehicle…") })
                }
            }
        }

        TextButton {
            objectName: "plannerClose"
            anchors.right: parent.right; anchors.rightMargin: 14
            anchors.verticalCenter: parent.verticalCenter
            label: "CLOSE"
            tone: "danger"
            height: 30; width: 76
            onClicked: root.closeRequested()           // signal, not Window.window.viewMode
        }
    }

    // ---- LEFT TOOLBAR ------------------------------------------------------------------------------
    Rectangle {
        anchors.top: topBar.bottom; anchors.topMargin: 14
        anchors.left: parent.left; anchors.leftMargin: 14
        width: 156
        height: toolsCol.implicitHeight + 24
        radius: 12
        color: Token.color_ui_glass
        border.width: 1; border.color: Token.color_ui_line
        z: 20
        Column {
            id: toolsCol
            anchors.fill: parent; anchors.margins: 12
            spacing: 6
            Text {
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                text: "MAP TOOLS"
                font.family: Token.typography_familyMono
                font.pixelSize: 9; font.letterSpacing: 2; font.weight: Font.DemiBold
                color: Token.color_ui_textDim
                bottomPadding: 4
            }
            PlannerToolButton { width: parent.width; label: root.tool === "orbit" ? "LIVE ORBIT: ON" : "LIVE ORBIT"
                                active: root.tool === "orbit"; activeColor: "#B38CFF"; onClicked: root.setTool("orbit") }
            PlannerToolButton { width: parent.width; label: root.tool === "survey" ? "SURVEY: ON" : "ADD SURVEY"
                                active: root.tool === "survey"; activeColor: "#5AA9FF"; onClicked: root.setTool("survey") }
            PlannerToolButton { objectName: "toolWaypoint"; width: parent.width; label: root.tool === "waypoint" ? "ADD WP: ON" : "ADD WP"
                                active: root.tool === "waypoint"; activeColor: "#5AA9FF"; onClicked: root.setTool("waypoint") }
            PlannerToolButton { width: parent.width; label: root.tool === "fence" ? "DRAW FENCE: ON" : "DRAW FENCE"
                                active: root.tool === "fence"; activeColor: "#5ADBFF"; onClicked: root.setTool("fence") }
            PlannerToolButton { width: parent.width; label: root.tool === "deleteWp" ? "DEL WP: ON" : "DEL WP"
                                active: root.tool === "deleteWp"; activeColor: "#FF7A7A"; onClicked: root.setTool("deleteWp") }
            PlannerToolButton { width: parent.width; label: "DEL FENCE PT"
                                active: root.tool === "deleteFence"; activeColor: "#FFB547"; onClicked: root.setTool("deleteFence") }
        }
    }

    // ---- active tool hint -----------------------------------------------------------------------------
    Rectangle {
        visible: root.anyToolActive
        anchors.top: topBar.bottom; anchors.topMargin: 14
        anchors.horizontalCenter: parent.horizontalCenter
        width: hintText.implicitWidth + 32; height: 28; radius: 14
        color: Token.color_ui_glassStrong
        border.width: 1; border.color: Token.color_ui_accentLine
        z: 20
        Text {
            id: hintText
            anchors.centerIn: parent
            text: root.tool === "orbit" ? "Click the map to orbit that point"
                : root.tool === "fence" ? "Click the map to add fence vertices"
                : root.tool === "deleteFence" ? "Click a fence vertex to remove it"
                : root.tool === "waypoint" ? "Click the map to add waypoints"
                : root.tool === "deleteWp" ? "Click a waypoint to delete it"
                : root.tool === "survey" ? "Click the map to set the survey centre" : ""
            font.family: Token.typography_familyMono
            font.pixelSize: 10; font.letterSpacing: 1
            color: Token.color_accent_primary
        }
    }

    // ---- CONTEXT PANEL (one slot, top-right) ------------------------------------------------------------
    // survey
    CtxPanel {
        shown: root.contextKind === "survey"; below: topBar; edge: Token.color_ui_accentLine
        height: surveyCol.implicitHeight + 28
        Column {
            id: surveyCol
            anchors.fill: parent; anchors.margins: 14; spacing: 8
            PanelTitle { text: "SURVEY GRID"; onClosed: root.setTool("survey") }
            LabeledNumber { id: surveyWidth;   title: "Grid width (m)";   value: "100"; onValueChanged: surveyCanvas.requestPaint() }
            LabeledNumber { id: surveyHeight;  title: "Grid height (m)";  value: "100"; onValueChanged: surveyCanvas.requestPaint() }
            LabeledNumber { id: surveySpacing; title: "Line spacing (m)"; value: "20";  onValueChanged: surveyCanvas.requestPaint() }
            LabeledNumber { id: surveyAngle;   title: "Angle (deg)";      value: "0";   onValueChanged: surveyCanvas.requestPaint() }
            LabeledNumber { id: surveyAlt;     title: "Altitude (m)";     value: "20" }
            TextButton {
                width: parent.width; height: 32
                label: "GENERATE GRID"; tone: "primary"
                onClicked: {
                    var sp = parseFloat(surveySpacing.value)
                    if (!(sp > 0) || !(parseFloat(surveyWidth.value) > 0) || !(parseFloat(surveyHeight.value) > 0)) {
                        root.setStatus("⚠ Width, height and spacing must be above 0", false); return
                    }
                    var n = Mission.generateSurvey(root.surveyCenter.x, root.surveyCenter.y,
                        parseFloat(surveyWidth.value), parseFloat(surveyHeight.value), sp,
                        parseFloat(surveyAngle.value) || 0, parseFloat(surveyAlt.value) || 20)
                    root.setStatus(n > 0 ? "Generated " + n + " survey waypoints" : "⚠ Grid too large or invalid", n > 0)
                    if (n > 0) root.setTool("")
                }
            }
        }
    }

    // orbit
    CtxPanel {
        shown: root.contextKind === "orbit"; below: topBar; edge: "#66B38CFF"
        height: orbitCol.implicitHeight + 28
        Column {
            id: orbitCol
            anchors.fill: parent; anchors.margins: 14; spacing: 8
            PanelTitle { text: "ORBIT SETTINGS"; tone: "#B38CFF"; onClosed: root.setTool("orbit") }
            LabeledNumber { title: "Radius (m)"; value: "15"; onValueChanged: { var v = parseFloat(value); if (v > 0) Mission.setOrbitRadius(v) } }
            LabeledNumber { title: "Speed (m/s)"; value: "2"; onValueChanged: { var v = parseFloat(value); if (!isNaN(v)) Mission.setOrbitVelocity(v) } }
            Text {
                width: parent.width
                text: "Positive = clockwise.\nNegative = counter-clockwise."
                wrapMode: Text.WordWrap
                font.family: Token.typography_familyMono; font.pixelSize: 9; color: Token.color_text_muted
            }
        }
    }

    // waypoint
    CtxPanel {
        shown: root.contextKind === "waypoint"; below: topBar
        height: wpCol.implicitHeight + 28
        readonly property var wp: Mission.selectedIndex >= 0 && Mission.selectedIndex < Mission.waypoints.length
                                  ? Mission.waypoints[Mission.selectedIndex] : null
        Column {
            id: wpCol
            anchors.fill: parent; anchors.margins: 14; spacing: 8
            PanelTitle { text: "WAYPOINT " + (Mission.selectedIndex + 1); onClosed: Mission.selectWaypoint(-1) }   // markers are 1-based
            Text { text: "COMMAND"; font.family: Token.typography_familyMono; font.pixelSize: 9; font.letterSpacing: 1.2; color: Token.color_ui_textDim }
            Row {
                spacing: 4
                Repeater {
                    model: ["WAYPOINT", "TAKEOFF", "LAND"]
                    delegate: Rectangle {
                        id: seg
                        required property string modelData
                        readonly property bool on: wpCol.parent.wp !== null && wpCol.parent.wp.command === modelData
                        width: (wpCol.width - 8) / 3; height: 28; radius: 6
                        color: on ? Token.color_ui_accentSoft : "transparent"
                        border.width: 1; border.color: on ? Token.color_ui_accentLine : Token.color_ui_line
                        Text { anchors.centerIn: parent; text: modelData === "WAYPOINT" ? "WP" : modelData
                               font.family: Token.typography_familyMono; font.pixelSize: 9; font.letterSpacing: 0.8
                               color: seg.on ? Token.color_accent_primary : Token.color_ui_text }
                        HoverHandler { cursorShape: Qt.PointingHandCursor }
                        TapHandler { gesturePolicy: TapHandler.ReleaseWithinBounds
                                     onTapped: Mission.setWaypointCommand(Mission.selectedIndex, modelData) }
                    }
                }
            }
            LabeledNumber {
                id: wpAlt
                title: "Altitude (m)"
                onCommitted: { var v = parseFloat(value); if (!isNaN(v)) Mission.setWaypointAlt(Mission.selectedIndex, v) }
                // follow the selection, but never fight the user while typing
                Binding on value {
                    when: !wpAlt.field.activeFocus
                    value: wpCol.parent.wp ? String(wpCol.parent.wp.alt) : ""
                }
            }
            TextButton {
                width: parent.width; height: 30
                label: "DELETE WAYPOINT"; tone: "danger"
                onClicked: { Mission.deleteWaypoint(Mission.selectedIndex); Mission.selectWaypoint(-1) }
            }
        }
    }

    // fence vertex
    CtxPanel {
        shown: root.contextKind === "fence"; below: topBar; edge: "#6600E5E5"
        height: fenceCol.implicitHeight + 28
        Column {
            id: fenceCol
            anchors.fill: parent; anchors.margins: 14; spacing: 8
            PanelTitle { text: "FENCE POINT " + (root.selectedFenceIndex + 1); tone: "#5ADBFF"; onClosed: root.selectedFenceIndex = -1 }
            Text { text: "LAT"; font.family: Token.typography_familyMono; font.pixelSize: 9; color: Token.color_ui_textDim }
            Text { text: root.selectedFenceIndex >= 0 && root.selectedFenceIndex < Mission.fencePoints.length
                         ? Number(Mission.fencePoints[root.selectedFenceIndex][0]).toFixed(6) : "–"
                   font.family: Token.typography_familyMono; font.pixelSize: 11; color: "#5ADBFF" }
            Text { text: "LON"; font.family: Token.typography_familyMono; font.pixelSize: 9; color: Token.color_ui_textDim }
            Text { text: root.selectedFenceIndex >= 0 && root.selectedFenceIndex < Mission.fencePoints.length
                         ? Number(Mission.fencePoints[root.selectedFenceIndex][1]).toFixed(6) : "–"
                   font.family: Token.typography_familyMono; font.pixelSize: 11; color: "#5ADBFF" }
            TextButton {
                width: parent.width; height: 30
                label: "DELETE POINT"; tone: "danger"
                onClicked: { Mission.deleteFencePoint(root.selectedFenceIndex); root.selectedFenceIndex = -1 }
            }
        }
    }

    // ---- status + fence count --------------------------------------------------------------------------------
    Rectangle {
        visible: root.statusText !== ""
        anchors.bottom: parent.bottom; anchors.bottomMargin: 20
        anchors.left: parent.left; anchors.leftMargin: 20
        width: statusLabel.implicitWidth + 28; height: 30; radius: 8
        color: Token.color_ui_glassStrong
        border.width: 1
        border.color: root.statusOk ? Token.color_ui_okLine : Token.color_ui_dangerLine
        z: 20
        Text {
            id: statusLabel
            anchors.centerIn: parent
            text: root.statusText
            font.family: Token.typography_familyMono
            font.pixelSize: 10; font.letterSpacing: 0.8
            color: root.statusOk ? Token.color_status_ok : "#FF8A8A"
        }
    }
    Rectangle {
        visible: Mission.fencePoints.length > 0
        anchors.bottom: parent.bottom; anchors.bottomMargin: 20
        anchors.right: parent.right; anchors.rightMargin: 20
        width: fenceCountText.implicitWidth + 28; height: 30; radius: 8
        color: Token.color_ui_glassStrong
        border.width: 1; border.color: "#6600E5E5"
        z: 20
        Text {
            id: fenceCountText
            anchors.centerIn: parent
            text: "FENCE: " + Mission.fencePoints.length + " PTS" + (Mission.fencePoints.length < 3 ? " (need 3+)" : " ✓")
            font.family: Token.typography_familyMono
            font.pixelSize: 10; font.letterSpacing: 0.8
            color: "#5ADBFF"
        }
    }

    // ---- confirm popup for destructive actions -------------------------------------------------------------------
    Popup {
        id: confirm
        property var onYes: null
        property string message: ""
        function ask(msg, cb) { message = msg; onYes = cb; open() }
        anchors.centerIn: Overlay.overlay
        modal: true
        padding: 18
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        Overlay.modal: Rectangle { color: Qt.rgba(0, 0, 0, 0.4) }
        background: Rectangle { radius: 12; color: Token.color_ui_glassSolid; border.width: 1; border.color: Token.color_ui_lineStrong }
        contentItem: Column {
            spacing: 16
            Text { text: confirm.message; color: Token.color_ui_text; font.family: Token.typography_familyUi; font.pixelSize: 13 }
            Row {
                spacing: 8
                layoutDirection: Qt.RightToLeft
                anchors.right: parent.right
                TextButton { label: "CONFIRM"; tone: "danger"; onClicked: { confirm.close(); if (confirm.onYes) confirm.onYes() } }
                TextButton { label: "CANCEL"; onClicked: confirm.close() }
            }
        }
    }

    // ---- file dialogs ------------------------------------------------------------------------------------------------
    FileDialog {
        id: missionImportDialog
        nameFilters: ["Mission files (*.json *.waypoints *.txt)"]
        onAccepted: {
            var u = selectedFile.toString()
            var ok = u.toLowerCase().endsWith(".json") ? Mission.importFromFile(u) : Mission.importQgcWaypoints(u)
            root.setStatus(ok ? "Mission imported" : "⚠ Could not read that file", ok)
        }
    }
    FileDialog {
        id: fenceImportDialog
        nameFilters: ["Fence files (*.json)"]
        onAccepted: {
            var ok = Mission.importFromFile(selectedFile.toString())   // only replaces what the file contains
            root.setStatus(ok ? "Fence imported" : "⚠ Could not read that file", ok)
        }
    }
    FileDialog {
        id: missionExportDialog
        fileMode: FileDialog.SaveFile
        defaultSuffix: "json"
        nameFilters: ["Mission JSON (*.json)"]
        onAccepted: root.setStatus(Mission.exportMissionTo(selectedFile.toString()) ? "Mission exported" : "⚠ Export failed", true)
    }
    FileDialog {
        id: fenceExportDialog
        fileMode: FileDialog.SaveFile
        defaultSuffix: "json"
        nameFilters: ["Fence JSON (*.json)"]
        onAccepted: root.setStatus(Mission.exportFenceTo(selectedFile.toString()) ? "Fence exported" : "⚠ Export failed", true)
    }

    // ---- logic --------------------------------------------------------------------------------------------------------
    function uploadMission() {
        if (!Mission.validateMission()) return          // reports why via lastResult
        setStatus("Uploading mission…")
        Mission.upload()
    }
    function uploadFence() {
        if (Mission.fencePoints.length < 3) { setStatus("⚠ Fence needs at least 3 points", false); return }
        if (!Mission.isHomeInsideFence()) { setStatus("⚠ Fence must include the HOME position", false); return }
        setStatus("Uploading geofence…")
        Mission.uploadFence()
    }
    function exportMission() {
        if (Mission.waypoints.length < 1) { setStatus("Nothing to export", false); return }
        missionExportDialog.open()
    }
    function exportFence() {
        if (Mission.fencePoints.length < 3) { setStatus("Nothing to export", false); return }
        fenceExportDialog.open()
    }
}
