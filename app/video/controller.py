"""VideoController — the single seam between video acquisition and QML.

Owns a VideoWorker thread plus a FrameHub; a QTimer (default 30 Hz) copies
the newest BGR frame into a QImage and repaints the bound QML item. Status
(state/label/fps) updates like the web HUD's video panel; all source
selection mirrors the backend's mode semantics (auto probe order
udp_rtp → rtsp → mjpeg → webcam, custom-URL-first within each family).

QML API:
    readonly frame        QImage (valid while hasFrame)
    readonly hasFrame     bool
    readonly state        "idle"|"connecting"|"live"|"error"
    readonly label        human status ("LIVE · udp_rtp:5600", errors, ...)
    readonly sourceLabel  configured source ("auto", "udp_rtp:5600", ...)
    readonly fps          measured frames per second
    Slots: setMode(mode), setCustomUrl(mode, url), forceReconnect()
"""
from __future__ import annotations

import os
import threading
import time

from PySide6.QtCore import QObject, Property, QTimer, Signal, Slot
from PySide6.QtGui import QImage
from PySide6.QtQuick import QQuickImageProvider

from app.video.config import DEFAULT_RTP_PORT, MODES, VideoConfig
from app.video.worker import FrameHub, VideoWorker

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
        if mode == "udp_rtp":
            return f"udp_rtp:{self._config.get_custom_url('udp_rtp') or DEFAULT_RTP_PORT}"
        url = self._config.get_custom_url(mode)
        if url:
            return f"{mode}:{url}"
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
        return {m: self._config.get_custom_url(m) for m in ("rtsp", "mjpeg")}

    @Property("QVariantList", constant=True)
    def modeHints(self) -> list:  # noqa: N802
        return [
            {"mode": "auto", "label": "AUTO", "hint": "Listens for RTP on UDP 5600"},
            {"mode": "udp_rtp", "label": "RTP 5600", "hint": "PX4 SITL / drone H.264 on UDP 5600"},
            {"mode": "rtsp", "label": "RTSP", "hint": "rtsp://127.0.0.1:8554 or custom URL"},
            {"mode": "mjpeg", "label": "MJPEG", "hint": "http://192.168.4.1/vision or custom URL"},
        ]

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

    @Slot(str, str)
    def setCustomUrl(self, mode: str, url: str) -> None:  # noqa: N802
        if mode not in MODES:
            return
        url = url.strip()
        if mode in ("rtsp", "mjpeg") and url:
            ok = url.lower().startswith("rtsp://") if mode == "rtsp" else url.lower().startswith(("http://", "https://"))
            if not ok:
                self._label = f"{mode}: URL must start with " + ("rtsp://" if mode == "rtsp" else "http:// or https://")
                self._state = "error"
                self.statusChanged.emit()
                return
        self._config.set_custom_url(mode, url)
        self.statusChanged.emit()
        if mode == self._config.get_mode():
            self._restart()

    @Slot()
    def forceReconnect(self) -> None:  # noqa: N802
        self._restart()

    # ---- internals ---------------------------------------------------------

    def _apply_mode(self, mode: str) -> None:
        self._config.set_mode(mode)
        self.statusChanged.emit()
        self._restart()

    def _restart(self) -> None:
        """Resolve the configured mode into a worker spec (source_detector
        semantics: custom URL first, family defaults second)."""
        # Defensive: if the worker thread died (decoder crash etc.), respawn
        # it so a mode switch or manual reconnect still works.
        if not self._thread.is_alive():
            self._thread = threading.Thread(target=self._worker._loop, name="gh-video", daemon=True)
            self._thread.start()
        mode = self._config.get_mode()
        url = self._config.get_custom_url(mode)
        if mode == "auto":
            # Auto listens for the QGC-convention RTP stream (PX4 SITL / drone
            # H.264 on UDP 5600) the same way the web GCS does. It does NOT
            # fall back to a synthetic test pattern or open a webcam — with
            # no stream the panel shows NO SIGNAL until frames arrive.
            try:
                port = int(url or DEFAULT_RTP_PORT)
            except ValueError:
                port = DEFAULT_RTP_PORT
            self._worker.detail = str(port)
            self._worker.start({"kind": "udp_rtp", "port": port})
            self._state = "connecting"
            self._label = f"auto · listening UDP {port} — no stream yet"
            self.statusChanged.emit()
            return
        if mode == "udp_rtp":
            try:
                self._worker.detail = str(int(url or DEFAULT_RTP_PORT))
            except ValueError:
                self._worker.detail = str(DEFAULT_RTP_PORT)
            self._worker.start({"kind": "udp_rtp", "port": int(self._worker.detail)})
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
                self._label = f"LIVE · {self.sourceLabel}"
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
