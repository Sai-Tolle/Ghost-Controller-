import QtQuick
import QtQuick.Layouts
import "../components"

// Slippy-map engine (offline tiles / grid fallback) with mission overlays.
// Pure presentation + pan/zoom; planning interactions are exposed as signals
// and driven by MissionPlanner. Vehicle track/position come from Telemetry.
GlassPanel {
    id: mapPanel
    objectName: "mapView"
    accentBorder: false
    radius: 0
    color: "#0B0F16"
    border.width: 0

    // ---- API ---------------------------------------------------------------
    property bool plannerMode: false          // render mission plan + fence
    property bool addWaypointArmed: false     // next map click adds a waypoint
    property bool addFenceArmed: false        // next map click adds a fence point
    property bool deleteArmed: false          // next marker click deletes it
    signal mapClicked(real lat, real lon)
    signal waypointClicked(int seq)
    signal fencePointClicked(int index)

    // ---- view state ------------------------------------------------------
    property real centerLat: Mission.home[0]      // start on HOME, not a hard-coded Zurich
    property real centerLon: Mission.home[1]
    // Start inside the tile source's zoom range so offline tiles show at boot.
    property int zoom: 13
    property var track: Telemetry.positionTrack
    property bool hasVehicle: typeof Telemetry.telemetry.lat === "number"
                              && typeof Telemetry.telemetry.lon === "number"
    property bool followVehicle: true
    property bool markerDragging: false        // a waypoint/fence drag must not pan the map
    property string _tileRangeKey: ""

    // ---- slippy math (fractional tile units) ------------------------------
    function lngToTileX(lng, z) { return (lng + 180.0) / 360.0 * Math.pow(2, z) }
    function latToTileY(lat, z) {
        var latRad = Math.max(-85.05112878, Math.min(85.05112878, lat)) * Math.PI / 180
        return (1 - Math.log(Math.tan(latRad) + 1 / Math.cos(latRad)) / Math.PI) / 2 * Math.pow(2, z)
    }
    function tileXToLng(x, z) { return x / Math.pow(2, z) * 360.0 - 180.0 }
    function tileYToLat(y, z) {
        var n = Math.PI - 2 * Math.PI * y / Math.pow(2, z)
        return 180 / Math.PI * Math.atan(0.5 * (Math.exp(n) - Math.exp(-n)))
    }
    function clampZoom(z) {
        return Math.max(MapBridge.minZoom(), Math.min(MapBridge.maxZoom(), z))
    }

    // lat/lon → screen px
    function toScreen(lat, lon) {
        var originX = width / 2 - lngToTileX(centerLon, zoom) * 256
        var originY = height / 2 - latToTileY(centerLat, zoom) * 256
        return {
            x: lngToTileX(lon, zoom) * 256 + originX,
            y: latToTileY(lat, zoom) * 256 + originY
        }
    }
    function toLatLon(x, y) {
        var originX = width / 2 - lngToTileX(centerLon, zoom) * 256
        var originY = height / 2 - latToTileY(centerLat, zoom) * 256
        return {
            lat: tileYToLat((y - originY) / 256, zoom),
            lon: tileXToLng((x - originX) / 256, zoom)
        }
    }

    function markerNear(px, py) {
        var wps = Mission.waypoints
        for (var i = 0; i < wps.length; i++) {
            var p = toScreen(wps[i].lat, wps[i].lon)
            if (Math.abs(p.x - px) < 16 && Math.abs(p.y - py) < 16) return true
        }
        var fp = Mission.fencePoints
        for (var j = 0; j < fp.length; j++) {
            var q = toScreen(fp[j][0], fp[j][1])
            if (Math.abs(q.x - px) < 12 && Math.abs(q.y - py) < 12) return true
        }
        return false
    }

    function pad3(n) {
        var s = "" + Math.round(n)
        while (s.length < 3) s = "0" + s
        return s
    }

    // ---- world-anchored tile layer ----------------------------------------------
    // Each tile shows, bottom to top: coarser cached tiles scaled up (zoom-in) or
    // finer cached tiles scaled down (zoom-out) as an instant placeholder, then the
    // sharp tile itself. Zooming therefore never goes blank, and sharp tiles pop in
    // as the parallel downloads finish (MapBridge.tileReady).
    property int retryGen: 0          // bumped when the network comes back (retries misses)
    property int ghostGen: 0          // bumped per zoom (cache-buster for placeholder URLs)
    property string ghostMode: "parent"
    property int _lastZoom: -1
    property var _tiles: ({})         // "z/x/y" -> delegate, for tileReady dispatch

    ListModel { id: tileModel }
    ListModel { id: oldModel }          // snapshot of the previous zoom's tiles, kept while the new ones load
    Timer { id: oldTimer; interval: 900; onTriggered: { oldWorld.visible = false; oldModel.clear() } }

    Connections {
        target: MapBridge
        function onTileReady(z, x, y) {
            var t = mapPanel._tiles[z + "/" + x + "/" + y]
            if (t) t.ver++
        }
        function onOnlineChanged() { if (MapBridge.online) mapPanel.retryGen++ }
    }

    Item {
        id: worldItem
        z: 0
        Item {                                       // previous zoom, scaled onto the new one
            id: oldWorld
            visible: false
            transformOrigin: Item.TopLeft
            Repeater {
                model: oldModel
                delegate: Image {
                    required property int tx
                    required property int ty
                    required property int tz
                    required property int ver
                    x: tx * 256; y: ty * 256; width: 256; height: 256
                    // identical URL to the tile as it was shown -> served from QML's pixmap
                    // cache instantly (no async gap, no flash)
                    source: { ver; return MapBridge.tileUrl(tz, tx, ty, false) }
                }
            }
        }
        Repeater {
            id: tilesRepeater
            model: tileModel
            delegate: Item {
                id: tile
                required property int tx
                required property int ty
                required property int tz
                property int ver: 0
                x: tx * 256; y: ty * 256
                width: 256; height: 256

                Image {                                   // z-2 placeholder
                    visible: tile.tz >= 2
                    width: 256; height: 256
                    asynchronous: true; fillMode: Image.Stretch
                    source: { mapPanel.ghostGen; return tile.tz >= 2 ? MapBridge.tileUrl(tile.tz - 2, tile.tx >> 2, tile.ty >> 2, false) : "" }
                    sourceClipRect: Qt.rect((tile.tx & 3) * 64, (tile.ty & 3) * 64, 64, 64)
                }
                Image {                                   // z-1 placeholder
                    visible: tile.tz >= 1
                    width: 256; height: 256
                    asynchronous: true; fillMode: Image.Stretch
                    source: { mapPanel.ghostGen; return tile.tz >= 1 ? MapBridge.tileUrl(tile.tz - 1, tile.tx >> 1, tile.ty >> 1, false) : "" }
                    sourceClipRect: Qt.rect((tile.tx & 1) * 128, (tile.ty & 1) * 128, 128, 128)
                }
                Repeater {                                // z+1 placeholders (after zooming OUT)
                    model: mapPanel.ghostMode === "children" ? 4 : 0
                    delegate: Image {
                        required property int index
                        x: (index & 1) * 128; y: (index >> 1) * 128
                        width: 128; height: 128
                        asynchronous: true; fillMode: Image.Stretch
                        source: { mapPanel.ghostGen; return MapBridge.tileUrl(tile.tz + 1, tile.tx * 2 + (index & 1), tile.ty * 2 + (index >> 1), false) }
                    }
                }
                Image {                                   // the sharp tile
                    width: 256; height: 256
                    asynchronous: true
                    // file:// URL from Qt's own loader thread (no Python there: see mapbridge.py)
                    source: { tile.ver; mapPanel.retryGen; return MapBridge.tileUrl(tile.tz, tile.tx, tile.ty, true) }
                }
                Component.onCompleted: {
                    mapPanel._tiles[tz + "/" + tx + "/" + ty] = tile
                    // closes the tiny race where the download finished between the
                    // provider's miss and this registration
                    if (MapBridge.hasTile(tz, tx, ty)) tile.ver++
                }
                Component.onDestruction: {
                    var k = tz + "/" + tx + "/" + ty
                    if (mapPanel._tiles[k] === tile) delete mapPanel._tiles[k]
                }
            }
        }
    }

    Canvas {
        id: grid
        anchors.fill: parent
        z: -1
        visible: MapBridge.fallbackGrid
        onPaint: {
            var ctx = getContext("2d")
            ctx.reset()
            ctx.strokeStyle = Qt.rgba(0.55, 0.65, 0.8, Token.opacity_grid)
            ctx.lineWidth = 1
            var step = 44
            for (var x = 0; x <= width; x += step) {
                ctx.beginPath(); ctx.moveTo(x + 0.5, 0); ctx.lineTo(x + 0.5, height); ctx.stroke()
            }
            for (var y = 0; y <= height; y += step) {
                ctx.beginPath(); ctx.moveTo(0, y + 0.5); ctx.lineTo(width, y + 0.5); ctx.stroke()
            }
        }
        onWidthChanged: requestPaint()
        onHeightChanged: requestPaint()
    }

    // ---- track + planned path + fence --------------------------------------
    Canvas {
        id: linesCanvas
        anchors.fill: parent
        z: 1

        function repaintAll() { requestPaint() }
        onPaint: {
            var ctx = getContext("2d")
            ctx.reset()

            // flown track (solid salmon, reference map view)
            if (mapPanel.track.length >= 2) {
                ctx.strokeStyle = Token.color_mission_flown.toString()
                ctx.lineWidth = 3
                ctx.globalAlpha = 0.9
                ctx.beginPath()
                for (var i = 0; i < mapPanel.track.length; i++) {
                    var px = toScreen(mapPanel.track[i][0], mapPanel.track[i][1])
                    if (px.x < -60 || px.x > width + 60 || px.y < -60 || px.y > height + 60)
                        continue
                    if (i === 0) ctx.moveTo(px.x, px.y); else ctx.lineTo(px.x, px.y)
                }
                ctx.stroke()
                ctx.globalAlpha = 1.0
            }

            // planned path (dashed blue, reference mission view)
            var wps = Mission.waypoints
            if (wps.length >= 2) {
                ctx.strokeStyle = Token.color_mission_planned.toString()
                ctx.lineWidth = 2.5
                ctx.setLineDash([6, 6])
                ctx.beginPath()
                for (var w = 0; w < wps.length; w++) {
                    var p = toScreen(wps[w].lat, wps[w].lon)
                    if (w === 0) ctx.moveTo(p.x, p.y); else ctx.lineTo(p.x, p.y)
                }
                ctx.stroke()
                ctx.setLineDash([])
            }

            // active live orbit ring [lat, lon, radius_m]
            var ot = Mission.orbitTarget
            if (ot.length === 3) {
                var oc = toScreen(ot[0], ot[1])
                var mpp = 156543.03392 * Math.cos(ot[0] * Math.PI / 180) / Math.pow(2, mapPanel.zoom)
                ctx.strokeStyle = Token.color_mission_orbit.toString()
                ctx.lineWidth = 2
                ctx.setLineDash([])
                ctx.beginPath(); ctx.arc(oc.x, oc.y, Math.max(4, ot[2] / mpp), 0, Math.PI * 2); ctx.stroke()
            }

            // geofence (dashed cyan polygon)
            var fence = Mission.fencePoints
            if (fence.length >= 3) {
                ctx.strokeStyle = Token.color_mission_fence.toString()
                ctx.lineWidth = 2
                ctx.setLineDash([8, 6])
                ctx.beginPath()
                for (var f = 0; f <= fence.length; f++) {
                    var fp = toScreen(fence[f % fence.length][0], fence[f % fence.length][1])
                    if (f === 0) ctx.moveTo(fp.x, fp.y); else ctx.lineTo(fp.x, fp.y)
                }
                ctx.stroke()
                ctx.setLineDash([])
            }
        }
        Connections {
            target: Telemetry
            function onPositionTrackChanged() { linesCanvas.repaintAll() }
        }
        Connections {
            target: Mission
            function onWaypointsChanged() { linesCanvas.repaintAll() }
            function onFenceChanged() { linesCanvas.repaintAll() }
            function onHomeChanged() { linesCanvas.repaintAll() }
            function onOrbitTargetChanged() { linesCanvas.repaintAll() }
        }
        Connections {
            target: mapPanel
            function onCenterLatChanged() { linesCanvas.repaintAll() }
            function onCenterLonChanged() { linesCanvas.repaintAll() }
            function onZoomChanged() { linesCanvas.repaintAll() }
        }
    }

    // ---- home marker (H) -------------------------------------------------------
    Rectangle {
        z: 2
        width: 22; height: 22; radius: 4
        color: Qt.alpha(Token.color_base_bg, 0.85)
        border.width: 1.5
        border.color: Token.color_text_primary
        x: mapPanel.toScreen(Mission.home[0], Mission.home[1]).x - width / 2
        y: mapPanel.toScreen(Mission.home[0], Mission.home[1]).y - height / 2
        Text {
            anchors.centerIn: parent
            text: "H"
            font.family: Token.typography_familyMono
            font.pixelSize: Token.typography_size_sm
            font.weight: Token.typography_weight_bold
            color: Token.color_text_primary
        }
    }

    // ---- mission waypoint markers (planner) --------------------------------------
    Repeater {
        id: wpRepeater
        model: Mission.waypoints

        delegate: Rectangle {
            id: wpMarker
            required property var modelData
            required property int index
            readonly property bool selected: index === Mission.selectedIndex
            z: 3                       // Repeater.z does not reach delegates; the canvas (z:1) drew over markers
            width: 24; height: 24; radius: 12
            color: modelData.command === "TAKEOFF" ? Token.color_mission_home
                 : modelData.command === "LAND" ? Token.color_status_danger
                 : Token.color_status_info
            border.width: selected ? 2.5 : 1.5
            border.color: selected ? "#FFFFFF" : Qt.alpha(Token.color_base_bg, 0.9)
            x: mapPanel.toScreen(modelData.lat, modelData.lon).x - width / 2
            y: mapPanel.toScreen(modelData.lat, modelData.lon).y - height / 2

            Text {
                anchors.centerIn: parent
                text: index + 1
                font.family: Token.typography_familyMono
                font.pixelSize: Token.typography_size_xs
                font.weight: Token.typography_weight_bold
                color: "#0B1016"
            }

            DragHandler {
                target: null
                enabled: mapPanel.plannerMode
                onActiveChanged: mapPanel.markerDragging = active
                onTranslationChanged: function(delta) {
                    if (mapPanel.deleteArmed) return
                    var ll = mapPanel.toLatLon(wpMarker.x + delta.x + wpMarker.width / 2,
                                               wpMarker.y + delta.y + wpMarker.height / 2)
                    Mission.moveWaypoint(wpMarker.index, ll.lat, ll.lon)
                    linesCanvas.repaintAll()
                }
            }
            TapHandler {
                enabled: mapPanel.plannerMode && mapPanel.deleteArmed
                onTapped: Mission.deleteWaypoint(wpMarker.index)
            }
            // selection: non-delete clicks select; when delete armed, marker tap deletes
            TapHandler {
                enabled: mapPanel.plannerMode && !mapPanel.deleteArmed
                gesturePolicy: TapHandler.ReleaseWithinBounds
                onTapped: Mission.selectWaypoint(wpMarker.index)
            }
        }
    }

    // ---- fence point markers (planner) ---------------------------------------------
    Repeater {
        model: Mission.fencePoints

        delegate: Rectangle {
            id: fenceMarker
            required property var modelData
            required property int index
            z: 3
            width: 14; height: 14; radius: 7
            color: "transparent"
            border.width: 2
            border.color: Token.color_mission_fence
            x: mapPanel.toScreen(modelData[0], modelData[1]).x - width / 2
            y: mapPanel.toScreen(modelData[0], modelData[1]).y - height / 2

            DragHandler {
                target: null
                enabled: mapPanel.plannerMode
                onActiveChanged: mapPanel.markerDragging = active
                onTranslationChanged: function(delta) {
                    var ll = mapPanel.toLatLon(fenceMarker.x + delta.x + fenceMarker.width / 2,
                                               fenceMarker.y + delta.y + fenceMarker.height / 2)
                    Mission.moveFencePoint(fenceMarker.index, ll.lat, ll.lon)
                    linesCanvas.repaintAll()
                }
            }
            TapHandler {
                enabled: mapPanel.plannerMode
                onTapped: {
                    if (mapPanel.deleteArmed) Mission.deleteFencePoint(fenceMarker.index)
                    else mapPanel.fencePointClicked(fenceMarker.index)
                }
            }
        }
    }

    // ---- vehicle marker ----------------------------------------------------
    // World-anchored: positioned at the vehicle's lat/lon via toScreen()
    // (same pattern as home/waypoint markers). anchors.centerIn (previous
    // behavior) glued it to the view center, so panning dragged the marker
    // — and follow-mode re-centering fought the operator.
    Item {
        id: vehicleMarker
        z: 4
        width: 30; height: 30
        rotation: Telemetry.telemetry.heading
        visible: mapPanel.hasVehicle
        x: mapPanel.toScreen(Telemetry.telemetry.lat, Telemetry.telemetry.lon).x - width / 2
        y: mapPanel.toScreen(Telemetry.telemetry.lat, Telemetry.telemetry.lon).y - height / 2

        Canvas {
            anchors.fill: parent
            onPaint: {
                var ctx = getContext("2d")
                ctx.reset()
                ctx.fillStyle = Token.color_status_info.toString()
                ctx.beginPath()
                ctx.moveTo(15, 2)
                ctx.lineTo(26, 27)
                ctx.lineTo(15, 21)
                ctx.lineTo(4, 27)
                ctx.closePath()
                ctx.fill()
            }
        }
    }

    // ---- interaction: wheel zoom + drag pan --------------------------------
    WheelHandler {
        acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
        onWheel: function(wheel) {
            var nz = mapPanel.clampZoom(mapPanel.zoom + (wheel.angleDelta.y > 0 ? 1 : -1))
            if (nz === mapPanel.zoom) return
            if (!mapPanel.followVehicle) {
                // keep the point under the cursor fixed while zooming
                var ll = mapPanel.toLatLon(wheel.x, wheel.y)
                mapPanel.zoom = nz
                mapPanel.centerLon = mapPanel.tileXToLng(mapPanel.lngToTileX(ll.lon, nz) - (wheel.x - mapPanel.width / 2) / 256, nz)
                mapPanel.centerLat = mapPanel.tileYToLat(mapPanel.latToTileY(ll.lat, nz) - (wheel.y - mapPanel.height / 2) / 256, nz)
            } else {
                mapPanel.zoom = nz
            }
            mapPanel.updateWorld()
        }
    }

    DragHandler {
        id: panDrag
        target: null
        enabled: !mapPanel.markerDragging
        onTranslationChanged: function(delta) {
            mapPanel.panBy(delta.x, delta.y)
        }
    }

    TapHandler {
        id: mapTap
        gesturePolicy: TapHandler.ReleaseWithinBounds
        onTapped: function(eventPoint) {
            if (mapPanel.markerNear(eventPoint.position.x, eventPoint.position.y)) return
            var ll = mapPanel.toLatLon(eventPoint.position.x, eventPoint.position.y)
            if (mapPanel.plannerMode && mapPanel.addWaypointArmed) {
                Mission.addWaypointAt(ll.lat, ll.lon)
            } else if (mapPanel.plannerMode && mapPanel.addFenceArmed) {
                Mission.addFencePointAt(ll.lat, ll.lon)
            } else {
                mapPanel.mapClicked(ll.lat, ll.lon)
            }
        }
        onDoubleTapped: mapPanel.followVehicle = true
    }

    // ---- follow vehicle -----------------------------------------------------
    Connections {
        target: Telemetry
        function onTelemetryChanged() {
            var lat = Telemetry.telemetry.lat
            var lon = Telemetry.telemetry.lon
            if (mapPanel.followVehicle && typeof lat === "number" && typeof lon === "number") {
                mapPanel.centerLat = lat
                mapPanel.centerLon = lon
                mapPanel.updateWorld()
            }
        }
    }

    // ---- tiling engine ------------------------------------------------------
    function panBy(dx, dy) {
        followVehicle = false
        var cx = lngToTileX(centerLon, zoom) * 256 - dx
        var cy = latToTileY(centerLat, zoom) * 256 - dy
        centerLon = tileXToLng(cx / 256, zoom)
        centerLat = tileYToLat(cy / 256, zoom)
        updateWorld()
    }

    function tileRange(z, margin) {
        var cx = lngToTileX(centerLon, z) * 256
        var cy = latToTileY(centerLat, z) * 256
        var n = Math.pow(2, z)
        return {
            x0: Math.max(0, Math.floor((cx - width / 2) / 256) - margin),
            x1: Math.min(n - 1, Math.floor((cx + width / 2) / 256) + margin),
            y0: Math.max(0, Math.floor((cy - height / 2) / 256) - margin),
            y1: Math.min(n - 1, Math.floor((cy + height / 2) / 256) + margin)
        }
    }

    // Keep the model in step with the viewport by ADDING/REMOVING only the tiles that
    // changed (the old code reassigned the whole array, destroying and reloading every
    // delegate whenever the visible range moved).
    function syncTiles(r) {
        var want = {}
        for (var tx = r.x0; tx <= r.x1; tx++)
            for (var ty = r.y0; ty <= r.y1; ty++) want[tx + "_" + ty] = true
        for (var i = tileModel.count - 1; i >= 0; i--) {
            var t = tileModel.get(i)
            if (t.tz !== zoom || !want[t.tx + "_" + t.ty]) tileModel.remove(i)
        }
        var have = {}
        for (var j = 0; j < tileModel.count; j++) {
            var u = tileModel.get(j); have[u.tx + "_" + u.ty] = true
        }
        for (var x = r.x0; x <= r.x1; x++)
            for (var y = r.y0; y <= r.y1; y++)
                if (!have[x + "_" + y]) tileModel.append({ tx: x, ty: y, tz: zoom })
    }

    function updateWorld() {
        worldItem.x = width / 2 - lngToTileX(centerLon, zoom) * 256
        worldItem.y = height / 2 - latToTileY(centerLat, zoom) * 256
        var r = tileRange(zoom, 0)
        var key = zoom + ":" + r.x0 + ".." + r.x1 + ":" + r.y0 + ".." + r.y1
        if (key !== _tileRangeKey) {
            _tileRangeKey = key
            if (zoom !== _lastZoom) {
                if (_lastZoom >= 0 && tileModel.count > 0) {
                    oldModel.clear()
                    for (var k = 0; k < tileModel.count; k++) {
                        var ot = tileModel.get(k)
                        var live = _tiles[ot.tz + "/" + ot.tx + "/" + ot.ty]
                        oldModel.append({ tx: ot.tx, ty: ot.ty, tz: ot.tz, ver: live ? live.ver : 0 })
                    }
                    oldWorld.scale = Math.pow(2, zoom - _lastZoom)
                    oldWorld.visible = true
                    oldTimer.restart()
                }
                ghostMode = (_lastZoom > zoom) ? "children" : "parent"
                ghostGen++
                _lastZoom = zoom
            }
            // 1) start downloading the WHOLE viewport (+1 ring) in parallel, 2) warm the
            //    zoom levels the user is likely to scroll to next, so the next wheel step
            //    is instant, 3) only then build/refresh delegates.
            var ring = tileRange(zoom, 1)
            MapBridge.prefetch(zoom, ring.x0, ring.x1, ring.y0, ring.y1)
            // neighbour zooms only use idle download slots (never delay on-screen tiles)
            var fresh = true
            if (zoom < MapBridge.maxZoom()) { var up = tileRange(zoom + 1, 0); MapBridge.prefetchLow(zoom + 1, up.x0, up.x1, up.y0, up.y1, fresh); fresh = false }
            if (zoom > MapBridge.minZoom()) { var dn = tileRange(zoom - 1, 0); MapBridge.prefetchLow(zoom - 1, dn.x0, dn.x1, dn.y0, dn.y1, fresh) }
            syncTiles(r)
        }
        linesCanvas.repaintAll()
    }

    onWidthChanged: updateWorld()
    onHeightChanged: updateWorld()

    Component.onCompleted: {
        zoom = clampZoom(zoom)  // land inside the offline source's zoom range
        updateWorld()
    }

    // ---- compass (bottom centre) ---------------------------------------------------------
    Compass {
        width: 92; height: 92
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 40
        z: 5
        heading: Telemetry.telemetry.heading
    }

    // ---- re-centre on vehicle (shown once the operator has panned away) -----------------
    Rectangle {
        visible: !mapPanel.followVehicle && mapPanel.hasVehicle
        anchors.left: parent.left; anchors.leftMargin: 16
        anchors.bottom: parent.bottom; anchors.bottomMargin: 64
        z: 5
        width: recText.implicitWidth + 24; height: 32; radius: 8
        color: Token.color_ui_glassStrong
        border.width: 1
        border.color: Token.color_ui_accentLine
        Text { id: recText; anchors.centerIn: parent; text: "◎  FOLLOW VEHICLE"
               font.family: Token.typography_familyMono; font.pixelSize: 10; font.letterSpacing: 1.2
               color: Token.color_accent_primary }
        HoverHandler { cursorShape: Qt.PointingHandCursor }
        TapHandler { gesturePolicy: TapHandler.ReleaseWithinBounds
                     onTapped: { mapPanel.followVehicle = true; mapPanel.updateWorld() } }
    }
}
