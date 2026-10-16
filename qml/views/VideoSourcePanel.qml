import QtQuick
import QtQuick.Controls
import "../components"

// Bottom-right video source drawer: detected-stream card, AUTO / RTP / RTSP /
// MJPEG cards with custom-URL fields, feedback strip.
Rectangle {
    id: root
    property bool open: false
    signal closeRequested()

    width: 304
    height: col.implicitHeight + 28
    radius: Token.dimension_radius_xl
    color: Token.color_ui_glassStrong
    border.width: 1
    border.color: Token.color_ui_line
    opacity: open ? 1.0 : 0.0
    visible: opacity > 0.01
    enabled: open
    Behavior on opacity { NumberAnimation { duration: Token.motion_fast } }

    property string feedbackMsg: ""
    property bool feedbackOk: true
    Timer { id: fbTimer; interval: 3500; onTriggered: root.feedbackMsg = "" }
    function showFeedback(msg, ok) { feedbackMsg = msg; feedbackOk = ok; fbTimer.restart() }

    // Surface video errors (e.g. a rejected URL) in the feedback strip.
    Connections {
        target: Video
        function onStatusChanged() {
            if (root.open && Video.state === "error") root.showFeedback(Video.label, false)
        }
    }

    Column {
        id: col
        anchors.fill: parent
        anchors.margins: 14
        spacing: 10

        Item {                                              // header
            width: parent.width; height: 28
            Row {
                anchors.verticalCenter: parent.verticalCenter
                spacing: 9
                Rectangle {
                    width: 26; height: 26; radius: 8
                    color: Token.color_ui_accentSoft
                    Icon { anchors.centerIn: parent; name: "video"; size: 16; color: Token.color_accent_primary }
                }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: "Video Source"
                    font.pixelSize: 15; font.weight: Font.DemiBold
                    color: Token.color_ui_text
                }
            }
            Rectangle {
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                width: 22; height: 22; radius: 11
                color: closeHover.hovered ? Token.color_ui_fillHover : Token.color_ui_fill
                Icon { anchors.centerIn: parent; name: "xmark"; size: 12; weight: 1.8
                       color: closeHover.hovered ? Token.color_ui_text : Token.color_ui_textDim }
                HoverHandler { id: closeHover; cursorShape: Qt.PointingHandCursor }
                TapHandler { onTapped: root.closeRequested() }
            }
        }

        Rectangle {                                        // detected stream
            id: det
            width: parent.width; height: 52; radius: 9
            readonly property bool live: Video.state === "live"
            color: live ? Token.color_ui_okSoft : Token.color_ui_fill
            border.width: 1
            border.color: live ? Token.color_ui_okLine : Token.color_ui_line
            Column {
                anchors.verticalCenter: parent.verticalCenter
                anchors.left: parent.left
                anchors.leftMargin: 12
                spacing: 4
                Row {
                    spacing: 6
                    Rectangle { width: 6; height: 6; radius: 3; anchors.verticalCenter: parent.verticalCenter
                                color: det.live ? Token.color_status_ok : Token.color_text_muted }
                    Text {
                        text: det.live ? "Detected" : "No source detected"
                        font.pixelSize: 11; font.weight: Font.DemiBold
                        color: det.live ? Token.color_status_ok : Token.color_ui_textDim
                    }
                }
                Text {
                    text: Video.state === "live"
                          ? Video.sourceLabel + (Video.resolution !== "" ? "  ·  " + Video.resolution : "") + "  ·  " + Video.fps.toFixed(0) + " fps"
                          : Video.label
                    elide: Text.ElideRight
                    width: 260
                    font.pixelSize: 12; font.weight: Font.DemiBold
                    color: Token.color_ui_text
                }
            }
        }

        Repeater {
            model: Video.modeHints
            delegate: Rectangle {
                id: card
                required property var modelData
                readonly property string mode: modelData.mode
                readonly property bool urlEditable: mode === "rtsp" || mode === "mjpeg"
                readonly property string customUrl: urlEditable ? (Video.customUrls[mode] || "") : ""
                readonly property bool selected: mode === "auto" ? Video.sourceLabel === "auto"
                                                                 : Video.sourceLabel.indexOf(mode) === 0
                width: col.width
                height: cardCol.implicitHeight + 16
                radius: 9
                color: selected ? Token.color_ui_accentSoft : (cardHover.hovered ? Token.color_ui_fillHover : Token.color_ui_fill)
                border.width: 1
                border.color: selected ? Token.color_ui_accentLine : Token.color_ui_line

                Column {
                    id: cardCol
                    anchors.left: parent.left; anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.margins: 10
                    anchors.topMargin: 8
                    spacing: 7
                    Item {                                   // title row (explicit ids — no parent.parent chains)
                        width: parent.width; height: 18
                        Row {
                            anchors.verticalCenter: parent.verticalCenter
                            spacing: 8
                            Text {
                                anchors.verticalCenter: parent.verticalCenter
                                text: card.modelData.label
                                font.pixelSize: 12; font.weight: Font.DemiBold
                                color: Token.color_ui_text
                            }
                            Rectangle {
                                visible: card.customUrl !== ""
                                anchors.verticalCenter: parent.verticalCenter
                                width: urlTag.implicitWidth + 10; height: 14; radius: 3
                                color: "transparent"; border.width: 1; border.color: Token.color_ui_okLine
                                Text { id: urlTag; anchors.centerIn: parent; text: "Custom URL"
                                       font.pixelSize: 10; color: Token.color_status_ok }
                            }
                        }
                        Rectangle {
                            visible: card.selected
                            anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                            width: activeTag.implicitWidth + 12; height: 16; radius: 4
                            color: Token.color_accent_primary
                            Text { id: activeTag; anchors.centerIn: parent; text: "Active"
                                   font.pixelSize: 10
                                   font.weight: Font.DemiBold; color: Token.color_ui_text }
                        }
                    }
                    Row {
                        visible: card.urlEditable
                        width: parent.width
                        spacing: 6
                        TextField {
                            id: urlInput
                            width: parent.width - setBtn.width - (clearBtn.visible ? clearBtn.width + 6 : 0) - 6
                            height: 28
                            selectByMouse: true
                            color: Token.color_ui_text
                            font.pixelSize: 11
                            placeholderText: card.customUrl !== "" ? card.customUrl
                                           : (card.mode === "rtsp" ? "rtsp://user:pass@host:554/stream" : "http://host:8080/video")
                            placeholderTextColor: Token.color_text_muted
                            leftPadding: 8
                            background: Rectangle {
                                radius: 7; color: Token.color_ui_fill
                                border.width: urlInput.activeFocus ? 2 : 0
                                border.color: Qt.alpha(Token.color_accent_primary, 0.8)
                            }
                            function commit() {
                                var v = text.trim()
                                if (v === "") return
                                Video.setCustomUrl(card.mode, v)
                                root.showFeedback(card.mode.toUpperCase() + " URL set · saved", true)
                                text = ""
                            }
                            Keys.onReturnPressed: commit()
                        }
                        TextButton { id: setBtn; label: "Set"; tone: "primary"; height: 28; onClicked: urlInput.commit() }
                        TextButton {
                            id: clearBtn; visible: card.customUrl !== ""; label: "Clear"; tone: "danger"; height: 28
                            onClicked: { Video.setCustomUrl(card.mode, ""); root.showFeedback(card.mode.toUpperCase() + " URL cleared", true) }
                        }
                    }
                }
                HoverHandler { id: cardHover }
                TapHandler {
                    gesturePolicy: TapHandler.ReleaseWithinBounds
                    onTapped: {
                        Video.setMode(card.mode)
                        root.showFeedback("source → " + card.modelData.label + " · saved for startup", true)
                    }
                }
            }
        }

        Rectangle {                                          // feedback strip
            visible: root.feedbackMsg !== ""
            width: parent.width; height: 26; radius: 7
            color: root.feedbackOk ? Token.color_ui_okSoft : Token.color_ui_dangerSoft
            border.width: 1
            border.color: root.feedbackOk ? Token.color_ui_okLine : Token.color_ui_dangerLine
            Text {
                anchors.centerIn: parent
                width: parent.width - 16
                horizontalAlignment: Text.AlignHCenter
                elide: Text.ElideRight
                text: root.feedbackMsg
                font.pixelSize: 11
                color: root.feedbackOk ? Token.color_status_ok : "#FF6961"
            }
        }
    }
}
