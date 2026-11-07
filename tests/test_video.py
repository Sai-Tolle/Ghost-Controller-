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
  7. udp_h265/udp_ts — digital FPV and IP radio transports via system ffmpeg
  8. capture        — USB capture device listing and path validation
  9. udp_auto / url — auto-detected UDP transports and the catch-all URL source

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
import tempfile
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


def _stream_test(kind: str, encoder: str, muxer: str, url: str, port: int, detail: str = "",
                 expect_detected: str = "") -> None:
    """Real video over UDP: ffmpeg encodes a synthetic pattern and sends it the
    way the radio link would. The worker's PyAV path must decode it."""
    ffmpeg = shutil.which("ffmpeg")
    check("ffmpeg available for stream test", bool(ffmpeg))
    if not ffmpeg:
        return
    enc = subprocess.run([ffmpeg, "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
    if encoder not in enc:
        print(f"SKIP {kind} test — system ffmpeg lacks {encoder}")
        return

    from app.video.worker import FrameHub, VideoWorker

    # Receiver first, like a ground station waiting for the air unit.
    hub = FrameHub()
    w = VideoWorker(hub)
    w.detail = detail or str(port)
    w._thread = threading.Thread(target=w._loop, daemon=True)
    w._thread.start()
    w.start({"kind": kind})
    time.sleep(0.5)

    # testsrc at 15 fps, keyframe every second like SITL cameras.
    proc = subprocess.Popen(
        [
            ffmpeg, "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "testsrc=size=640x480:rate=15",
            "-c:v", encoder, "-preset", "ultrafast", "-tune", "zerolatency",
            "-pix_fmt", "yuv420p", "-g", "15",
            "-f", muxer, url,
        ],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.time() + 20
        while time.time() < deadline and hub.frames < 5:
            time.sleep(0.1)
        check(f"{kind} decodes real {encoder}/{muxer} frames", hub.frames >= 5,
              f"frames={hub.frames} err={hub.last_error}")
        if expect_detected:
            check(f"{kind} detects {expect_detected}", w.detected == expect_detected, repr(w.detected))
    finally:
        w.stop()
        proc.terminate()
        proc.wait(timeout=5)


def _free_udp_port() -> int:
    """A port below every OS's ephemeral range whose RTCP neighbour is free too.
    Windows hands out ephemeral ports in sequence, so a port picked with
    bind(0) is next in line for the ffmpeg sender's own sockets; the receiver
    then cannot bind it (WinError 10048)."""
    import random

    while True:
        port = random.randrange(20000, 30000, 2)
        socks = []
        try:
            for p in (port, port + 1):
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                socks.append(s)
                s.bind(("0.0.0.0", p))
            return port
        except OSError:
            continue
        finally:
            for s in socks:
                s.close()


def test_udp_rtp() -> None:
    """The exact transport PX4 SITL's gz gstreamer camera plugin emits."""
    port = _free_udp_port()
    _stream_test("udp_rtp", "libx264", "rtp", f"rtp://127.0.0.1:{port}", port)


def test_udp_h265() -> None:
    """The transport OpenIPC ground stations forward."""
    port = _free_udp_port()
    _stream_test("udp_h265", "libx265", "rtp", f"rtp://127.0.0.1:{port}", port)


def test_udp_ts() -> None:
    """The transport video encoders behind IP radios send."""
    port = _free_udp_port()
    _stream_test("udp_ts", "libx264", "mpegts", f"udp://127.0.0.1:{port}?pkt_size=1316", port)


def test_udp_auto() -> None:
    """Auto must work out each transport on its own."""
    for encoder, muxer, scheme, label in (("libx264", "rtp", "rtp", "H.264 RTP"),
                                          ("libx265", "rtp", "rtp", "H.265 RTP"),
                                          ("libx264", "mpegts", "udp", "MPEG-TS")):
        port = _free_udp_port()
        suffix = "?pkt_size=1316" if muxer == "mpegts" else ""
        _stream_test("udp_auto", encoder, muxer, f"{scheme}://127.0.0.1:{port}{suffix}", port,
                     expect_detected=label)


def test_stream_url() -> None:
    """The catch-all source plays a stream given only as a URL."""
    port = _free_udp_port()
    _stream_test("url", "libx264", "mpegts", f"udp://127.0.0.1:{port}?pkt_size=1316", port,
                 detail=f"udp://0.0.0.0:{port}")


def test_url_rejects_files() -> None:
    from app.video.worker import FrameHub, VideoWorker

    hub = FrameHub()
    w = VideoWorker(hub)
    w.detail = "file:///etc/passwd"
    w._thread = threading.Thread(target=w._loop, daemon=True)
    w._thread.start()
    w.start({"kind": "url"})
    deadline = time.time() + 5
    while time.time() < deadline and not hub.last_error:
        time.sleep(0.05)
    check("stream URL rejects file://", "enter a stream URL" in (hub.last_error or ""), str(hub.last_error))
    w.stop()


def test_capture_devices() -> None:
    """Metadata nodes and Pi media blocks must not be listed as cameras."""
    from app.video.devices import list_capture_devices

    with tempfile.TemporaryDirectory() as tmp:
        sysfs = Path(tmp)
        for node, name, index in (("video0", "USB2.0 AV Capture", "0"), ("video1", "USB2.0 AV Capture", "1"),
                                  ("video10", "bcm2835-codec-decode", "0"), ("video2", "HDMI Capture", "0")):
            (sysfs / node).mkdir()
            (sysfs / node / "name").write_text(name + "\n")
            (sysfs / node / "index").write_text(index + "\n")
        found = list_capture_devices(sysfs=sysfs)
    check("capture devices listed by name", found == [
        {"id": "0", "label": "USB2.0 AV Capture (video0)"},
        {"id": "2", "label": "HDMI Capture (video2)"},
    ], str(found))


def test_capture_rejects_files() -> None:
    """A capture source restored from settings must not open arbitrary files."""
    from app.video.worker import FrameHub, VideoWorker

    hub = FrameHub()
    w = VideoWorker(hub)
    w.detail = "movie.mp4"
    w._thread = threading.Thread(target=w._loop, daemon=True)
    w._thread.start()
    w.start({"kind": "webcam"})
    deadline = time.time() + 5
    while time.time() < deadline and not hub.last_error:
        time.sleep(0.05)
    check("capture rejects a file path", "must be a number" in (hub.last_error or ""), str(hub.last_error))
    w.stop()


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

    check("controller rejects a bad UDP port", vc.setCustomUrl("udp_h265", "70000") is False)
    check("controller rejects a file as capture device", vc.setCustomUrl("webcam", "movie.mp4") is False)
    check("controller rejects a file as stream URL", vc.setCustomUrl("url", "file:///etc/passwd") is False)
    check("controller accepts a UDP port", vc.setCustomUrl("udp_h265", "5601") is True)
    vc.setMode("udp_h265")
    check("controller labels the H.265 source", vc.sourceLabel == "udp_h265:5601", vc.sourceLabel)
    cfg.set_custom_url("udp_h265", "")

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
    test_udp_h265()
    test_udp_ts()
    test_udp_auto()
    test_stream_url()
    test_url_rejects_files()
    test_capture_devices()
    test_capture_rejects_files()
    test_controller()
    print(f"\n{'VIDEO TESTS PASSED' if not FAILURES else str(len(FAILURES)) + ' FAILURES'}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
