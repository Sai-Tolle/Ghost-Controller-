"""Map bridge: exposes map tile sources + overlays to QML.

Priority order (web MapOverlay SmartTileLayer parity, inverted for native
synchronous painting):
    1. Custom offline image overlay (operator uploaded an image + SW/NE
       bounds — web MapUploadPanel) when the view is inside its bounds.
    2. Offline tile source (maps/ dir, .pmtiles/.mbtiles) when it covers the
       requested tile.
    3. Online OSM (tile.openstreetmap.org) with a disk cache — the web's
       default TileLayer. Network failures degrade gracefully.

QML asks for tiles with MapBridge.tileUrl(z, x, y, fetch) and loads the
returned file:// URL with Qt's own image loader. Tiles used to come from a
Python QQuickImageProvider (image://map); Qt calls that on its pixmap-reader
thread while holding the reader lock, and whenever the GUI thread was running
Python at the same moment (telemetry updates, timers) both threads waited on
each other: the map froze. Now no Python ever runs on Qt's loader thread.
Overlay config persists via QSettings.
"""
from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path

from PySide6.QtCore import QObject, QByteArray, Property, QUrl, Signal, Slot

from app.map import tiles
from app.map.osm import OsmTileFetcher, write_atomic

# zoom above which OSM stops serving meaningful data
_OSM_MAX_ZOOM = 19


