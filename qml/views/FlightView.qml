import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

// Video-first flight HUD. Full-bleed live video with NO overlay effects
// (no vignette, no tint); HUD linework is white with a soft shadow so it stays
// legible on any footage. Layout (unchanged): SPEED tape left edge, ALT tape
// right edge, heading + roll arc top-centre, pitch ladder + bore-sight centre,
// YAW/PITCH/CLIMB chips bottom-centre, command dock bottom-left, map button
// top-right.
Item {
    id: root
    signal openMap()
    signal openLink()
    signal openVideo()

    readonly property var tm: Telemetry.telemetry
    readonly property bool link: tm.connected
    readonly property bool showVideo: Video.hasFrame
    property bool wasLive: false          // latches once frames were seen
    onShowVideoChanged: if (showVideo) wasLive = true
    onLinkChanged: if (link) wasLive = showVideo        // new link session: forget the previous vehicle's camera
    readonly property real topInset: Token.dimension_hud_topBarHeight

    // ---- video layer ---------------------------------------------------------
    Rectangle { anchors.fill: parent; color: Token.color_hud_videoBg }
    Image {
        anchors.fill: parent
        visible: root.showVideo
        source: root.showVideo ? "image://video/" + Video.frameSeq : ""
        fillMode: Image.PreserveAspectFit        // never crop or stretch the camera image
        cache: false
        asynchronous: false
    }

    // ---- heading readout + roll arc (top centre) --------------------------------------
    Text {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.top: parent.top
        anchors.topMargin: root.topInset + 58
        visible: root.link
        text: Math.round(((root.tm.heading % 360) + 360) % 360) + "°"
        font.family: Token.typography_familyMono
        font.pixelSize: 15
        font.weight: Font.Bold
        color: "#FFFFFF"
        style: Text.Outline
        styleColor: Qt.rgba(0, 0, 0, 0.75)
    }
    RollArc {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.top: parent.top
        anchors.topMargin: root.topInset + 80
        width: 160; height: 90
        roll: root.tm.roll
        visible: root.link
    }

    PitchLadder {
        anchors.centerIn: parent
        pitch: root.tm.pitch
        showReference: false
        visible: root.link
    }

    Canvas {                                         // bore-sight
        anchors.centerIn: parent
        width: 220; height: 40
        visible: root.link
        onPaint: {
            var ctx = getContext("2d"); ctx.reset()
            ctx.shadowColor = "rgba(0,0,0,0.7)"; ctx.shadowBlur = 4
            ctx.strokeStyle = "#FFFFFF"; ctx.lineWidth = 2.5
            var cx = width / 2, cy = height / 2
            ctx.beginPath(); ctx.arc(cx, cy, 6, 0, Math.PI * 2); ctx.stroke()
            ctx.beginPath()
            ctx.moveTo(cx - 100, cy); ctx.lineTo(cx - 50, cy); ctx.lineTo(cx - 50, cy + 10)
            ctx.moveTo(cx + 100, cy); ctx.lineTo(cx + 50, cy); ctx.lineTo(cx + 50, cy + 10)
            ctx.stroke()
        }
    }

    // ---- tapes ---------------------------------------------------------------------------
    EdgeTape {
        anchors { left: parent.left; top: parent.top; bottom: parent.bottom; topMargin: root.topInset }
        width: Token.dimension_hud_tapeWidth
        value: root.tm.speed; step: 1
        minValue: 0
        title: "SPEED"; readout: root.tm.speed.toFixed(1); unit: "m/s"
        side: "left"
        sourceNote: root.tm.extra && root.tm.extra.velocity && root.tm.extra.velocity.source
                    ? root.tm.extra.velocity.source : ""
        visible: root.link
    }
    EdgeTape {
        anchors { right: parent.right; top: parent.top; bottom: parent.bottom; topMargin: root.topInset }
        width: Token.dimension_hud_tapeWidth
        value: root.tm.altitude; step: 2
        title: "ALT"; readout: root.tm.altitude.toFixed(1); unit: "m"
        side: "right"
        visible: root.link
    }

    // ---- map button (top right) -------------------------------------------------------------
    Rectangle {
        id: mapBtn
        objectName: "mapBtn"
        width: 44; height: 44; radius: 22
        anchors.top: parent.top
        anchors.topMargin: root.topInset + 12
        anchors.right: parent.right
        anchors.rightMargin: 16
        color: mapHover.hovered ? Token.color_accent_primaryDim : Token.color_ui_glass
        border.width: 1
        border.color: mapHover.hovered ? Token.color_accent_primary : Token.color_ui_lineStrong
        Behavior on color { ColorAnimation { duration: Token.motion_fast } }
        Canvas {
            anchors.centerIn: parent
            width: 22; height: 20
            property bool hot: mapHover.hovered
            onHotChanged: requestPaint()
            onPaint: {
                var ctx = getContext("2d"); ctx.reset()
                ctx.strokeStyle = hot ? "#FFFFFF" : "#A9D2FF"; ctx.lineWidth = 1.8
                ctx.lineJoin = "round"
                ctx.beginPath()
                ctx.moveTo(2, 4); ctx.lineTo(8, 2); ctx.lineTo(14, 4); ctx.lineTo(20, 2)
                ctx.lineTo(20, 16); ctx.lineTo(14, 18); ctx.lineTo(8, 16); ctx.lineTo(2, 18)
                ctx.closePath(); ctx.stroke()
                ctx.beginPath(); ctx.moveTo(8, 2); ctx.lineTo(8, 16)
                ctx.moveTo(14, 4); ctx.lineTo(14, 18); ctx.stroke()
            }
        }
        HoverHandler { id: mapHover; cursorShape: Qt.PointingHandCursor }
        TapHandler {
            gesturePolicy: TapHandler.ReleaseWithinBounds
            onTapped: root.openMap()          // was `Window.window.viewMode = "map"`, which is null inside a handler
        }
    }

    // ---- command dock (bottom left) ----------------------------------------------------------
    Rectangle {
        anchors.left: parent.left
        anchors.bottom: parent.bottom
        anchors.leftMargin: 16
        anchors.bottomMargin: 16
        width: 256
        height: dock.implicitHeight + 24
        radius: 12
        color: Qt.rgba(0.04, 0.06, 0.10, 0.82)
        border.width: 1
        border.color: Token.color_ui_line
    }
    Column {
        id: dock
        anchors.left: parent.left
        anchors.bottom: parent.bottom
        anchors.leftMargin: 28
        anchors.bottomMargin: 28
        width: 232
        spacing: 6
        enabled: root.link

        Item {                                        // dock header: title + armed state
            width: parent.width; height: 18
            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: "COMMANDS"
                font.family: Token.typography_familyMono
                font.pixelSize: 9; font.letterSpacing: 1.8; font.weight: Font.DemiBold
                color: Token.color_ui_textDim
            }
            Text {
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                text: !root.link ? "OFFLINE" : root.tm.armed ? "ARMED" : "SAFE"
                font.family: Token.typography_familyMono
                font.pixelSize: 9; font.letterSpacing: 1.8; font.weight: Font.Bold
                color: !root.link ? Token.color_text_muted
                     : root.tm.armed ? Token.color_status_warn : Token.color_status_ok
            }
        }

        GridLayout {
            width: parent.width
            columns: 2
            columnSpacing: 6
            rowSpacing: 6
            HudCmdButton {
                objectName: "armBtn"
                Layout.fillWidth: true; Layout.preferredHeight: 36
                label: root.tm.armed ? "DISARM" : "ARM"
                onClicked: root.tm.armed ? Vehicle.disarm() : Vehicle.arm()
            }
            HudCmdButton {
                Layout.fillWidth: true; Layout.preferredHeight: 36
                label: "TAKEOFF"
                sublabel: Vehicle.takeoffAltitude.toFixed(0) + " m"
                onClicked: Vehicle.takeoff(Vehicle.takeoffAltitude)
            }
            HudCmdButton {
                Layout.fillWidth: true; Layout.preferredHeight: 36
                label: "LAND"
                onClicked: Vehicle.land()
            }
            HudCmdButton {
                Layout.fillWidth: true; Layout.preferredHeight: 36
                label: "RTL"
                onClicked: Vehicle.rtl()
            }
        }
        HudCmdButton {
            width: parent.width
            label: "START MISSION"
            tone: "primary"
            enabled: root.link && Mission.commandable && Mission.waypoints.length > 0
            onClicked: Mission.startMission()
        }
        HudCmdButton {
            width: parent.width
            label: "KILL SWITCH"
            sublabel: "DOUBLE-CLICK"
            tone: "danger"
            onDoubleClicked: Vehicle.kill()
        }
    }

    // ---- YAW / PITCH / CLIMB (bottom centre) --------------------------------------------------------
    Row {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 14
        spacing: 8
        visible: root.link
        Repeater {
            model: [
                { label: "YAW",   value: root.tm.heading.toFixed(1) + "°" },
                { label: "PITCH", value: root.tm.pitch.toFixed(1) + "°" },
                { label: "CLIMB", value: (root.tm.climb >= 0 ? "+" : "") + root.tm.climb.toFixed(1) + " m/s" },
            ]
            delegate: Rectangle {
                id: chip
                required property var modelData
                width: Math.max(78, chipCol.implicitWidth + 28)
                height: 46
                radius: 8
                color: Token.color_ui_glass
                border.width: 1
                border.color: Token.color_ui_line
                Column {
                    id: chipCol
                    anchors.centerIn: parent
                    spacing: 2
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: chip.modelData.label
                        font.family: Token.typography_familyMono
                        font.pixelSize: 9; font.letterSpacing: 1.6; font.weight: Font.DemiBold
                        color: Token.color_ui_textDim
                    }
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: chip.modelData.value
                        font.family: Token.typography_familyMono
                        font.pixelSize: 15; font.weight: Font.Bold
                        color: "#FFFFFF"
                    }
                }
            }
        }
    }

    // ---- live-stream FPS (top left, only while video is flowing) ----------------------
    Text {
        visible: root.showVideo
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.topMargin: root.topInset + 10
        anchors.leftMargin: 100
        text: Video.fps.toFixed(0) + " FPS"
        font.family: Token.typography_familyMono
        font.pixelSize: 9
        font.letterSpacing: 1
        color: Token.color_status_ok
        style: Text.Outline
        styleColor: Qt.rgba(0, 0, 0, 0.6)
    }

    // ---- honest centre states -----------------------------------------------------------------------
    component StateCard: Rectangle {
        id: sc
        property color tone: Token.color_status_danger
        property string heading: ""
        property string detail: ""
        property string note: ""
        default property alias actions: actionRow.data
        width: Math.max(360, Math.min(520, scCol.implicitWidth + 56))
        height: scCol.implicitHeight + 44
        radius: 14
        color: Qt.rgba(0.04, 0.06, 0.10, 0.90)
        border.width: 1
        border.color: Qt.alpha(sc.tone, 0.45)
        Column {
            id: scCol
            anchors.centerIn: parent
            spacing: 10
            Rectangle {                               // status glyph
                anchors.horizontalCenter: parent.horizontalCenter
                width: 40; height: 40; radius: 20
                color: Qt.alpha(sc.tone, 0.14)
                border.width: 1; border.color: Qt.alpha(sc.tone, 0.6)
                Rectangle { anchors.centerIn: parent; width: 10; height: 10; radius: 5; color: sc.tone }
            }
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: sc.heading
                font.family: Token.typography_familyMono
                font.pixelSize: 17; font.weight: Font.Bold; font.letterSpacing: 3
                color: "#FFFFFF"
            }
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                visible: sc.detail !== ""
                width: Math.min(implicitWidth, 440)
                horizontalAlignment: Text.AlignHCenter
                elide: Text.ElideMiddle
                text: sc.detail
                font.family: Token.typography_familyUi
                font.pixelSize: 13
                color: Token.color_text_secondary
            }
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                visible: sc.note !== ""
                width: Math.min(implicitWidth, 440)
                horizontalAlignment: Text.AlignHCenter
                elide: Text.ElideRight
                text: sc.note
                font.family: Token.typography_familyMono
                font.pixelSize: 10
                color: sc.tone
            }
            Row {
                id: actionRow
                anchors.horizontalCenter: parent.horizontalCenter
                topPadding: 4
                spacing: 8
            }
        }
    }

    StateCard {                                       // link down (or video dropped mid-session)
        anchors.centerIn: parent
        visible: root.wasLive && (!root.link || !root.showVideo)
        heading: root.link ? qsTr("VIDEO SIGNAL LOST") : qsTr("CONNECTION LOST")
        detail: root.link ? qsTr("Waiting for frames from the camera…")
                          : qsTr("Vehicle link down — reconnecting on %1").arg(Link.target)
        TextButton {
            label: root.link ? qsTr("VIDEO SOURCE") : qsTr("CONNECTION")
            onClicked: root.link ? root.openVideo() : root.openLink()
        }
    }
    Rectangle {                                       // link up, no camera on this vehicle
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 78
        visible: root.link && !root.showVideo && !root.wasLive
        width: camRow.implicitWidth + 28; height: 30; radius: 15
        color: Qt.rgba(0.04, 0.06, 0.10, 0.82)
        border.width: 1
        border.color: camHover.hovered ? Token.color_status_warn : Qt.alpha(Token.color_status_warn, 0.5)
        Row {
            id: camRow
            anchors.centerIn: parent
            spacing: 8
            Rectangle { width: 6; height: 6; radius: 3; color: Token.color_status_warn; anchors.verticalCenter: parent.verticalCenter }
            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: qsTr("NO CAMERA SOURCE  ·  SET UP VIDEO")
                font.family: Token.typography_familyMono
                font.pixelSize: 10; font.weight: Font.DemiBold; font.letterSpacing: 1.6
                color: Token.color_status_warn
            }
        }
        HoverHandler { id: camHover; cursorShape: Qt.PointingHandCursor }
        TapHandler { gesturePolicy: TapHandler.ReleaseWithinBounds; onTapped: root.openVideo() }
    }
    StateCard {                                       // nothing connected yet
        anchors.centerIn: parent
        anchors.verticalCenterOffset: -parent.height * 0.06
        visible: !root.link && !root.wasLive
        readonly property bool off: Link.status === "disconnected"
        readonly property bool none: Link.status === "unavailable"
        tone: off || none ? Token.color_text_muted
            : Link.status === "retrying" ? Token.color_status_danger : Token.color_status_warn
        heading: off ? qsTr("DISCONNECTED") : none ? qsTr("NO VEHICLE BACKEND") : qsTr("NO VEHICLE LINK")
        detail: none ? qsTr("Running without a MAVLink backend.")
              : off ? qsTr("Link is off. Target: %1").arg(Link.target)
              : Link.status === "waiting" ? qsTr("Listening on %1 — waiting for a heartbeat").arg(Link.target)
              : qsTr("Trying %1").arg(Link.target)
        note: !off && !none && Link.error !== "" ? Link.error : ""
        TextButton {
            visible: Link.available && Link.status === "disconnected"
            label: qsTr("CONNECT"); tone: "primary"
            onClicked: Link.connectLink()
        }
        TextButton {
            visible: Link.available
            label: qsTr("CONNECTION SETTINGS")
            onClicked: root.openLink()
        }
    }
}
