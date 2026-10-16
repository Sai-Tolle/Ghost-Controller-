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
        anchors.leftMargin: 12
        anchors.verticalCenter: parent.verticalCenter
        spacing: 6

        Item {                                        // logo + GCS menu
            id: logoBtn
            objectName: "logoBtn"
            anchors.verticalCenter: parent.verticalCenter
            width: logoRow.implicitWidth + 16
            height: 36
            Rectangle {
                anchors.fill: parent
                radius: Token.dimension_radius_md
                color: menu.opened ? Token.color_ui_fillPressed : logoHover.hovered ? Token.color_ui_fill : "transparent"
                Behavior on color { ColorAnimation { duration: Token.motion_fast } }
            }
            Row {
                id: logoRow
                anchors.centerIn: parent
                spacing: 9
                Item {                                // theme-matched mark (both PNGs are derived from Logo.jpg)
                    width: 26; height: 26
                    anchors.verticalCenter: parent.verticalCenter
                    Image {
                        id: logo
                        anchors.fill: parent
                        source: Qt.resolvedUrl(Token.theme === "light" ? "../../assets/Logo-mark-dark.png" : "../../assets/Logo-mark.png")
                        fillMode: Image.PreserveAspectCrop
                        mipmap: true
                        smooth: true
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
                            font.pixelSize: 13
                            font.weight: Font.DemiBold
                            color: Token.color_ui_text
                        }
                    }
                }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: "Ghost Controller"
                    font.pixelSize: 14
                    font.weight: Font.DemiBold
                    color: Token.color_ui_text
                }
                Rectangle {                           // unmistakable: this is NOT a real vehicle
                    visible: root.sim
                    anchors.verticalCenter: parent.verticalCenter
                    width: simTag.implicitWidth + 14; height: 20; radius: 10
                    color: Token.color_ui_warnSoft
                    Text { id: simTag; anchors.centerIn: parent; text: "Simulation"
                           font.pixelSize: 11
                           font.weight: Font.DemiBold; color: Token.color_status_warn }
                }
                Icon {
                    anchors.verticalCenter: parent.verticalCenter
                    name: "chevron.down"; size: 11; weight: 1.6
                    color: Token.color_ui_textDim
                    rotation: menu.opened ? 180 : 0
                    Behavior on rotation { NumberAnimation { duration: Token.motion_fast; easing.type: Easing.OutCubic } }
                }
            }
            HoverHandler { id: logoHover; cursorShape: Qt.PointingHandCursor }
            TapHandler { gesturePolicy: TapHandler.ReleaseWithinBounds; onTapped: menu.opened ? menu.close() : menu.open() }

            Popup {
                id: menu
                y: logoBtn.height + 8
                width: 232
                padding: 5
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
                    radius: Token.dimension_radius_md
                    color: Token.color_ui_glassStrong
                    border.width: 1
                    border.color: Token.color_ui_line
                }
                contentItem: Column {
                    Repeater {
                        model: [{ text: "Mission Planner", act: "planner", icon: "map" },
                                { text: "Parameters", act: "params", icon: "gear" },
                                { text: "Connection", act: "link", icon: "link" },
                                { text: "Video Source", act: "video", icon: "video" }]
                        delegate: Item {
                            id: mi
                            required property var modelData
                            objectName: "menu_" + modelData.act
                            width: menu.availableWidth; height: 28
                            Rectangle {
                                anchors.fill: parent
                                radius: 5
                                color: miHover.hovered ? Token.color_accent_primary : "transparent"
                            }
                            Icon {
                                anchors.left: parent.left
                                anchors.leftMargin: 9
                                anchors.verticalCenter: parent.verticalCenter
                                name: mi.modelData.icon; size: 15; weight: 1.5
                                color: miHover.hovered ? "#FFFFFF" : Token.color_ui_textDim
                            }
                            Text {
                                anchors.left: parent.left
                                anchors.leftMargin: 32
                                anchors.verticalCenter: parent.verticalCenter
                                text: mi.modelData.text
                                font.pixelSize: 13
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
                    Item { width: menu.availableWidth; height: 11
                           Rectangle { anchors.centerIn: parent; width: parent.width - 16; height: 1; color: Token.color_ui_line } }
                    Column {                          // appearance: dark / light / follow the OS
                        objectName: "appearance"
                        width: menu.availableWidth
                        leftPadding: 10; rightPadding: 10; topPadding: 2; bottomPadding: 6
                        spacing: 6
                        Text {
                            text: "Appearance"
                            font.pixelSize: 11; font.weight: Font.DemiBold
                            color: Token.color_text_muted
                        }
                        SegControl {
                            width: parent.width - 20
                            options: [{ id: "dark", label: "Dark" }, { id: "light", label: "Light" },
                                      { id: "system", label: "Auto" }]
                            current: Theme.preference
                            onPicked: function(id) { Theme.setPreference(id) }
                        }
                    }
                    Item { width: menu.availableWidth; height: 11
                           Rectangle { anchors.centerIn: parent; width: parent.width - 16; height: 1; color: Token.color_ui_line } }
                    Item {                            // about row
                        width: menu.availableWidth; height: 30
                        Text {
                            anchors.left: parent.left; anchors.leftMargin: 10
                            anchors.verticalCenter: parent.verticalCenter
                            text: "Ghost Controller"
                            font.pixelSize: 12
                            color: Token.color_ui_textDim
                        }
                        Text {
                            anchors.right: parent.right; anchors.rightMargin: 10
                            anchors.verticalCenter: parent.verticalCenter
                            text: "v" + AppInfo.version
                            font.pixelSize: 11
                            color: Token.color_ui_textDim
                        }
                    }
                }
            }
        }

        Rectangle { width: 1; height: 20; color: Token.color_ui_line; anchors.verticalCenter: parent.verticalCenter }
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
                text: "Firmware"
                font.pixelSize: 11
                color: Token.color_ui_textDim
            }
            Text {
                text: root.linked && Vehicle.firmware !== "" ? Vehicle.firmware : "—"
                font.pixelSize: 13
                font.weight: Font.DemiBold
                color: Vehicle.firmware === "PX4" ? Token.color_accent_primary
                     : Vehicle.firmware === "ArduPilot" ? "#63E6E2" : Token.color_text_muted
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
            height: 30
            width: pillRow.implicitWidth + 26
            radius: height / 2
            color: Qt.alpha(tone, pillHover.hovered ? 0.26 : 0.16)
            Behavior on color { ColorAnimation { duration: Token.motion_fast } }
            Row {
                id: pillRow
                anchors.centerIn: parent
                spacing: 7
                Rectangle { width: 8; height: 8; radius: 4; color: pill.tone; anchors.verticalCenter: parent.verticalCenter }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: !root.linked ? (Link.status === "disconnected" ? "Disconnected" : "No Link") : pill.armed ? "Armed"
                          : pill.notReady ? "Not Ready" + (Vehicle.healthReason && Vehicle.healthReason !== "OK" ? " · " + Vehicle.healthReason : "")
                          : "Disarmed"
                    font.pixelSize: 12
                    font.weight: Font.DemiBold
                    color: pill.tone
                }
            }
        }
    }
}
