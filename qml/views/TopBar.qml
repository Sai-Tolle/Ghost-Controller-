import QtQuick
import QtQuick.Controls
import "../components"

// Top bar: [logo · GCS ▾] | MODE ▾ | GPS ▾ | BATT ............ FIRMWARE | ARM pill.
// Navigation goes UP through signals (openPlanner / openVideo): the old code
// reached for Window.window from handlers, which does not resolve there.
Rectangle {
    id: root

    readonly property var tm: Telemetry.telemetry
    readonly property bool linked: tm.connected
    readonly property bool sim: Telemetry.source === "simulated"
    signal openPlanner()
    signal openVideo()
    signal openParams()
    signal openLink()

    color: Token.color_hud_topbarBg
    implicitHeight: Token.dimension_hud_topBarHeight

    Rectangle {                                       // bottom hairline
        anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom
        height: 1
        color: Token.color_ui_line
    }

    // ---- left cluster ----------------------------------------------------------
    Row {
        anchors.left: parent.left
        anchors.leftMargin: 14
        anchors.verticalCenter: parent.verticalCenter
        spacing: 14

        Item {                                        // logo + GCS menu
            id: logoBtn
            objectName: "logoBtn"
            anchors.verticalCenter: parent.verticalCenter
            width: logoRow.implicitWidth + 12
            height: 38
            Rectangle {
                anchors.fill: parent
                radius: 8
                color: menu.opened || logoHover.hovered ? Qt.rgba(1, 1, 1, 0.06) : "transparent"
            }
            Row {
                id: logoRow
                anchors.centerIn: parent
                spacing: 9
                Item {
                    width: 26; height: 26
                    anchors.verticalCenter: parent.verticalCenter
                    Image {
                        id: logo
                        anchors.fill: parent
                        source: Qt.resolvedUrl("../../assets/Logo.jpg")
                        fillMode: Image.PreserveAspectCrop
                        mipmap: true
                        visible: status === Image.Ready
                    }
                    Rectangle {                       // fallback mark when the asset is missing
                        anchors.fill: parent
                        visible: logo.status !== Image.Ready
                        radius: 13
                        color: "transparent"
                        border.width: 1.5
                        border.color: Token.color_accent_primary
                        Text {
                            anchors.centerIn: parent
                            text: "G"
                            font.family: Token.typography_familyMono
                            font.pixelSize: 13
                            font.weight: Font.Bold
                            color: "#FFFFFF"
                        }
                    }
                }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: root.sim ? "GCS · SIM" : "GCS"
                    font.family: Token.typography_familyMono
                    font.pixelSize: 13
                    font.weight: Font.Bold
                    font.letterSpacing: 3
                    color: "#FFFFFF"
                }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: menu.opened ? "▴" : "▾"
                    font.pixelSize: 10
                    color: Token.color_ui_textDim
                }
            }
            HoverHandler { id: logoHover; cursorShape: Qt.PointingHandCursor }
            TapHandler { gesturePolicy: TapHandler.ReleaseWithinBounds; onTapped: menu.opened ? menu.close() : menu.open() }

            Popup {
                id: menu
                y: logoBtn.height + 8
                width: 200
                padding: 4
                closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
                background: Rectangle {
                    radius: 10
                    color: Token.color_ui_glassStrong
                    border.width: 1
                    border.color: Token.color_ui_lineStrong
                }
                contentItem: Column {
                    Repeater {
                        model: [{ text: "Mission Planner", act: "planner" },
                                { text: "Parameters", act: "params" },
                                { text: "Connection", act: "link" },
                                { text: "Video Source", act: "video" }]
                        delegate: Item {
                            id: mi
                            required property var modelData
                            objectName: "menu_" + modelData.act
                            width: menu.availableWidth; height: 32
                            Rectangle {
                                anchors.fill: parent
                                radius: 6
                                color: miHover.hovered ? Qt.rgba(1, 1, 1, 0.07) : "transparent"
                            }
                            Text {
                                anchors.left: parent.left
                                anchors.leftMargin: 10
                                anchors.verticalCenter: parent.verticalCenter
                                text: mi.modelData.text
                                font.family: Token.typography_familyUi
                                font.pixelSize: 12
                                color: Token.color_ui_text
                            }
                            HoverHandler { id: miHover; cursorShape: Qt.PointingHandCursor }
                            TapHandler {
                                gesturePolicy: TapHandler.ReleaseWithinBounds
                                onTapped: {
                                    menu.close()
                                    var a = mi.modelData.act
                                    if (a === "planner") root.openPlanner()
                                    else if (a === "params") root.openParams()
                                    else if (a === "link") root.openLink()
                                    else root.openVideo()
                                }
                            }
                        }
                    }
                }
            }
        }

        Rectangle { width: 1; height: 24; color: Token.color_ui_line; anchors.verticalCenter: parent.verticalCenter }
        ModeSelector { anchors.verticalCenter: parent.verticalCenter }
        GpsIndicator { anchors.verticalCenter: parent.verticalCenter }

        BatteryIndicator { anchors.verticalCenter: parent.verticalCenter }
    }

    // ---- right cluster ----------------------------------------------------------------
    Row {
        anchors.right: parent.right
        anchors.rightMargin: 14
        anchors.verticalCenter: parent.verticalCenter
        spacing: 16

        Column {
            anchors.verticalCenter: parent.verticalCenter
            spacing: 2
            Text {
                text: "FIRMWARE"
                font.family: Token.typography_familyMono
                font.pixelSize: 9
                font.letterSpacing: 1.4
                font.weight: Font.DemiBold
                color: Token.color_ui_textDim
            }
            Text {
                text: root.linked && Vehicle.firmware !== "" ? Vehicle.firmware : "—"
                font.family: Token.typography_familyMono
                font.pixelSize: 13
                font.weight: Font.Bold
                color: Vehicle.firmware === "PX4" ? Token.color_accent_primary
                     : Vehicle.firmware === "ArduPilot" ? "#34D8B0" : Token.color_text_muted
            }
        }

        Rectangle {                                    // ARM state pill (click → CONNECTION)
            id: pill
            objectName: "linkPill"
            anchors.verticalCenter: parent.verticalCenter
            HoverHandler { id: pillHover; cursorShape: Qt.PointingHandCursor }
            TapHandler { gesturePolicy: TapHandler.ReleaseWithinBounds; onTapped: root.openLink() }
            readonly property bool armed: root.linked && root.tm.armed
            readonly property bool notReady: root.linked && !armed && !Vehicle.healthReady
            readonly property color tone: !root.linked ? Token.color_text_muted
                                        : armed ? Token.color_status_warn
                                        : notReady ? Token.color_status_danger : Token.color_status_ok
            height: 28
            width: pillRow.implicitWidth + 24
            radius: 7
            color: !root.linked ? "transparent" : armed ? Token.color_ui_warnSoft
                 : notReady ? Token.color_ui_dangerSoft : Token.color_ui_okSoft
            border.width: 1
            border.color: Qt.alpha(tone, pillHover.hovered ? 0.95 : 0.6)
            Row {
                id: pillRow
                anchors.centerIn: parent
                spacing: 7
                Rectangle { width: 6; height: 6; radius: 3; color: pill.tone; anchors.verticalCenter: parent.verticalCenter }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: !root.linked ? (Link.status === "disconnected" ? "DISCONNECTED" : "NO LINK") : pill.armed ? "ARMED"
                          : pill.notReady ? "NOT READY" + (Vehicle.healthReason && Vehicle.healthReason !== "OK" ? " · " + Vehicle.healthReason : "")
                          : "DISARMED"
                    font.family: Token.typography_familyMono
                    font.pixelSize: 11
                    font.weight: Font.Bold
                    font.letterSpacing: 1.6
                    color: pill.tone
                }
            }
        }
    }
}
