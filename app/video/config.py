"""Video source configuration — the desktop counterpart of the web GCS's
POST /video/config + /video/config/url/{mode} endpoints (GCS/video/
stream_config.py, source_detector.py), presented natively in the VideoSourcePanel.

UI-facing modes mirror the web panel exactly (VideoSourcePanel.tsx):
    auto    probe udp_rtp → rtsp → mjpeg (same priority order)
    udp_rtp PX4 SITL / drone H.264 RTP over UDP (QGC convention, port 5600)
    rtsp    RTSP camera
    mjpeg   MJPEG-over-HTTP camera (WiFi boson cam etc.)

Internal-only modes (NOT shown in the panel; used by CI/tests and via
GH_VIDEO_ALLOW_INTERNAL_MODES=1 for demos):
    webcam  local USB webcam (OpenCV index)
    test    built-in synthetic pattern (CI / demos, no hardware)

The mode and per-mode custom URLs persist via QSettings (organization
"Ghost Handler", app "Ghost Handler") so the panel restores the operator's
last setup — the same behavior the web UI gets from StreamConfig's file.
"""
from __future__ import annotations

import os

from PySide6.QtCore import QSettings

from app.bridge.settings import app_settings

# Order = the web panel's row order (auto first).
UI_MODES = ("auto", "udp_rtp", "rtsp", "mjpeg")
# Worker-only modes stay reachable for tests/CI (test_video.py) and demos.
INTERNAL_MODES = ("webcam", "test")
ALL_MODES = UI_MODES + INTERNAL_MODES
MODES = ALL_MODES  # backwards-compatible alias used by VideoController

DEFAULT_RTP_PORT = 5600  # QGC / PX4 gz gstreamer convention
DEFAULT_WEBCAM_INDEX = 0

_DEFAULT_URLS = {
    "rtsp": "rtsp://127.0.0.1:8554/stream",
    "mjpeg": "http://192.168.4.1/vision",
}

# Hints rendered under each row — same copy as the web VideoSourcePanel.
UI_HINTS = {
    "auto": "Probe RTP → RTSP → MJPEG",
    "udp_rtp": "PX4 SITL / drone H.264 on UDP 5600",
    "rtsp": "rtsp://127.0.0.1:8554 or custom URL",
    "mjpeg": "http://192.168.4.1/vision or custom URL",
}

UI_LABELS = {
    "auto": "AUTO",
    "udp_rtp": "RTP 5600",
    "rtsp": "RTSP",
    "mjpeg": "MJPEG",
}

URL_PLACEHOLDERS = {
    "rtsp": "rtsp://user:pass@host:554/stream",
    "mjpeg": "http://host:8080/video",
}


def _internal_modes_allowed() -> bool:
    return os.environ.get("GH_VIDEO_ALLOW_INTERNAL_MODES", "") not in ("", "0")


def panel_modes() -> tuple[str, ...]:
    """Modes shown in the VideoSourcePanel (web parity: 4)."""
    return ALL_MODES if _internal_modes_allowed() else UI_MODES


class VideoConfig:
    """Video source settings with QSettings-backed persistence."""

    def __init__(self) -> None:
        self._settings = app_settings()

    # ---- mode ----

    def get_mode(self) -> str:
        mode = str(self._settings.value("video/mode", "auto"))
        return mode if mode in ALL_MODES else "auto"

    def set_mode(self, mode: str) -> None:
        if mode not in ALL_MODES:
            raise ValueError(f"unknown video mode: {mode!r}")
        self._settings.setValue("video/mode", mode)
        self._settings.sync()

    # ---- per-mode custom URL / target ----

    def get_custom_url(self, mode: str) -> str:
        url = str(self._settings.value(f"video/url/{mode}", ""))
        return url.strip()

    def set_custom_url(self, mode: str, url: str) -> None:
        if mode not in ALL_MODES:
            raise ValueError(f"unknown video mode: {mode!r}")
        self._settings.setValue(f"video/url/{mode}", url.strip())
        self._settings.sync()

    def default_url(self, mode: str) -> str:
        if mode == "rtsp":
            return _DEFAULT_URLS["rtsp"]
        if mode == "mjpeg":
            return _DEFAULT_URLS["mjpeg"]
        if mode == "udp_rtp":
            return str(os.environ.get("GH_VIDEO_RTP_PORT", DEFAULT_RTP_PORT))
        if mode == "webcam":
            return str(DEFAULT_WEBCAM_INDEX)
        return ""

    # ---- introspection (VideoController status / tests) ----

    def snapshot(self) -> dict:
        return {"mode": self.get_mode(), "urls": {m: self.get_custom_url(m) for m in ALL_MODES}}
