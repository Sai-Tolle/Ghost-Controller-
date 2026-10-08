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
    radius: 14
    color: Token.color_ui_glassStrong
    border.width: 1
    border.color: Token.color_ui_lineStrong
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
                    Canvas {
                        anchors.centerIn: parent; width: 16; height: 14
                        onPaint: {
                            var c = getContext("2d"); c.reset()
                            c.strokeStyle = "#A9D2FF"; c.lineWidth = 1.6; c.lineJoin = "round"
                            c.strokeRect(1, 2, 9, 9)
                            c.beginPath(); c.moveTo(10, 5); c.lineTo(15, 2.5); c.lineTo(15, 10.5); c.lineTo(10, 8); c.stroke()
                        }
                    }
                }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: "VIDEO SOURCE"
                    font.family: Token.typography_familyMono
                    font.pixelSize: 12; font.weight: Font.Bold; font.letterSpacing: 2
                    color: Token.color_ui_text
                }
            }
            Text {
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                text: "✕"
                font.pixelSize: 14
                color: closeHover.hovered ? "#FFFFFF" : Token.color_ui_textDim
                HoverHandler { id: closeHover; cursorShape: Qt.PointingHandCursor }
                TapHandler { onTapped: root.closeRequested() }
            }
        }

        Rectangle {                                        // detected stream
            id: det
            width: parent.width; height: 52; radius: 9
            readonly property bool live: Video.state === "live"
            color: live ? Token.color_ui_okSoft : Qt.rgba(1, 1, 1, 0.04)
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
                        text: det.live ? "DETECTED" : "NO SOURCE DETECTED"
                        font.family: Token.typography_familyMono
                        font.pixelSize: 9; font.letterSpacing: 1.4; font.weight: Font.DemiBold
                        color: det.live ? Token.color_status_ok : Token.color_ui_textDim
                    }
                }
                Text {
                    text: Video.state === "live"
                          ? Video.sourceLabel.toUpperCase() + (Video.resolution !== "" ? "  ·  " + Video.resolution : "") + "  ·  " + Video.fps.toFixed(0) + " fps"
                          : Video.label
                    elide: Text.ElideRight
                    width: 260
                    font.family: Token.typography_familyMono
                    font.pixelSize: 11; font.weight: Font.Bold
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
                color: selected ? Token.color_ui_accentSoft : Qt.rgba(1, 1, 1, cardHover.hovered ? 0.06 : 0.03)
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
                                font.family: Token.typography_familyMono
                                font.pixelSize: 11; font.weight: Font.Bold; font.letterSpacing: 1.6
                                color: card.selected ? Token.color_accent_primary : Token.color_ui_text
                            }
                            Rectangle {
                                visible: card.customUrl !== ""
                                anchors.verticalCenter: parent.verticalCenter
                                width: urlTag.implicitWidth + 10; height: 14; radius: 3
                                color: "transparent"; border.width: 1; border.color: Token.color_ui_okLine
                                Text { id: urlTag; anchors.centerIn: parent; text: "CUSTOM URL"
                                       font.family: Token.typography_familyMono; font.pixelSize: 8; color: Token.color_status_ok }
                            }
                        }
                        Rectangle {
                            visible: card.selected
                            anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
                            width: 7; height: 7; radius: 3.5; color: Token.color_accent_primary
                        }
                    }
                    Text {
                        width: parent.width
                        text: card.modelData.hint
                        wrapMode: Text.WordWrap
                        font.family: Token.typography_familyMono
                        font.pixelSize: 9
                        color: Token.color_ui_textDim
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
                            font.family: Token.typography_familyMono
                            font.pixelSize: 10
                            placeholderText: card.customUrl !== "" ? card.customUrl
                                           : (card.mode === "rtsp" ? "rtsp://user:pass@host:554/stream" : "http://host:8080/video")
                            placeholderTextColor: Token.color_text_muted
                            leftPadding: 8
                            background: Rectangle {
                                radius: 6; color: Qt.rgba(0, 0, 0, 0.25)
                                border.width: 1
                                border.color: urlInput.activeFocus ? Token.color_accent_primary : Token.color_ui_line
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
                        TextButton { id: setBtn; label: "SET"; tone: "primary"; height: 28; onClicked: urlInput.commit() }
                        TextButton {
                            id: clearBtn; visible: card.customUrl !== ""; label: "✕"; tone: "danger"; height: 28
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
                font.family: Token.typography_familyMono
                font.pixelSize: 9; font.letterSpacing: 0.8
                color: root.feedbackOk ? Token.color_status_ok : "#FF8A8A"
            }
        }
    }
}