class MapController(QObject):
    sourceChanged = Signal()
    availableChanged = Signal()
    overlayChanged = Signal()
    onlineChanged = Signal()
    tileReady = Signal(int, int, int)      # a background download finished (z, x, y)

    def __init__(self) -> None:
        super().__init__()
        self._source = None
        self._source_error = ""
        self._cache: dict[tuple[int, int, int], bytes] = {}
        self._cache_order: list[tuple[int, int, int]] = []
        self._cache_lock = threading.Lock()     # tile_for() runs on image-provider threads
        self._cache_limit = 256  # tiles ≈ up to ~40 MB decoded side is QML's business
        self._offline_dir_cache = None
        self._offline_inflight: set = set()
        self._offline_missing: set = set()

        self._osm = OsmTileFetcher()
        self._osm.set_ready_callback(lambda k: self.tileReady.emit(k[0], k[1], k[2]))

        # Custom image overlay (web MapUploadPanel parity)
        self._overlay_path = ""
        self._overlay_bounds: list[float] | None = None  # [swLat, swLon, neLat, neLon]
        self._overlay_label = ""
        self._load_overlay_config()

        src_path = tiles.autodetect_map_source()
        if src_path:
            src, err = tiles.open_tile_source(src_path)
            if src is not None:
                self._source = src
                print(f"[map] offline tiles: {src.name}")
            else:
                self._source_error = err or "unknown error"
                print(f"[map] no offline tiles: {self._source_error}")

    # ---- image overlay config (web MapUploadPanel parity) -----------------

    def _load_overlay_config(self) -> None:
        from app.bridge.settings import app_settings

        s = app_settings()
        path = str(s.value("map/overlayPath", ""))
        raw = str(s.value("map/overlayBounds", ""))
        label = str(s.value("map/overlayLabel", ""))
        if path:
            from pathlib import Path

            if Path(path).exists():
                self._overlay_path = path
                self._overlay_label = label
                try:
                    self._overlay_bounds = [float(v) for v in json.loads(raw)]
                except (ValueError, TypeError):
                    self._overlay_bounds = None

    @Slot(str, str, str, str, str, str, result=bool)
    def setOverlayImage(self, path: str, swLat: str, swLon: str, neLat: str, neLon: str,
                        label: str) -> bool:  # noqa: N802
        """Set the custom offline map image + geographic bounds (web
        MapUploadPanel SAVE). Empty `path` clears the overlay."""
        from pathlib import Path

        if path.startswith("file:"):
            path = QUrl(path).toLocalFile()        # QML hands us a file URL
        if not path:
            self._overlay_path = ""
            self._overlay_bounds = None
            self._overlay_label = ""
            self._persist_overlay()
            self.sourceChanged.emit()
            self.overlayChanged.emit()
            return True
        try:
            bounds = [float(swLat), float(swLon), float(neLat), float(neLon)]
        except ValueError:
            return False
        if not Path(path).exists():
            return False
        self._overlay_path = path
        self._overlay_bounds = bounds
        self._overlay_label = label or "Custom Map"
        self._persist_overlay()
        self.sourceChanged.emit()
        self.overlayChanged.emit()
        return True

    @Slot(str)
    def setOverlayImageUrl(self, url: str) -> None:  # noqa: N802
        """Called by QML after copying a picked image into the app's data
        location; stores the path for setOverlayImage."""
        self._pending_overlay_url = url

    def _persist_overlay(self) -> None:
        from app.bridge.settings import app_settings

        s = app_settings()
        s.setValue("map/overlayPath", self._overlay_path)
        s.setValue("map/overlayBounds",
                   json.dumps(self._overlay_bounds) if self._overlay_bounds else "")
        s.setValue("map/overlayLabel", self._overlay_label)
        s.sync()

    @Property("QVariantMap", notify=overlayChanged)
    def overlay(self) -> dict:  # noqa: N802
        return self.overlayInfo()

    @Property(bool, notify=overlayChanged)
    def overlayActive(self) -> bool:  # noqa: N802
        return self.hasOverlay()

    @Slot(result="QVariantMap")
    def overlayInfo(self) -> dict:  # noqa: N802
        if not self._overlay_path or not self._overlay_bounds:
            return {}
        return {
            "url": QUrl.fromLocalFile(self._overlay_path).toString(),   # file:///C:/.. on Windows
            "swLat": self._overlay_bounds[0],
            "swLon": self._overlay_bounds[1],
            "neLat": self._overlay_bounds[2],
            "neLon": self._overlay_bounds[3],
            "label": self._overlay_label or "Custom Map",
        }

    @Slot(result=bool)
    def hasOverlay(self) -> bool:  # noqa: N802
        return bool(self._overlay_path and self._overlay_bounds)

    # ---- OSM status ---------------------------------------------------------

    @Slot()
    def retryOnline(self) -> None:  # noqa: N802
        self._osm.clear_negative()

    @Property(bool, notify=onlineChanged)
    def online(self) -> bool:  # noqa: N802
        return self._osm.online

    # ---- tile resolution -----------------------------------------------------

    def tile_for(self, z: int, x: int, y: int) -> bytes | None:
        """Resolve one tile: offline source first, then OSM."""
        if self._source is not None:
            key = (z, x, y)
            with self._cache_lock:
                if key in self._cache:
                    try:
                        self._cache_order.remove(key)
                    except ValueError:
                        pass
                    self._cache_order.append(key)
                    return self._cache[key]
            try:
                data = self._source.tile(z, x, y)
            except Exception:  # noqa: BLE001 — a bad tile must never kill the map
                data = None
            if data is not None:
                with self._cache_lock:
                    self._cache[key] = data
                    self._cache_order.append(key)
                    if len(self._cache_order) > self._cache_limit:
                        old = self._cache_order.pop(0)
                        self._cache.pop(old, None)
                return data
        if z > _OSM_MAX_ZOOM:
            return None
        was_online = self._osm.online
        data = self._osm.tile(z, x, y)
        if self._osm.online != was_online:
            self.onlineChanged.emit()          # cross-thread signal -> queued to the GUI thread
        return data

    # ---- QML API (legacy offline-only surface, kept for compatibility) ----

    @Property(str, notify=sourceChanged)
    def source(self) -> str:  # noqa: N802
        if self._overlay_path:
            return f"image-overlay:{self._overlay_label}"
        return self._source.name if self._source else "osm-online"

    @Property(bool, notify=availableChanged)
    def available(self) -> bool:  # noqa: N802
        """True when any basemap can render (offline tiles OR online OSM)."""
        return True   # a basemap (offline, cached OSM or the grid) is always drawable

    @Property(str, notify=onlineChanged)
    def statusText(self) -> str:  # noqa: N802
        if self._overlay_path:
            return f"image overlay: {self._overlay_label}"
        if self._source:
            info = getattr(self._source, "max_zoom", None)
            return f"{self._source.name}" + (f" (z≤{info})" if info else "")
        if not self._osm.online:
            return "osm offline — tiles cached only"
        return "openstreetmap online"

    @Slot(int, int, int, int, int)
    def prefetch(self, z: int, x0: int, x1: int, y0: int, y1: int) -> None:
        """Warm tiles for the inclusive range (x0..x1, y0..y1) at zoom z in the
        background. Called by MapView as soon as the viewport (or zoom) changes so
        the whole screen downloads in parallel instead of one tile at a time."""
        if self._source is not None or z > _OSM_MAX_ZOOM or z < 0:
            return
        n = 1 << z
        keys = []
        for tx in range(max(0, x0), min(n - 1, x1) + 1):
            for ty in range(max(0, y0), min(n - 1, y1) + 1):
                keys.append((z, tx, ty))
                if len(keys) >= 200:
                    break
        self._osm.prefetch(keys)

    @Slot(int, int, int, int, int, bool)
    def prefetchLow(self, z: int, x0: int, x1: int, y0: int, y1: int, replace: bool) -> None:  # noqa: N802
        """Like prefetch(), but only uses idle download workers (neighbour zooms)."""
        if self._source is not None or z > _OSM_MAX_ZOOM or z < 0:
            return
        n = 1 << z
        keys = [(z, tx, ty) for tx in range(max(0, x0), min(n - 1, x1) + 1)
                for ty in range(max(0, y0), min(n - 1, y1) + 1)][:200]
        self._osm.prefetch_low(keys, replace)

    def tile_nowait(self, z: int, x: int, y: int) -> bytes | None:
        """For the image provider: return the tile if we have it, otherwise START the
        download in the pool and return None immediately. Qt services every image
        request on ONE reader thread — blocking it on the network (the old behaviour)
        serialised all tiles and starved the placeholders. The provider answers with a
        transparent tile and QML reloads it when `tileReady` fires."""
        if self._source is not None:
            return self.tile_for(z, x, y)
        if z > _OSM_MAX_ZOOM or z < 0:
            return None
        data = self._osm.peek(z, x, y)
        if data is None:
            self._osm.schedule(z, x, y)
        return data

    # ---- file-URL tile API (GUI thread only) -------------------------------------------

    def _offline_dir(self) -> Path:
        # Keyed by the source file's path + size + mtime, so replacing the
        # .mbtiles/.pmtiles with a new one never shows stale copied tiles.
        if getattr(self, "_offline_dir_cache", None) is None:
            src = getattr(self._source, "_path", None) or getattr(self._source, "_root", None)
            ident = str(getattr(self._source, "name", "offline"))
            try:
                st = Path(src).stat()
                ident = f"{Path(src).resolve()}|{st.st_size}|{int(st.st_mtime)}"
            except (TypeError, OSError):
                pass
            self._offline_dir_cache = (self._osm.cache_dir.parent / "offline-tiles"
                                       / hashlib.sha1(ident.encode()).hexdigest()[:12])
        return self._offline_dir_cache

    def _offline_path(self, z: int, x: int, y: int) -> Path:
        return self._offline_dir() / str(z) / f"{x}-{y}.tile"

    def _materialize(self, key) -> None:
        """Pool thread: copy one offline-source tile to disk for QML."""
        z, x, y = key
        try:
            data = self._source.tile(z, x, y) if self._source is not None else None
        except Exception:  # noqa: BLE001
            data = None
        if data:
            if write_atomic(self._offline_path(z, x, y), data):
                self.tileReady.emit(z, x, y)
        else:
            with self._cache_lock:
                self._offline_missing.add(key)
        with self._cache_lock:
            self._offline_inflight.discard(key)

    @Slot(int, int, int, bool, result=str)
    def tileUrl(self, z: int, x: int, y: int, fetch: bool) -> str:  # noqa: N802
        """file:// URL of the tile if it is on disk, else "" (and, with
        `fetch`, start getting it; tileReady fires when it lands)."""
        if z < 0 or x < 0 or y < 0 or x >= (1 << z) or y >= (1 << z):
            return ""
        if self._source is not None:
            path = self._offline_path(z, x, y)
            if path.exists():
                return QUrl.fromLocalFile(str(path)).toString()
            key = (z, x, y)
            with self._cache_lock:
                known_missing = key in self._offline_missing
                busy = key in self._offline_inflight
                if fetch and not known_missing and not busy:
                    self._offline_inflight.add(key)
            if fetch and not known_missing and not busy:
                self._osm.submit_job(self._materialize, key)
            if not known_missing:
                return ""
            # not in the offline set: fall through to OSM for this tile
        if z > _OSM_MAX_ZOOM:
            return ""
        path = self._osm.cached_path(z, x, y)
        if path is not None:
            return QUrl.fromLocalFile(str(path)).toString()
        if fetch:
            was_online = self._osm.online
            self._osm.schedule(z, x, y)
            if self._osm.online != was_online:
                self.onlineChanged.emit()
        return ""

    @Slot(int, int, int, result=bool)
    def hasTile(self, z: int, x: int, y: int) -> bool:  # noqa: N802
        return self.tileUrl(z, x, y, False) != ""

    def peek_tile(self, z: int, x: int, y: int) -> bytes | None:
        """Cache-only: offline source or already-downloaded OSM tile; no network."""
        if self._source is not None:
            return self.tile_for(z, x, y)
        if z > _OSM_MAX_ZOOM or z < 0:
            return None
        return self._osm.peek(z, x, y)

    @Slot(int, int, int)
    def requestTile(self, z: int, x: int, y: int) -> None:  # noqa: N802
        """Warm the cache for a tile (called by the provider before getTile)."""
        self.tile_for(z, x, y)

    @Slot(int, int, int, result=QByteArray)
    def getTile(self, z: int, x: int, y: int) -> QByteArray:  # noqa: N802
        return QByteArray(self.tile_for(z, x, y) or b"")

    @Slot(result=int)
    def minZoom(self) -> int:  # noqa: N802
        # Online OSM covers z0..19, so the operative minimum is 2 regardless
        # of the offline set's range (offline tiles simply fall back to OSM).
        return 2

    @Slot(result=int)
    def maxZoom(self) -> int:  # noqa: N802
        return max(int(getattr(self._source, "max_zoom", 6) or 6), _OSM_MAX_ZOOM)

    @Property(bool, notify=onlineChanged)
    def fallbackGrid(self) -> bool:  # noqa: N802
        """True when no basemap is available right now (no offline tiles and
        OSM unreachable). It only controls whether the grid is drawn UNDER the
        tile layer — QML keeps requesting tiles regardless, so cached tiles still
        show and the map recovers by itself when the network returns. (It used to
        also stop tile requests, and one timed-out tile blanked the map until
        restart.)"""
        return self._source is None and not self._osm.online
