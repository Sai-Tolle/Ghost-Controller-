"""Video acquisition worker — desktop port of the proven GCS video stack.

Mirrors GCS/video/ semantics with one thread per family:

    udp_rtp  → RtpH264Receiver-style SDP/ffmpeg demuxer (rtp_receiver.py):
               UDP :5600 → synthetic SDP → PyAV demux → H.264 decode → hub.
               This is how PX4 SITL (gz gstreamer plugin) and most drones
               stream; the QGC convention port 5600 is probed first in auto.
    webcam   → OpenCV VideoCapture (source_detector.py / webrtc.py)
    rtsp     → OpenCV VideoCapture with CAP_FFMPEG (fast TCP pre-check first,
               exactly like source_detector._rtsp_reachable)
    mjpeg    → multipart/x-mixed-replace reader (webrtc._mjpeg_reader)
    test     → built-in synthetic pattern (count-up + moving bars) so the
               pipeline, panel and tests work with zero hardware

Decoded frames land in the local FrameHub (latest-wins, like
GCS/vision/frames.py) and are consumed by VideoController on the Qt main
thread. Nothing in here touches Qt objects — it dies with the process like
the backend workers.
"""
from __future__ import annotations

import os
import socket
import tempfile
import threading
import time
from urllib.parse import urlsplit

SDP_TEMPLATE = """v=0
o=- 0 0 IN IP4 0.0.0.0
s=GCS Video
c=IN IP4 0.0.0.0
t=0 0
m=video {port} RTP/AVP 96
a=rtpmap:96 H264/90000
a=fmtp:96 packetization-mode=1
"""

FALLBACK_WIDTH, FALLBACK_HEIGHT = 640, 480   # test-pattern size only
MAX_WIDTH, MAX_HEIGHT = 1920, 1080           # decode cap; native aspect is preserved


class FrameHub:
    """Latest-wins frame store + liveness (clean-room reimplementation of
    GCS/vision/frames.py FrameHub, trimmed to what the desktop needs)."""

    def __init__(self, stale_after: float = 3.0) -> None:
        self._lock = threading.Lock()
        self._frame = None
        self._ts = 0.0
        self._stale_after = stale_after
        self.frames = 0
        self.last_error: str | None = None

    def publish(self, frame) -> None:
        with self._lock:
            self._frame = frame
            self._ts = time.time()
            self.frames += 1

    def latest(self, max_age: float | None = None):
        with self._lock:
            fresh = (time.time() - self._ts) <= (self._stale_after if max_age is None else max_age)
            return self._frame.copy() if fresh and self._frame is not None else None

    def age(self) -> float:
        with self._lock:
            return time.time() - self._ts


