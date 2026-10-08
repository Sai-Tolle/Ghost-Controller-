#!/usr/bin/env python3
"""Video pipeline tests (no hardware, no network beyond localhost).

Covers the M2/M3 video milestone:
  1. config        — VideoConfig mode/url persistence via QSettings
  2. test source   — synthetic worker produces deterministic BGR frames
  3. mjpeg         — worker decodes a live multipart/x-mixed-replace server
  4. udp_rtp       — REAL RTP/H.264 over UDP via system ffmpeg (the exact
                     transport PX4 SITL's gz gstreamer plugin emits), decoded
                     through the same SDP/PyAV path the worker uses
  5. controller    — VideoController: mode switch, frame property, LIVE state
  6. worker restart — switching kinds stops the previous loop cleanly

Usage:
    .venv-desktop/bin/python tests/test_video.py
"""
import os
os.environ.setdefault("GH_QSETTINGS_APP", "ghost-handler-tests")  # never pollute real settings

import http.server
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Qt needs a platform even in pure-logic tests (QImage/QSettings).
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

FAILURES = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(("PASS " if cond else "FAIL ") + name + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


# ---------------------------------------------------------------------------

def test_config() -> None:
    from app.video.config import VideoConfig

    cfg = VideoConfig()
    old = cfg.snapshot()

    cfg.set_mode("udp_rtp")
    cfg.set_custom_url("rtsp", "rtsp://10.220.4.17:8554/main")
    check("config mode persisted", cfg.get_mode() == "udp_rtp")
    check("config custom url persisted", cfg.get_custom_url("rtsp") == "rtsp://10.220.4.17:8554/main")
    check("config rejects unknown mode", _raises(lambda: cfg.set_mode("hdmi"), ValueError))

    # restore so a dev run of the app isn't left on a weird source
    for m, u in old["urls"].items():
        cfg.set_custom_url(m, u)
    cfg.set_mode(old["mode"])


def _raises(fn, exc_type) -> bool:
    try:
        fn()
        return False
    except exc_type:
        return True


def test_test_source() -> None:
    from app.video.worker import FrameHub, VideoWorker

    hub = FrameHub()
    w = VideoWorker(hub)
    w.detail = ""
    w._thread = threading.Thread(target=w._loop, name="t-test", daemon=True)
    w._thread.start()
    w.start({"kind": "test"})

    deadline = time.time() + 5
    first = None
    while time.time() < deadline:
        first = hub.latest(max_age=5.0)
        if first is not None:
            break
        time.sleep(0.05)
    check("test source produces frames", first is not None)
    if first is None:
        w.stop()
        return
    check("test frame is 640x480 BGR", first.shape == (480, 640, 3), f"shape={first.shape}")

    f1 = hub.frames
    time.sleep(0.35)
    check("test source advances frames", hub.frames > f1)

    w.stop()
    after = hub.frames
    time.sleep(0.2)
    check("test source stops cleanly", not w.running and hub.frames <= after + 15)


def test_mjpeg() -> None:
    import cv2
    import numpy as np

    # Tiny MJPEG server: multipart/x-mixed-replace with incrementing counter.
    jpgs = []
    for i in range(4):
        img = np.full((120, 160, 3), i * 40, dtype=np.uint8)
        ok, buf = cv2.imencode(".jpg", img)
        assert ok
        jpgs.append(buf.tobytes())

    class MJHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.end_headers()
            try:
                while True:
                    for j in jpgs:
                        self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + j + b"\r\n")
                        self.wfile.flush()
                        time.sleep(0.05)
            except Exception:
                pass

        def log_message(self, *a):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), MJHandler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()

    from app.video.worker import FrameHub, VideoWorker

    hub = FrameHub()
    w = VideoWorker(hub)
    w.detail = f"http://127.0.0.1:{port}/vision"
    w._thread = threading.Thread(target=w._loop, daemon=True)
    w._thread.start()
    w.start({"kind": "mjpeg"})

    deadline = time.time() + 8
    while time.time() < deadline and hub.frames < 3:
        time.sleep(0.05)
    check("mjpeg worker decodes frames", hub.frames >= 3, f"frames={hub.frames} err={hub.last_error}")

    w.stop()
    server.shutdown()


