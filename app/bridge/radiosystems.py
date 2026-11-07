"""RadioSystems: one-tap setup for off-the-shelf video + telemetry links.

Each entry holds a product's factory defaults, so choosing the radio an
operator already owns sets the video source and, where that radio also carries
MAVLink, the telemetry link. Addresses come from the makers' manuals:
    SIYI      MK15 manual "Common IP Addresses" and its QGC setup
    Herelink  CubePilot "Video and Data Sharing" (hotspot)
    Skydroid  G16 manual (C10 Pro RTSP, RC hotspot telemetry)
    OpenIPC   docs.openipc.org ground station guide (H.265, 5600 / 14550)
    WFB-ng    PX4 WFB-ng guide; OpenHD QGroundControl guide (5600 / 14550)

The live telemetry link is never replaced while a vehicle is connected: tapping
a system in the air must not be able to cut the command link.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Property, Signal, Slot

from app.bridge.settings import app_settings

_UDP_LISTEN = {"mode": "udp", "udp_role": "udpin", "udp_host": "0.0.0.0", "udp_port": 14550}
_SIYI_LINK = {"mode": "udp", "udp_role": "udpout", "udp_host": "192.168.144.12", "udp_port": 19856}
_SIYI_NOTE = "Give this PC a 192.168.144.x address on the ground unit's network."

SYSTEMS = (
    {"id": "analog_usb", "group": "Analog", "label": "5.8 GHz receiver + USB capture",
     "video": {"mode": "webcam"}, "link": {"mode": "auto"},
     "note": "Receiver AV output into a USB capture dongle. "
             "SiK or RFD900 telemetry radios are detected on any serial port."},
    {"id": "hdmi_capture", "group": "Digital", "label": "HDMI out + capture card",
     "video": {"mode": "webcam"}, "link": None,
     "note": "Any receiver, goggles or controller with HDMI out (e.g. HDZero, Walksnail VRX). "
             "Telemetry stays as set in Connection."},
    {"id": "siyi", "group": "Digital", "label": "SIYI HM30 / MK15 / A8 mini / ZR10",
     "video": {"mode": "rtsp", "url": "rtsp://192.168.144.25:8554/main.264"}, "link": _SIYI_LINK,
     "note": _SIYI_NOTE},
    {"id": "siyi_new", "group": "Digital", "label": "SIYI (newer camera firmware)",
     "video": {"mode": "rtsp", "url": "rtsp://192.168.144.25:8554/video1"}, "link": _SIYI_LINK,
     "note": _SIYI_NOTE + " Use this if main.264 shows no picture."},
    {"id": "herelink", "group": "Digital", "label": "CubePilot Herelink",
     "video": {"mode": "rtsp", "url": "rtsp://192.168.43.1:8554/fpv_stream"}, "link": _UDP_LISTEN,
     "note": "Join the Herelink controller's Wi-Fi hotspot from this PC."},
    {"id": "skydroid", "group": "Digital", "label": "Skydroid H12 / H16 / H30 / G16",
     "video": {"mode": "rtsp", "url": "rtsp://192.168.144.108:554/stream=0"},
     "link": {"mode": "tcp", "tcp_host": "192.168.43.1", "tcp_port": 5760},
     "note": "Join the controller's Wi-Fi hotspot. The URL is for the C10 Pro; "
             "for other cameras enter yours under Manual."},
    {"id": "openipc", "group": "Digital", "label": "OpenIPC (H.265)",
     "video": {"mode": "udp_h265", "url": "5600"}, "link": _UDP_LISTEN,
     "note": "Point the ground station's video and MAVLink peers at this PC."},
    {"id": "wfb_openhd", "group": "Digital", "label": "WFB-ng / OpenHD (H.264)",
     "video": {"mode": "udp_rtp", "url": "5600"}, "link": _UDP_LISTEN,
     "note": "Connect by USB tethering, Wi-Fi or Ethernet hotspot. "
             "If the air unit encodes H.265, use RTP H.265 under Manual."},
    {"id": "ip_radio", "group": "Digital", "label": "IP radio (Doodle Labs, Silvus, Microhard)",
     "video": {"mode": "rtsp"}, "link": _UDP_LISTEN,
     "note": "These carry any IP traffic, so enter your camera's RTSP URL under Manual."},
    {"id": "any_ip", "group": "Other", "label": "Any other system",
     "video": {"mode": "auto"}, "link": None,
     "note": "Send video to UDP 5600 (H.264 or H.265 RTP, or MPEG-TS) and it is detected. "
             "Anything else: Manual → Stream URL (rtsp, rtmp, srt, udp, http) or USB / HDMI Capture."},
)
_BY_ID = {s["id"]: s for s in SYSTEMS}


class RadioSystems(QObject):
    currentChanged = Signal()

    def __init__(self, video, link) -> None:
        super().__init__()
        self._video = video
        self._link = link
        self._settings = app_settings()
        video.statusChanged.connect(self.currentChanged)

    def _video_matches(self, system: dict) -> bool:
        wanted = system["video"]
        config = self._video._config
        return config.get_mode() == wanted["mode"] and (
            "url" not in wanted or config.get_custom_url(wanted["mode"]) == wanted["url"])

    @Property("QVariantList", constant=True)
    def systems(self) -> list:
        return [{k: s[k] for k in ("id", "group", "label", "note")} for s in SYSTEMS]

    @Property(str, notify=currentChanged)
    def current(self) -> str:
        """The applied system, until the operator changes its video source by hand."""
        system = _BY_ID.get(str(self._settings.value("video/system", "")))
        return system["id"] if system and self._video_matches(system) else ""

    @Slot(str, result="QVariantMap")
    def apply(self, system_id: str) -> dict:
        system = _BY_ID.get(system_id)
        if system is None:
            return {"ok": False, "message": "Unknown radio system"}
        wanted = system["video"]
        if "url" in wanted and not self._video.setCustomUrl(wanted["mode"], wanted["url"]):
            return {"ok": False, "message": self._video.label}
        self._settings.setValue("video/system", system_id)
        self._settings.sync()
        self._video.setMode(wanted["mode"])

        if system["link"] is None:
            return {"ok": True, "message": "Video set · telemetry unchanged"}
        if self._link.status == "connected":
            return {"ok": True, "message": "Video set · telemetry kept, vehicle is connected"}
        result = self._link.apply({**self._link.config, **system["link"]}, True)
        if not result["ok"]:
            return {"ok": False, "message": result["error"]}
        return {"ok": True, "message": "Video and telemetry set · saved"}
