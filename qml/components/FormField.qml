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
    spacing: 6
    Text {
        text: fld.title
        font.pixelSize: Token.typography_size_sm; font.weight: Font.Medium
        color: Token.color_ui_textDim
    }
    TextField {
        id: input
        width: fld.fieldWidth; height: 32
        color: Token.color_ui_text
        placeholderTextColor: Token.color_text_disabled
        selectionColor: Token.color_accent_primary
        selectByMouse: true
        font.pixelSize: Token.typography_size_md
        leftPadding: 10
        onAccepted: fld.accepted()
        background: Rectangle {
            radius: Token.dimension_radius_sm + 1; color: Token.color_ui_fill
            border.width: input.activeFocus ? 2 : 0
            border.color: Qt.alpha(Token.color_accent_primary, 0.8)
        }
    }
}