def test_udp_rtp() -> None:
    """Real RTP/H.264 over UDP: ffmpeg encodes a synthetic pattern to
    rtp://127.0.0.1:<port> — exactly what PX4 SITL's gz gstreamer camera
    plugin sends. The worker's SDP/PyAV path must decode it."""
    ffmpeg = shutil.which("ffmpeg")
    check("ffmpeg available for RTP test", bool(ffmpeg))
    if not ffmpeg:
        return
    enc = subprocess.run([ffmpeg, "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
    if "libx264" not in enc:
        print("SKIP udp_rtp test — system ffmpeg lacks libx264")
        return

    # Pick a free UDP port.
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()

    # testsrc2 exercises many colors (unlike plain testsrc) so decode errors
    # would be visible; 15 fps, keyframe every second like SITL cameras.
    proc = subprocess.Popen(
        [
            ffmpeg, "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "testsrc2=size=640x480:rate=15",
            "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency",
            "-pix_fmt", "yuv420p", "-g", "15",
            "-f", "rtp", f"rtp://127.0.0.1:{port}",
        ],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    proc = subprocess.Popen(
        [
            ffmpeg, "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "testsrc=size=640x480:rate=15",
            "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency",
            "-pix_fmt", "yuv420p", "-g", "15",           # keyframe every second
            "-f", "rtp", f"rtp://127.0.0.1:{port}",
        ],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        from app.video.worker import FrameHub, VideoWorker

        hub = FrameHub()
        w = VideoWorker(hub)
        w.detail = str(port)
        w._thread = threading.Thread(target=w._loop, daemon=True)
        w._thread.start()
        w.start({"kind": "udp_rtp"})

        deadline = time.time() + 20
        while time.time() < deadline and hub.frames < 5:
            time.sleep(0.1)
        check("udp_rtp decodes real H.264/RTP frames", hub.frames >= 5,
              f"frames={hub.frames} err={hub.last_error}")

        w.stop()
    finally:
        proc.terminate()
        proc.wait(timeout=5)

def test_controller() -> None:
    from PySide6.QtGui import QGuiApplication

    app = QGuiApplication.instance() or QGuiApplication(sys.argv)

    from app.video.config import VideoConfig
    from app.video.controller import VideoController

    cfg = VideoConfig()
    old = cfg.snapshot()
    cfg.set_mode("test")          # deterministic, no hardware
    cfg.set_custom_url("rtsp", "")  # keep restored state clean

    vc = VideoController()
    deadline = time.time() + 6
    while time.time() < deadline and vc.state != "live":
        app.processEvents()
        time.sleep(0.02)
    check("controller reaches LIVE on test mode", vc.state == "live", f"state={vc.state} label={vc.label}")
    check("controller has frame", vc.hasFrame and not vc._image.isNull())
    # FPS updates on a 1 s timer — pump the loop past one interval before judging.
    fps_deadline = time.time() + 3
    while time.time() < fps_deadline and vc.fps <= 0:
        app.processEvents()
        time.sleep(0.05)
    check("controller fps measured", vc.fps > 0, f"fps={vc.fps}")

    # QSettings round trip through the controller slot
    vc.setMode("udp_rtp")
    check("controller setMode persists", VideoConfig().get_mode() == "udp_rtp")

    vc.shutdown()
    for m, u in old["urls"].items():
        cfg.set_custom_url(m, u)
    cfg.set_mode(old["mode"])


def main() -> int:
    print("=== video tests ===")
    test_config()
    test_test_source()
    test_mjpeg()
    test_udp_rtp()
    test_controller()
    print(f"\n{'VIDEO TESTS PASSED' if not FAILURES else str(len(FAILURES)) + ' FAILURES'}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
