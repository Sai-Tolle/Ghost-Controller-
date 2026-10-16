import QtQuick
import QtQuick.Controls

// Numeric input with a small label (survey / orbit panels).
Column {
    id: root
    property string title: ""
    property alias value: input.text
    property alias field: input
    signal committed()
    width: parent ? parent.width : 160
    spacing: 5
    Text {
        text: root.title
        font.pixelSize: Token.typography_size_sm
        font.weight: Font.Medium
        color: Token.color_ui_textDim
    }
    TextField {
        id: input
        width: parent.width
        height: 30
        color: Token.color_ui_text
        selectionColor: Token.color_accent_primary
        selectByMouse: true
        font.pixelSize: Token.typography_size_md
        leftPadding: 10
        background: Rectangle {
            radius: Token.dimension_radius_sm + 1
            color: Token.color_ui_fill
            border.width: input.activeFocus ? 2 : 0
            border.color: Qt.alpha(Token.color_accent_primary, 0.8)
        }
        onEditingFinished: root.committed()
        validator: DoubleValidator { bottom: -10000; top: 100000; decimals: 2; notation: DoubleValidator.StandardNotation }
    }
}
