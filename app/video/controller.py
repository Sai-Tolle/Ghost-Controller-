"""VideoController — the single seam between video acquisition and QML.

Owns a VideoWorker thread plus a FrameHub; a QTimer (default 30 Hz) copies
the newest BGR frame into a QImage and repaints the bound QML item. Status
(state/label/fps) updates like the web HUD's video panel; all source
selection mirrors the backend's mode semantics (auto probe order
udp_rtp → rtsp → mjpeg → webcam, custom-URL-first within each family).
USB capture devices (analog receivers, HDMI capture cards) are listed on a
background thread because finding them can mean opening each one.

QML API:
    readonly frame        QImage (valid while hasFrame)
    readonly hasFrame     bool
    readonly state        "idle"|"connecting"|"live"|"error"
    readonly label        human status ("LIVE · udp_rtp:5600", errors, ...)
    readonly sourceLabel  configured source ("auto", "udp_rtp:5600", ...)
    readonly fps          measured frames per second
    readonly captureDevices  [{id, label}] of USB capture devices
    readonly captureDevice   selected capture device id
    Slots: setMode(mode), setCustomUrl(mode, url) → bool, forceReconnect(),
           scanCaptureDevices()
"""
from __future__ import annotations

import os
import re
import threading
import time
from urllib.parse import urlsplit

from PySide6.QtCore import QObject, Property, QTimer, Signal, Slot
from PySide6.QtGui import QImage
from PySide6.QtQuick import QQuickImageProvider

from app.video.config import DEFAULT_RTP_PORT, MODES, UDP_MODES, VideoConfig
from app.video.devices import list_capture_devices
from app.video.worker import URL_SCHEMES, FrameHub, VideoWorker, redact_url

class VideoImageProvider(QQuickImageProvider):
    """Serves the newest frame as image://video/<seq> — QML Image elements
    re-fetch whenever the URL's seq changes, giving repaint + aspect-fit
    scaling without any Canvas code."""

    def __init__(self, controller: "VideoController") -> None:
        super().__init__(QQuickImageProvider.Image)
        self._controller = controller

    def requestImage(self, id: str, size, requestedSize):  # noqa: N802
        # PySide6 wants ONLY the QImage here — returning a tuple makes every
        # fetch fail ("Invalid return value ... got tuple"), so the panel
        # would never paint. Size is reported via the passed-in `size` object.
        img = self._controller._image
        if img.isNull():
            if size is not None:
                size.setWidth(0)
                size.setHeight(0)
            return QImage()
        if size is not None:
            size.setWidth(img.width())
            size.setHeight(img.height())
        return img.copy()


