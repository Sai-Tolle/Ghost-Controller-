import QtQuick

// Shader-free soft drop shadow: a few stacked translucent rounded rects.
// Put it INSIDE the surface it shadows (z: -1 draws beneath the parent).
// Unlike MultiEffect this renders on every Qt Quick backend, including the
// software renderer used on GPU-less machines, where a shader layer would
// make the whole panel disappear.
Item {
    id: sh
    property real radius: parent ? parent.radius : 0
    property real spread: 14
    property real offsetY: 6
    property real strength: 0.36
    readonly property int steps: 7
    anchors.fill: parent
    anchors.topMargin: offsetY
    anchors.bottomMargin: -offsetY
    z: -1
    Repeater {
        model: sh.steps
        Rectangle {
            required property int index
            readonly property real grow: sh.spread * (index + 1) / sh.steps
            anchors.fill: parent
            anchors.margins: -grow
            radius: sh.radius + grow
            color: Qt.rgba(0, 0, 0, sh.strength / sh.steps)
        }
    }
}