def _tcp_reachable(host: str, port: int, timeout: float = 1.0) -> bool:
    """Cheap TCP pre-check before an expensive RTSP/HTTP handshake (same
    trick as GCS/video/source_detector.py)."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


class VideoWorker:
    """Single background worker; `restart(spec)` switches source family.

    spec: {"kind": "udp_rtp"|"mjpeg"|"rtsp"|"webcam"|"test",
           "port"?: int, "url"?: str, "index"?: int}
    """

    def __init__(self, hub: FrameHub) -> None:
        self._hub = hub
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self.kind = "test"
        self.detail = ""

    # ---- lifecycle ----

    def start(self, spec: dict) -> None:
        # NOTE: callers set `.detail` BEFORE start() — start must not reset it.
        self.kind = spec.get("kind", "test")
        # Re-arm: start() must work again after stop() (e.g. controller
        # restart flows), so clear the shutdown flag set by a previous stop.
        self._stop.clear()
        self._wake.set()

    def stop(self, timeout: float = 3.0) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        self._thread = None

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    # ---- worker loop ----

    def _loop(self) -> None:
        current_kind = None
        cv2 = None
        try:
            import cv2  # numpy+opencv wheels for py3.10; deferred so boot never hard-requires them
        except Exception as exc:  # noqa: BLE001 — reported through status, not a crash
            self._hub.last_error = f"cv2 unavailable: {exc}"
            cv2 = None
        while not self._stop.is_set():
            if not self._wake.is_set():
                self._wake.wait(0.5)
                continue
            self._wake.clear()
            if self._stop.is_set():
                break
            if self.kind == "udp_rtp":
                port = int(self.detail or 5600)
                self._run_udp_rtp(port)
            elif self.kind == "test":
                self._run_test()
            elif cv2 is None:
                self._hub.last_error = "opencv not installed — rtsp/mjpeg/webcam unavailable"
                self._stop.wait(1.0)
            elif self.kind == "mjpeg":
                self._run_mjpeg(self.detail)
            elif self.kind == "rtsp":
                self._run_capture(cv2, self.detail, cv2.CAP_FFMPEG)
            elif self.kind == "webcam":
                self._run_capture(cv2, self._camera_index(self.detail), cv2.CAP_ANY)
            else:
                self._stop.wait(0.5)

    def _emit(self, img) -> None:
        self._hub.publish(img)

    def _run_udp_rtp(self, port: int) -> None:
        """UDP H.264 RTP → SDP file → PyAV demux/decode (port of
        GCS/video/rtp_receiver.py, same reopen/timeout semantics)."""
        try:
            import av
        except Exception as exc:  # noqa: BLE001 — decoder missing must not kill the thread
            self._hub.last_error = f"rtp: PyAV unavailable ({exc})"
            self._stop.wait(2.0)
            return
        sdp_path = os.path.join(tempfile.gettempdir(), f"gh_video_rtp_{os.getpid()}.sdp")
        try:
            with open(sdp_path, "w") as fh:
                fh.write(SDP_TEMPLATE.format(port=port))
        except OSError as exc:
            self._hub.last_error = f"rtp: cannot write SDP file ({exc})"
            self._stop.wait(2.0)
            return
        while not self._stop.is_set() and not self._wake.is_set():
            try:
                container = av.open(
                    sdp_path,
                    format="sdp",
                    options={
                        "timeout": "2000000",
                        "protocol_whitelist": "file,udp,rtp",
                        "buffer_size": "262144",
                        "fflags": "nobuffer",
                        "flags": "low_delay",
                        "max_delay": "100000",
                    },
                )
            except Exception as exc:  # noqa: BLE001 — no stream (yet); keep probing
                self._hub.last_error = f"rtp: {exc}"
                self._stop.wait(1.0)
                continue
            try:
                stream = next((s for s in container.streams if s.type == "video"), None)
                if stream is None:
                    raise RuntimeError("no video stream in SDP session")
                for packet in container.demux(stream):
                    if self._stop.is_set() or self._wake.is_set():
                        break
                    if packet.dts is None:
                        continue
                    try:
                        for frame in packet.decode():
                            img = frame.to_ndarray(format="bgr24")
                            h, w = img.shape[:2]
                            if w > MAX_WIDTH or h > MAX_HEIGHT:
                                img = _resize_fit(img, MAX_WIDTH, MAX_HEIGHT)
                            self._emit(img)
                    except Exception as exc:  # noqa: BLE001 — count, don't die
                        self._hub.last_error = str(exc)
            except Exception as exc:  # noqa: BLE001
                self._hub.last_error = str(exc)
            finally:
                try:
                    container.close()
                except Exception:
                    pass
            if not self._stop.is_set() and not self._wake.is_set():
                self._hub.last_error = f"rtp:{port} stream ended; reopening"
                self._stop.wait(1.0)

    def _run_test(self) -> None:
        """Synthetic source: static + moving pattern with a frame counter —
        deterministic for tests (HUD stamp == frame index)."""
        import numpy as np

        idx = 0
        t0 = time.time()
        while not self._stop.is_set() and not self._wake.is_set():
            img = np.zeros((FALLBACK_HEIGHT, FALLBACK_WIDTH, 3), dtype=np.uint8)
            img[:, :, 0] = 24  # dark blue-ish base (BGR)
            img[:, :, 1] = 16
            bar = int((time.time() - t0) * 60) % FALLBACK_WIDTH
            img[:, max(0, bar - 2):bar + 3, 2] = 200  # sweeping red bar
            # Big frame counter so a human (and tests) can verify motion.
            text = f"GH-TEST {idx:05d}"
            _draw_text(img, 12, 40, text)
            self._emit(img)
            idx += 1
            self._stop.wait(1.0 / 30.0)

    def _run_mjpeg(self, url: str) -> None:
        import cv2
        import numpy as np
        from urllib.request import urlopen

        buf = b""
        while not self._stop.is_set() and not self._wake.is_set():
            try:
                # stdlib streaming GET — no requests dependency; the multipart
                # boundary scan matches CameraTrack._mjpeg_reader exactly.
                with urlopen(url, timeout=10) as resp:
                    ctype = resp.headers.get("Content-Type", "")
                    if "multipart/x-mixed-replace" not in ctype and "image/jpeg" not in ctype:
                        raise RuntimeError(f"not an MJPEG endpoint ({ctype or 'no content-type'})")
                    while not self._stop.is_set() and not self._wake.is_set():
                        chunk = resp.read(1024)
                        if not chunk:
                            raise RuntimeError("mjpeg stream ended")
                        buf += chunk
                        a, b = buf.find(b"\xff\xd8"), buf.find(b"\xff\xd9")
                        if a != -1 and b != -1 and b > a:
                            jpg = buf[a:b + 2]
                            buf = buf[b + 2:]
                            img = cv2.imdecode(np.frombuffer(jpg, dtype=np.uint8), cv2.IMREAD_COLOR)
                            if img is not None:
                                h, w = img.shape[:2]
                                if w > MAX_WIDTH or h > MAX_HEIGHT:
                                    img = _resize_fit(img, MAX_WIDTH, MAX_HEIGHT)
                                self._emit(img)
                        elif len(buf) > 8 * 1024 * 1024:
                            # SOI without EOI (bogus endpoint) — drop instead
                            # of growing without bound.
                            buf = buf[-1024:]
            except Exception as exc:  # noqa: BLE001 — reconnect like CameraTrack
                self._hub.last_error = f"mjpeg: {exc}"
                self._stop.wait(1.0)

    @staticmethod
    def _camera_index(detail: str):
        """Webcam source: numeric string → int index (OpenCV treats "0" as a
        filename), a device path (/dev/video0) stays a string."""
        text = str(detail or "0").strip()
        try:
            return int(text)
        except ValueError:
            return text

    def _run_capture(self, cv2, source, api_preference: int) -> None:
        """OpenCV capture loop for rtsp (CAP_FFMPEG) and webcam (CAP_ANY);
        mirrors source_detector + CameraTrack's cap.read() path. Retries
        forever (1 s pause between attempts) until stopped or the operator
        switches source — a single failed open must not dead the family."""
        while not self._stop.is_set() and not self._wake.is_set():
            try:
                if isinstance(source, str) and source.startswith("rtsp://"):
                    parts = urlsplit(source)
                    if parts.hostname and not _tcp_reachable(parts.hostname, parts.port or 554):
                        self._hub.last_error = f"rtsp host unreachable: {parts.hostname}:{parts.port or 554}"
                        self._stop.wait(1.0)
                        continue
                cap = cv2.VideoCapture(source, api_preference)
                if not cap.isOpened():
                    self._hub.last_error = f"open failed: {source} (retrying)"
                    self._stop.wait(1.0)
                    continue
            except Exception as exc:  # noqa: BLE001
                self._hub.last_error = str(exc)
                self._stop.wait(1.0)
                continue
            try:
                while not self._stop.is_set() and not self._wake.is_set():
                    ok, img = cap.read()
                    if not ok or img is None:
                        self._hub.last_error = "capture returned no frame"
                        self._stop.wait(0.2)
                        continue
                    h, w = img.shape[:2]
                    if w > MAX_WIDTH or h > MAX_HEIGHT:
                        img = _resize_fit(img, MAX_WIDTH, MAX_HEIGHT)
                    self._emit(img)
            except Exception as exc:  # noqa: BLE001 — decode hiccup: reopen, don't die
                self._hub.last_error = str(exc)
            finally:
                try:
                    cap.release()
                except Exception:
                    pass
            # fall through: outer loop retries the open while not stopped


# ---- tiny numpy helpers (no cv2 dependency for the test source) ----------

def _resize_fit(img, max_w: int, max_h: int):
    """Downscale only when larger than the cap, keeping the aspect ratio.
    Every source used to be force-resized to 640x480, which stretched 16:9
    video into 4:3 and threw away resolution — fatal for a video-first GCS."""
    h, w = img.shape[:2]
    scale = min(max_w / w, max_h / h, 1.0)
    if scale >= 1.0:
        return img
    return _resize(img, max(2, int(w * scale) // 2 * 2), max(2, int(h * scale) // 2 * 2))


def _resize(img, width: int, height: int):
    """Nearest-neighbor resize with plain numpy — avoids requiring cv2 for
    the test/RTP paths (cv2.resize used only where cv2 is already loaded)."""
    import numpy as np

    h, w = img.shape[:2]
    if (w, h) == (width, height):
        return img
    yi = (np.arange(height) * (h / height)).astype(int).clip(0, h - 1)
    xi = (np.arange(width) * (w / width)).astype(int).clip(0, w - 1)
    return img[np.ix_(yi, xi)]


def _draw_text(img, x: int, y: int, text: str) -> None:
    """5x7 bitmap font stamp — enough for 'GH-TEST 00123', no cv2 needed."""
    GLYPHS = {
        "0": ["01110", "10001", "10011", "10101", "11001", "10001", "01110"],
        "1": ["00100", "01100", "00100", "00100", "00100", "00100", "01110"],
        "2": ["01110", "10001", "00001", "00010", "00100", "01000", "11111"],
        "3": ["11110", "00001", "00001", "01110", "00001", "00001", "11110"],
        "4": ["00010", "00110", "01010", "10010", "11111", "00010", "00010"],
        "5": ["11111", "10000", "11110", "00001", "00001", "10001", "01110"],
        "6": ["00110", "01000", "10000", "11110", "10001", "10001", "01110"],
        "7": ["11111", "00001", "00010", "00100", "01000", "01000", "01000"],
        "8": ["01110", "10001", "10001", "01110", "10001", "10001", "01110"],
        "9": ["01110", "10001", "10001", "01111", "00001", "00010", "01100"],
        "A": ["01110", "10001", "10001", "11111", "10001", "10001", "10001"],
        "B": ["11110", "10001", "10001", "11110", "10001", "10001", "11110"],
        "C": ["01110", "10001", "10000", "10000", "10000", "10001", "01110"],
        "D": ["11110", "10001", "10001", "10001", "10001", "10001", "11110"],
        "E": ["11111", "10000", "10000", "11110", "10000", "10000", "11111"],
        "F": ["11111", "10000", "10000", "11110", "10000", "10000", "10000"],
        "G": ["01110", "10001", "10000", "10111", "10001", "10001", "01111"],
        "H": ["10001", "10001", "10001", "11111", "10001", "10001", "10001"],
        "I": ["01110", "00100", "00100", "00100", "00100", "00100", "01110"],
        "-": ["00000", "00000", "00000", "01110", "00000", "00000", "00000"],
        "T": ["11111", "00100", "00100", "00100", "00100", "00100", "00100"],
        "S": ["01111", "10000", "10000", "01110", "00001", "00001", "11110"],
        " ": ["00000", ] * 7,
    }
    cx = x
    for ch in text.upper():
        glyph = GLYPHS.get(ch, GLYPHS[" "])
        for gy, row in enumerate(glyph):
            for gx, bit in enumerate(row):
                if bit == "1":
                    img[y + gy, cx + gx] = (240, 240, 240)
        cx += 6  # 5 px glyph + 1 px space
