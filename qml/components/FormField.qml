import QtQuick
import QtQuick.Controls

// Labelled single-line input used by the settings dialogs.
Column {
    id: fld
    property string title: ""
    property alias text: input.text
    property alias field: input
    property alias placeholder: input.placeholderText
    property real fieldWidth: 120
    signal accepted()
    spacing: 4
    Text {
        text: fld.title
        font.family: Token.typography_familyMono; font.pixelSize: 9
        font.letterSpacing: 1.2; color: Token.color_ui_textDim
    }
    TextField {
        id: input
        width: fld.fieldWidth; height: 30
        color: Token.color_ui_text
        placeholderTextColor: Token.color_text_disabled
        selectByMouse: true
        font.family: Token.typography_familyMono; font.pixelSize: 12
        leftPadding: 9
        onAccepted: fld.accepted()
        background: Rectangle {
            radius: 6; color: Qt.rgba(1, 1, 1, 0.05)
            border.width: 1
            border.color: input.activeFocus ? Token.color_accent_primary : Token.color_ui_line
        }
    }
}
