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

    // ---- heading tape + roll scale (top centre; clears the alert banner) --------------
    HeadingTape {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.top: parent.top
        anchors.topMargin: root.topInset + 56
        width: Math.min(480, parent.width * 0.36)
        heading: root.tm.heading
        visible: root.link
    }
    RollArc {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.top: parent.top
        anchors.topMargin: root.topInset + 140
        width: 300; height: 64
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
            ctx.shadowColor = "rgba(0,0,0,0.5)"; ctx.shadowBlur = 5
            ctx.strokeStyle = "#FFFFFF"; ctx.lineWidth = 2.25
            ctx.lineCap = "round"; ctx.lineJoin = "round"
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
        title: "Speed"; readout: root.tm.speed.toFixed(1); unit: "m/s"
        side: "left"
        visible: root.link
    }
    EdgeTape {
        anchors { right: parent.right; top: parent.top; bottom: parent.bottom; topMargin: root.topInset }
        width: Token.dimension_hud_tapeWidth
        value: root.tm.altitude; step: 2
        title: "Altitude"; readout: root.tm.altitude.toFixed(1); unit: "m"
        side: "right"
        visible: root.link
    }

    // ---- map button (top right) -------------------------------------------------------------
    Rectangle {
        id: mapBtn
        objectName: "mapBtn"
        width: 44; height: 44; radius: 22
        anchors.top: parent.top
        anchors.topMargin: root.topInset + 16
        anchors.right: parent.right
        anchors.rightMargin: 16
        color: mapTap.pressed ? Token.color_ui_glassStrong : Token.color_ui_glass
        border.width: 1
        border.color: mapHover.hovered ? Token.color_ui_lineStrong : Token.color_ui_line
        scale: mapTap.pressed ? 0.94 : 1
        Behavior on scale { NumberAnimation { duration: Token.motion_fast } }
        Behavior on color { ColorAnimation { duration: Token.motion_fast } }
        Icon { anchors.centerIn: parent; name: "map"; size: 20; color: Token.color_ui_text }
        HoverHandler { id: mapHover; cursorShape: Qt.PointingHandCursor }
        TapHandler {
            id: mapTap
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
        width: 264
        height: dock.implicitHeight + 28
        radius: Token.dimension_radius_xl
        color: Token.color_ui_glass
        border.width: 1
        border.color: Token.color_ui_line
        SoftShadow { visible: true }
    }
    Column {
        id: dock
        anchors.left: parent.left
        anchors.bottom: parent.bottom
        anchors.leftMargin: 30
        anchors.bottomMargin: 30
        width: 236
        spacing: 8
        enabled: root.link

        Item {                                        // dock header: title + armed state
            width: parent.width; height: 24
            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: "Commands"
                font.pixelSize: Token.typography_size_lg; font.weight: Font.DemiBold
                color: Token.color_ui_text
            }
            Rectangle {
                id: dockState
                readonly property color tone: !root.link ? Token.color_text_muted
                                            : root.tm.armed ? Token.color_status_warn : Token.color_status_ok
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                width: dockStateText.implicitWidth + 16; height: 20; radius: 10
                color: Qt.alpha(tone, 0.18)
                Text {
                    id: dockStateText
                    anchors.centerIn: parent
                    text: !root.link ? "Offline" : root.tm.armed ? "Armed" : "Safe"
                    font.pixelSize: 11; font.weight: Font.DemiBold
                    color: dockState.tone
                }
            }
        }

        GridLayout {
            width: parent.width
            columns: 2
            columnSpacing: 8
            rowSpacing: 8
            HudCmdButton {
                objectName: "armBtn"
                Layout.fillWidth: true; Layout.preferredHeight: 40
                label: root.tm.armed ? "Disarm" : "Arm"
                onClicked: root.tm.armed ? Vehicle.disarm() : Vehicle.arm()
            }
            HudCmdButton {
                Layout.fillWidth: true; Layout.preferredHeight: 40
                label: "Takeoff"
                sublabel: Vehicle.takeoffAltitude.toFixed(0) + " m"
                onClicked: Vehicle.takeoff(Vehicle.takeoffAltitude)
            }
            HudCmdButton {
                Layout.fillWidth: true; Layout.preferredHeight: 40
                label: "Land"
                onClicked: Vehicle.land()
            }
            HudCmdButton {
                Layout.fillWidth: true; Layout.preferredHeight: 40
                label: "RTL"
                onClicked: Vehicle.rtl()
            }
        }
        HudCmdButton {
            width: parent.width
            label: "Start Mission"
            tone: "primary"
            enabled: root.link && Mission.commandable && Mission.waypoints.length > 0
            onClicked: Mission.startMission()
        }
        HudCmdButton {
            width: parent.width
            label: "Kill Switch"
            sublabel: "Double-click"
            tone: "danger"
            onDoubleClicked: Vehicle.kill()
        }
    }

    // ---- YAW / PITCH / CLIMB (bottom centre): one capsule, hairline-divided ----------------
    Rectangle {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 16
        visible: root.link
        width: attRow.implicitWidth
        height: 52
        radius: Token.dimension_radius_lg
        color: Token.color_ui_glass
        border.width: 1
        border.color: Token.color_ui_line
        Row {
            id: attRow
            anchors.verticalCenter: parent.verticalCenter
            Repeater {
                model: [
                    { label: "Yaw",   value: root.tm.heading.toFixed(1) + "°" },
                    { label: "Pitch", value: root.tm.pitch.toFixed(1) + "°" },
                    { label: "Climb", value: (root.tm.climb >= 0 ? "+" : "") + root.tm.climb.toFixed(1) + " m/s" },
                ]
                delegate: Item {
                    id: chip
                    required property var modelData
                    required property int index
                    width: Math.max(92, chipCol.implicitWidth + 32)
                    height: 52
                    Rectangle {
                        visible: chip.index > 0
                        width: 1; height: 26
                        anchors.verticalCenter: parent.verticalCenter
                        color: Token.color_ui_line
                    }
                    Column {
                        id: chipCol
                        anchors.centerIn: parent
                        spacing: 1
                        Text {
                            anchors.horizontalCenter: parent.horizontalCenter
                            text: chip.modelData.label
                            font.pixelSize: 11
                            color: Token.color_ui_textDim
                        }
                        Text {
                            anchors.horizontalCenter: parent.horizontalCenter
                            text: chip.modelData.value
                            font.features: { "tnum": 1 }
                            font.pixelSize: 17; font.weight: Font.DemiBold
                            color: Token.color_ui_text
                        }
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
        text: Video.fps.toFixed(0) + " fps"
        font.pixelSize: 11; font.weight: Font.Medium
        color: Qt.rgba(1, 1, 1, 0.8)
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
        width: Math.max(380, Math.min(520, scCol.implicitWidth + 64))
        height: scCol.implicitHeight + 56
        radius: Token.dimension_radius_xl
        color: Token.color_ui_glass
        border.width: 1
        border.color: Token.color_ui_line
        SoftShadow { visible: true }
        Column {
            id: scCol
            anchors.centerIn: parent
            spacing: 8
            Item {                                    // status glyph with a slow "searching" pulse
                anchors.horizontalCenter: parent.horizontalCenter
                width: 56; height: 64
                Rectangle {
                    id: pulse
                    anchors.centerIn: parent
                    width: 56; height: 56; radius: 28
                    color: "transparent"
                    border.width: 2; border.color: sc.tone
                    opacity: 0
                    SequentialAnimation on scale {
                        running: sc.visible; loops: Animation.Infinite
                        NumberAnimation { from: 0.45; to: 1.0; duration: 1600; easing.type: Easing.OutCubic }
                        PauseAnimation { duration: 400 }
                    }
                    SequentialAnimation on opacity {
                        running: sc.visible; loops: Animation.Infinite
                        NumberAnimation { from: 0.7; to: 0; duration: 1600; easing.type: Easing.OutCubic }
                        PauseAnimation { duration: 400 }
                    }
                }
                Rectangle {
                    anchors.centerIn: parent
                    width: 36; height: 36; radius: 18
                    color: Qt.alpha(sc.tone, 0.18)
                    Rectangle { anchors.centerIn: parent; width: 12; height: 12; radius: 6; color: sc.tone }
                }
            }
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: sc.heading
                font.pixelSize: Token.typography_size_title; font.weight: Font.DemiBold
                color: Token.color_ui_text
            }
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                visible: sc.detail !== ""
                width: Math.min(implicitWidth, 440)
                horizontalAlignment: Text.AlignHCenter
                elide: Text.ElideMiddle
                text: sc.detail
                font.pixelSize: 14
                color: Token.color_text_secondary
            }
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                visible: sc.note !== ""
                width: Math.min(implicitWidth, 440)
                horizontalAlignment: Text.AlignHCenter
                elide: Text.ElideRight
                text: sc.note
                font.pixelSize: 11
                color: sc.tone
            }
            Row {
                id: actionRow
                anchors.horizontalCenter: parent.horizontalCenter
                topPadding: 12
                spacing: 10
            }
        }
    }

    StateCard {                                       // link down (or video dropped mid-session)
        anchors.centerIn: parent
        visible: root.wasLive && (!root.link || !root.showVideo)
        heading: root.link ? qsTr("Video signal lost") : qsTr("Connection Lost")
        detail: root.link ? qsTr("Waiting for frames from the camera…")
                          : qsTr("Vehicle link down — reconnecting on %1").arg(Link.target)
        TextButton {
            label: root.link ? qsTr("Video Source") : qsTr("Connection")
            onClicked: root.link ? root.openVideo() : root.openLink()
        }
    }
    Rectangle {                                       // link up, no camera on this vehicle
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 84
        visible: root.link && !root.showVideo && !root.wasLive
        width: camRow.implicitWidth + 32; height: 34; radius: 17
        color: camHover.hovered ? Token.color_ui_glassStrong : Token.color_ui_glass
        border.width: 1
        border.color: Token.color_ui_line
        Row {
            id: camRow
            anchors.centerIn: parent
            spacing: 8
            Rectangle { width: 8; height: 8; radius: 4; color: Token.color_status_warn; anchors.verticalCenter: parent.verticalCenter }
            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: qsTr("No camera source")
                font.pixelSize: 13; font.weight: Font.Medium
                color: Token.color_ui_text
            }
            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: qsTr("Set Up Video ›")
                font.pixelSize: 13; font.weight: Font.Medium
                color: Token.color_accent_primary
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
        heading: off ? qsTr("Disconnected") : none ? qsTr("No vehicle backend") : qsTr("No vehicle link")
        detail: none ? qsTr("Running without a MAVLink backend.")
              : off ? qsTr("Link is off. Target: %1").arg(Link.target)
              : Link.status === "waiting" ? qsTr("Listening on %1 — waiting for a heartbeat").arg(Link.target)
              : qsTr("Trying %1").arg(Link.target)
        note: !off && !none && Link.error !== "" ? Link.error : ""
        TextButton {
            visible: Link.available && Link.status === "disconnected"
            label: qsTr("Connect"); tone: "primary"
            onClicked: Link.connectLink()
        }
        TextButton {
            visible: Link.available
            label: qsTr("Connection Settings")
            onClicked: root.openLink()
        }
    }
}
