#!/usr/bin/env python3
"""Off-the-shelf radio system presets (no hardware, no network beyond localhost).

Covers:
  1. catalog    — every preset passes the same validation the UI's fields do
  2. apply      — video and telemetry both follow the chosen system
  3. safety     — a live vehicle link is never replaced by a preset
  4. udp hello  — a udpout link speaks first, or the far end never answers

Usage:
    .venv-desktop/bin/python tests/test_radio_systems.py
"""
import os
os.environ.setdefault("GH_QSETTINGS_APP", "ghost-handler-tests")  # never pollute real settings
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import socket
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FAILURES = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(("PASS " if cond else "FAIL ") + name + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


def test_catalog() -> None:
    from app.bridge.link import DEFAULTS, validate
    from app.bridge.radiosystems import SYSTEMS
    from app.video.config import UI_MODES

    check("catalog has analog, digital and catch-all systems",
          {s["group"] for s in SYSTEMS} == {"Analog", "Digital", "Other"})
    check("catalog ids are unique", len({s["id"] for s in SYSTEMS}) == len(SYSTEMS))
    for system in SYSTEMS:
        check(f"{system['id']}: video mode is in the panel", system["video"]["mode"] in UI_MODES)
        if system["link"] is not None:
            cfg, err = validate({**DEFAULTS, **system["link"]})
            check(f"{system['id']}: telemetry settings are valid", cfg is not None, err)


def test_apply() -> None:
    from PySide6.QtGui import QGuiApplication

    QGuiApplication.instance() or QGuiApplication(sys.argv)

    from app.bridge.link import LinkController
    from app.bridge.radiosystems import RadioSystems, _BY_ID
    from app.video.controller import VideoController

    video = VideoController()
    old_video = video._config.snapshot()
    link = LinkController(None)
    old_link = link.config
    radios = RadioSystems(video, link)
    try:
        for system_id, mode in (("siyi", "rtsp"), ("openipc", "udp_h265"), ("analog_usb", "webcam")):
            res = radios.apply(system_id)
            check(f"{system_id}: applied", res["ok"], res["message"])
            check(f"{system_id}: video mode set", video._config.get_mode() == mode)
            check(f"{system_id}: is now current", radios.current == system_id, radios.current)
            wanted = _BY_ID[system_id]["link"]
            check(f"{system_id}: telemetry set", all(link.config[k] == v for k, v in wanted.items()),
                  str(link.config))

        radios.apply("siyi")
        check("siyi: RTSP URL set", video._config.get_custom_url("rtsp") == "rtsp://192.168.144.25:8554/main.264")
        video.setMode("mjpeg")
        check("manual change clears the current system", radios.current == "", radios.current)

        check("unknown system refused", radios.apply("nope")["ok"] is False)

        before = link.config
        res = radios.apply("hdmi_capture")
        check("system without telemetry leaves the link alone", res["ok"] and link.config == before)

        # A live vehicle: the preset may change video, never the command link.
        before = link.config
        link._status = "connected"
        res = radios.apply("herelink")
        check("connected vehicle keeps its telemetry link", res["ok"] and link.config == before, str(link.config))
        check("connected vehicle still gets the video", video._config.get_custom_url("rtsp").endswith("/fpv_stream"))
        check("operator told telemetry was kept", "kept" in res["message"], res["message"])
    finally:
        video.shutdown()
        for mode, url in old_video["urls"].items():
            video._config.set_custom_url(mode, url)
        video._config.set_mode(old_video["mode"])
        link._status = "unavailable"
        link.apply(old_link, False)
        radios._settings.remove("video/system")


def test_udpout_says_hello() -> None:
    """Fake ground unit: answers with a vehicle heartbeat only after it has
    heard from the GCS, which is how a UDP server learns its client's address."""
    from pymavlink import mavutil

    from backend.mavlink.connection import MAVLinkConnection

    # On Windows pymavlink binds the udpout socket to 0.0.0.0:<destination
    # port> (as QGC does for SIYI: local 19856 → ground unit :19856). With the
    # fake unit on 127.0.0.1 too, its replies would loop back to itself.
    host = "127.0.0.2" if sys.platform == "win32" else "127.0.0.1"
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((host, 0))
    sock.settimeout(5.0)
    port = sock.getsockname()[1]

    class Sink:
        def __init__(self, addr):
            self.addr = addr

        def write(self, buf):
            sock.sendto(buf, self.addr)

    heard = {}

    def ground_unit() -> None:
        try:
            _, addr = sock.recvfrom(512)
        except OSError:
            return
        heard["addr"] = addr
        mav = mavutil.mavlink.MAVLink(Sink(addr), srcSystem=1, srcComponent=1)
        for _ in range(5):
            mav.heartbeat_send(mavutil.mavlink.MAV_TYPE_QUADROTOR, mavutil.mavlink.MAV_AUTOPILOT_PX4, 0, 0, 0)

    thread = threading.Thread(target=ground_unit, daemon=True)
    thread.start()
    conn = MAVLinkConnection(f"udpout:{host}:{port}")
    master = mavutil.mavlink_connection(f"udpout:{host}:{port}")
    try:
        hb = conn._wait_vehicle_heartbeat(master, conn._generation, timeout=6.0)
        check("udpout link speaks first", "addr" in heard)
        check("udpout link gets the vehicle heartbeat", hb is not None)
    finally:
        master.close()
        thread.join(timeout=6)
        sock.close()


def main() -> int:
    print("=== radio system tests ===")
    test_catalog()
    test_apply()
    test_udpout_says_hello()
    print(f"\n{'RADIO SYSTEM TESTS PASSED' if not FAILURES else str(len(FAILURES)) + ' FAILURES'}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
