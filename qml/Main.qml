import QtQuick
import QtQuick.Controls
import "components"
import "views"

// Shell: full-window flight HUD with overlays — TopBar, expanded Map, Mission
// Planner, VideoSource drawer and the notice stack. QML is presentation-only;
// state arrives through context properties (Telemetry, Vehicle, Mission, Video,
// MapBridge).
//
// View switching is done with SIGNALS from the views up to this window. The old
// code reached for `Window.window.viewMode` inside TapHandler handlers, where
// the attached property is null (a handler is not an Item), so the map button,
// the planner Close button and the map collapse button did nothing.
ApplicationWindow {
    id: root
    width: 1600
    height: 950
    minimumWidth: 1120
    minimumHeight: 700
    visible: true
    title: qsTr("Ghost Controller")
    color: Token.color_hud_videoBg

    // "flight" | "map" | "planner"
    property string viewMode: "flight"
    property bool videoOpen: false

    function setView(v) { viewMode = v }

    Shortcut { sequence: "Escape"; onActivated: if (root.viewMode !== "flight") root.setView("flight") }

    // ---- flight HUD (always mounted: it owns the live video) ----------------------
    FlightView {
        anchors.fill: parent
        visible: root.viewMode === "flight"
        onOpenMap: root.setView("map")
    }

    // ---- expanded map / planner: created on demand, destroyed on close ---------------
    Loader {
        id: mapLoader
        anchors.fill: parent
        active: root.viewMode === "map"
        source: "views/MapScreen.qml"
    }
    Connections {
        target: mapLoader.item
        function onCloseRequested() { root.setView("flight") }
    }

    Loader {
        id: plannerLoader
        anchors.fill: parent
        active: root.viewMode === "planner"
        source: "views/MissionPlanner.qml"
        z: 25                                    // above the app TopBar (z:20)
    }
    Connections {
        target: plannerLoader.item
        function onCloseRequested() { root.setView("flight") }
    }

    // ---- persistent chrome: the planner has its own bar, so hide this one there -----
    TopBar {
        id: topBar
        anchors { top: parent.top; left: parent.left; right: parent.right }
        height: Token.dimension_hud_topBarHeight
        visible: root.viewMode !== "planner"
        z: 20
        onOpenPlanner: root.setView("planner")
        onOpenVideo: root.videoOpen = true
        onOpenParams: { paramsWindow.show(); paramsWindow.raise(); paramsWindow.requestActivate() }
        onOpenLink: linkDialog.open()
    }

    // ---- settings: CONNECTION dialog + PARAMETERS window ------------------------------------
    LinkDialog { id: linkDialog }
    ParamsWindow {
        id: paramsWindow
        visible: false
        onOpenConnection: linkDialog.open()
    }

    VideoSourcePanel {
        open: root.videoOpen && root.viewMode !== "planner"
        anchors { right: parent.right; bottom: parent.bottom; rightMargin: 12 + Token.dimension_hud_tapeWidth; bottomMargin: 56 }
        z: 30
        onCloseRequested: root.videoOpen = false
    }

    // ---- notices: alerts + command feedback ---------------------------------------------
    Column {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.top: parent.top
        anchors.topMargin: root.viewMode === "planner" ? 58 : 60
        spacing: 8
        z: 100
        AlertBanner { anchors.horizontalCenter: parent.horizontalCenter }
        ActionToast { anchors.horizontalCenter: parent.horizontalCenter }
    }
}