class VideoController(QObject):
    frameChanged = Signal()
    statusChanged = Signal()
    devicesChanged = Signal()
    _devicesFound = Signal("QVariantList")  # scan thread → GUI thread

    def __init__(self, parent=None, data_lake=None) -> None:
        super().__init__(parent)
        self._config = VideoConfig()
        self._lake = data_lake
        self._hub = FrameHub()
        self._worker = VideoWorker(self._hub)
        self._image = QImage()
        self._frame_seq = 0  # bumped per rendered frame (image://video/<seq>)
        self._provider = VideoImageProvider(self)
        self._has_frame = False
        self._state = "idle"
        self._label = ""
        self._fps = 0.0
        self._resolution = ""  # "1280x720" from the last frame
        self._seen_frames = 0  # hub count at last fps sample
        self._last_fps_ts = time.monotonic()
        self._devices: list[dict] = []
        self._scanning = False
        self._devicesFound.connect(self._on_devices_found)

        self._timer = QTimer(self)
        self._timer.setInterval(33)  # ~30 Hz paint tick
        self._timer.timeout.connect(self._tick)
        self._timer.start()

        self._fps_timer = QTimer(self)
        self._fps_timer.setInterval(1000)
        self._fps_timer.timeout.connect(self._measure_fps)
        self._fps_timer.start()

        self._thread = threading.Thread(target=self._worker._loop, name="gh-video", daemon=True)
        self._thread.start()
        self._apply_mode(self._config.get_mode())

    # ---- QML properties ---------------------------------------------------

    @Property(int, notify=frameChanged)
    def frameSeq(self) -> int:  # noqa: N802
        """Frame counter — QML Image sources use image://video/<frameSeq>."""
        return self._frame_seq

    @Property(QImage, notify=frameChanged)
    def frame(self) -> QImage:  # noqa: N802
        return self._image

    @Property(bool, notify=frameChanged)
    def hasFrame(self) -> bool:  # noqa: N802
        return self._has_frame

    @Property(str, notify=statusChanged)
    def state(self) -> str:  # noqa: N802
        return self._state

    @Property(str, notify=statusChanged)
    def label(self) -> str:  # noqa: N802
        return self._label

    @Property(str, notify=statusChanged)
    def sourceLabel(self) -> str:  # noqa: N802
        mode = self._config.get_mode()
        if mode in UDP_MODES:
            return f"{mode}:{self._config.get_custom_url(mode) or self._config.default_url(mode)}"
        url = self._config.get_custom_url(mode)
        if url:
            return f"{mode}:{redact_url(url)}"     # never paint camera passwords on the HUD
        if mode == "webcam":
            return f"webcam:{self._config.default_url('webcam')}"
        return mode

    @Property(float, notify=statusChanged)
    def fps(self) -> float:  # noqa: N802
        return round(self._fps, 1)

    @Property(str, notify=frameChanged)
    def resolution(self) -> str:  # noqa: N802
        """Last frame size as "WxH" (empty until the first frame)."""
        return self._resolution

    @Property(str, constant=True)
    def rtpPort(self) -> str:  # noqa: N802
        return str(os.environ.get("GH_VIDEO_RTP_PORT", DEFAULT_RTP_PORT))

    @Property("QVariantMap", notify=statusChanged)
    def customUrls(self) -> dict:  # noqa: N802
        """{mode: url} — bindable. The old customUrl() slot was evaluated once
        per delegate, so the URL badge and clear button never updated after SET."""
        return {m: redact_url(self._config.get_custom_url(m)) for m in UDP_MODES + ("rtsp", "mjpeg", "url")}

    @Property("QVariantList", constant=True)
    def modeHints(self) -> list:  # noqa: N802
        return [
            {"mode": "auto", "label": "Automatic"},
            {"mode": "udp_rtp", "label": "RTP H.264"},
            {"mode": "udp_h265", "label": "RTP H.265"},
            {"mode": "udp_ts", "label": "MPEG-TS"},
            {"mode": "rtsp", "label": "RTSP"},
            {"mode": "mjpeg", "label": "MJPEG"},
            {"mode": "url", "label": "Stream URL"},
            {"mode": "webcam", "label": "USB / HDMI Capture"},
        ]

    @Property("QVariantList", notify=devicesChanged)
    def captureDevices(self) -> list:  # noqa: N802
        return list(self._devices)

    @Property(bool, notify=devicesChanged)
    def scanningDevices(self) -> bool:  # noqa: N802
        return self._scanning

    @Property(str, notify=statusChanged)
    def captureDevice(self) -> str:  # noqa: N802
        return self._config.get_custom_url("webcam") or self._config.default_url("webcam")

    @Slot(str, result=str)
    def customUrl(self, mode: str) -> str:  # noqa: N802
        return self._config.get_custom_url(mode)

    @Slot(str, result=str)
    def defaultUrl(self, mode: str) -> str:  # noqa: N802
        return self._config.default_url(mode)

    @Slot(result=QQuickImageProvider)
    def provider(self) -> QQuickImageProvider:  # noqa: N802
        return self._provider

    # ---- QML slots --------------------------------------------------------

    @Slot(str)
    def setMode(self, mode: str) -> None:  # noqa: N802
        if mode not in MODES:
            return
        self._apply_mode(mode)

    @Slot(str, str, result=bool)
    def setCustomUrl(self, mode: str, url: str) -> bool:  # noqa: N802
        if mode not in MODES:
            return False
        url = url.strip()
        if len(url) > 2048 or any(ord(ch) < 0x20 for ch in url):
            self._label = f"{mode}: invalid URL"
            self._state = "error"
            self.statusChanged.emit()
            return False
        if mode in UDP_MODES and url and not (url.isdecimal() and 1 <= int(url) <= 65535):
            self._label = f"{mode}: UDP port must be 1–65535"
            self._state = "error"
            self.statusChanged.emit()
            return False
        if mode == "url" and url and urlsplit(url).scheme.lower() not in URL_SCHEMES:
            self._label = "url: must start with " + ", ".join(s + "://" for s in URL_SCHEMES[:6]) + " …"
            self._state = "error"
            self.statusChanged.emit()
            return False
        if mode == "webcam" and url and not re.fullmatch(r"\d+|/dev/video\d+", url):
            self._label = "capture: device must be a number or /dev/videoN"
            self._state = "error"
            self.statusChanged.emit()
            return False
        if mode in ("rtsp", "mjpeg") and url:
            ok = url.lower().startswith("rtsp://") if mode == "rtsp" else url.lower().startswith(("http://", "https://"))
            if not ok:
                self._label = f"{mode}: URL must start with " + ("rtsp://" if mode == "rtsp" else "http:// or https://")
                self._state = "error"
                self.statusChanged.emit()
                return False
        self._config.set_custom_url(mode, url)
        self.statusChanged.emit()
        if mode == self._config.get_mode():
            self._restart()
        return True

    @Slot()
    def forceReconnect(self) -> None:  # noqa: N802
        self._restart()

    @Slot()
    def scanCaptureDevices(self) -> None:  # noqa: N802
        if self._scanning:
            return
        self._scanning = True
        self.devicesChanged.emit()
        selected = self.captureDevice

        def scan() -> None:
            try:
                found = list_capture_devices(selected)
            except Exception:  # noqa: BLE001 — a failed scan is just an empty list
                found = []
            self._devicesFound.emit(found)

        threading.Thread(target=scan, name="gh-video-scan", daemon=True).start()

    @Slot("QVariantList")
    def _on_devices_found(self, devices: list) -> None:
        self._devices = list(devices)
        self._scanning = False
        self.devicesChanged.emit()

    # ---- internals ---------------------------------------------------------

    def _apply_mode(self, mode: str) -> None:
        self._config.set_mode(mode)
        self.statusChanged.emit()
        self._restart()
        if mode == "webcam":
            self.scanCaptureDevices()

    def _restart(self) -> None:
        """Resolve the configured mode into a worker spec (source_detector
        semantics: custom URL first, family defaults second)."""
        # Defensive: if the worker thread died (decoder crash etc.), respawn
        # it so a mode switch or manual reconnect still works.
        if not self._thread.is_alive():
            self._thread = threading.Thread(target=self._worker._loop, name="gh-video", daemon=True)
            self._thread.start()
        self._hub.last_error = None  # the previous source's error is not this one's
        mode = self._config.get_mode()
        url = self._config.get_custom_url(mode)
        if mode == "auto":
            # Auto listens on the QGC-convention port (PX4 SITL / drone video
            # on UDP 5600) and plays H.264 RTP, H.265 RTP or MPEG-TS, whichever
            # arrives. It does NOT fall back to a synthetic test pattern or
            # open a webcam — with no stream the panel shows NO SIGNAL.
            try:
                port = int(url or DEFAULT_RTP_PORT)
            except ValueError:
                port = DEFAULT_RTP_PORT
            self._worker.detail = str(port)
            self._worker.start({"kind": "udp_auto", "port": port})
            self._state = "connecting"
            self._label = f"auto · listening UDP {port} — no stream yet"
            self.statusChanged.emit()
            return
        if mode in UDP_MODES:
            default_port = self._config.default_url(mode)
            try:
                self._worker.detail = str(int(url or default_port))
            except ValueError:
                self._worker.detail = default_port
            self._worker.start({"kind": mode, "port": int(self._worker.detail)})
        elif mode == "url":
            self._worker.detail = url
            self._worker.start({"kind": "url"})
        elif mode == "test":
            self._worker.detail = ""
            self._worker.start({"kind": "test"})
        elif mode == "mjpeg":
            self._worker.detail = url or self._config.default_url("mjpeg")
            self._worker.start({"kind": "mjpeg", "url": self._worker.detail})
        elif mode == "rtsp":
            self._worker.detail = url or self._config.default_url("rtsp")
            self._worker.start({"kind": "rtsp", "url": self._worker.detail})
        elif mode == "webcam":
            # Numeric custom URL → camera index; device path stays a string.
            detail = (url or self._config.default_url("webcam")).strip()
            try:
                detail = str(int(detail))
            except ValueError:
                pass  # e.g. /dev/video0 — the worker handles device paths
            self._worker.detail = detail
            self._worker.start({"kind": "webcam", "index": detail})
        self._state = "connecting"
        self._label = f"connecting · {mode}"
        self.statusChanged.emit()

    def _tick(self) -> None:
        frame = self._hub.latest(max_age=1.0)
        if frame is not None:
            h, w = frame.shape[:2]
            self._image = QImage(frame.data, w, h, 3 * w, QImage.Format_BGR888).copy()
            self._has_frame = True
            resolution = f"{w}x{h}"
            self._frame_seq += 1
            if resolution != self._resolution:
                self._resolution = resolution
                self.statusChanged.emit()
            self.frameChanged.emit()
            if self._state != "live":
                self._state = "live"
                detected = self._worker.detected
                self._label = f"LIVE · {self.sourceLabel}" + (f" ({detected})" if detected else "")
                self.statusChanged.emit()
        else:
            # No fresh frame (hub drops frames older than 1 s). _has_frame used
            # to stay True forever, so a dead stream left the LAST frame frozen
            # on screen looking live and the SIGNAL LOST overlay never fired.
            if self._has_frame:
                self._has_frame = False
                self.frameChanged.emit()
            if self._state == "live":
                self._state = "connecting"
                self._label = "signal lost — waiting for frames"
                self.statusChanged.emit()
            elif self._state == "connecting" and self._hub.last_error:
                self._state = "error"
                self._label = self._hub.last_error
                self.statusChanged.emit()

    def _measure_fps(self) -> None:
        now = time.monotonic()
        total = self._hub.frames
        elapsed = now - self._last_fps_ts
        if elapsed <= 0:
            return
        delta = total - self._seen_frames
        self._seen_frames = total
        self._last_fps_ts = now
        self._fps = delta / elapsed
        if self._state == "live":
            self.statusChanged.emit()
        if self._lake is not None:
            self._lake.set("video/fps", round(self._fps, 1))
            self._lake.set("video/state", self._state)

    # ---- shutdown ----------------------------------------------------------

    def shutdown(self) -> None:
        self._timer.stop()
        self._fps_timer.stop()
        self._worker.stop()
