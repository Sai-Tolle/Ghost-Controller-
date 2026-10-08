import QtQuick
import QtQuick.Controls

// Numeric input with a small uppercase label (survey / orbit panels).
Column {
    id: root
    property string title: ""
    property alias value: input.text
    property alias field: input
    signal committed()
    width: parent ? parent.width : 160
    spacing: 4
    Text {
        text: root.title.toUpperCase()
        font.family: Token.typography_familyMono
        font.pixelSize: 9
        font.letterSpacing: 1.2
        color: Token.color_ui_textDim
    }
    TextField {
        id: input
        width: parent.width
        height: 28
        color: Token.color_ui_text
        selectByMouse: true
        font.family: Token.typography_familyMono
        font.pixelSize: 11
        leftPadding: 9
        background: Rectangle {
            radius: 6
            color: Qt.rgba(1, 1, 1, 0.05)
            border.width: 1
            border.color: input.activeFocus ? Token.color_accent_primary : Token.color_ui_line
        }
        onEditingFinished: root.committed()
        validator: DoubleValidator { bottom: -10000; top: 100000; decimals: 2; notation: DoubleValidator.StandardNotation }
    }
}
