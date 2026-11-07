"""Video acquisition worker — desktop port of the proven GCS video stack.

Mirrors GCS/video/ semantics with one thread per family:

    udp_rtp  → RtpH264Receiver-style SDP/ffmpeg demuxer (rtp_receiver.py):
               UDP :5600 → synthetic SDP → PyAV demux → H.264 decode → hub.
               This is how PX4 SITL (gz gstreamer plugin) and most drones
               stream; the QGC convention port 5600 is probed first in auto.
    udp_h265 → same path with an H.265 SDP (OpenIPC and other digital FPV links)
    udp_ts   → MPEG-TS over UDP (video encoders behind IP radios)
    udp_auto → listens on one UDP port and works out which of the three above
               is arriving, so a link need not be named to be shown
    url      → any network stream FFmpeg reads (rtsp, rtmp, srt, udp, rtp,
               http/HLS), for systems that fit none of the above
    webcam   → OpenCV VideoCapture (source_detector.py / webrtc.py); this is
               also how analog receivers and HDMI output reach the app, through
               a USB capture dongle that appears as a camera
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
import re
import socket
import sys
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
{codec}
"""

SDP_CODECS = {
    "udp_rtp": "a=rtpmap:96 H264/90000\na=fmtp:96 packetization-mode=1",
    "udp_h265": "a=rtpmap:96 H265/90000",
}

# A capture source must be a camera index or a V4L2 node, never a file path.
_CAPTURE_PATH = re.compile(r"^/dev/video\d+$")
# cap.read() fails this many times in a row (~5 s) → reopen. An unplugged USB
# capture dongle keeps failing forever on the old handle, so replugging it
# would otherwise never bring the picture back.
MAX_READ_FAILURES = 25

# Stream URL source: network protocols only. FFmpeg would otherwise also read
# local files, concat: and subfile: lists from a URL the operator pasted.
URL_SCHEMES = ("rtsp", "rtsps", "rtmp", "rtmps", "srt", "udp", "rtp", "tcp", "http", "https")
URL_PROTOCOLS = "tcp,udp,rtp,rtsp,rtsps,rtmp,rtmps,rtmpt,srt,http,https,tls,crypto,hls,httpproxy"

H264_RTP_TYPES = {1, 5, 7, 8, 24, 28}       # slice, IDR, SPS, PPS, STAP-A, FU-A
H265_RTP_TYPES = set(range(0, 22)) | set(range(32, 41)) | {48, 49}


def classify_udp_payload(data: bytes) -> str | None:
    """One UDP datagram → "udp_ts", "udp_rtp" (H.264), "udp_h265" or None.

    MPEG-TS arrives as whole 188-byte packets starting with the 0x47 sync
    byte. RTP is told apart by the first byte(s) of the NAL unit: a byte can
    pass for either codec, so callers decide on a majority of datagrams."""
    if len(data) >= 188 and len(data) % 188 == 0 and data[0] == 0x47 and data[188 * (len(data) // 188 - 1)] == 0x47:
        return "udp_ts"
    if len(data) < 14 or data[0] >> 6 != 2:
        return None
    offset = 12 + 4 * (data[0] & 0x0F)
    if data[0] & 0x10:                       # header extension
        if len(data) < offset + 4:
            return None
        offset += 4 + 4 * int.from_bytes(data[offset + 2:offset + 4], "big")
    if len(data) < offset + 2:
        return None
    b0, b1 = data[offset], data[offset + 1]
    h264 = not b0 & 0x80 and b0 & 0x60 and (b0 & 0x1F) in H264_RTP_TYPES
    h265 = not b0 & 0x81 and (b1 & 0x07) >= 1 and ((b0 >> 1) & 0x3F) in H265_RTP_TYPES
    if h264 and not h265:
        return "udp_rtp"
    if h265 and not h264:
        return "udp_h265"
    return None


def detected_label(kind: str) -> str:
    return {"udp_rtp": "H.264 RTP", "udp_h265": "H.265 RTP", "udp_ts": "MPEG-TS"}.get(kind, "")

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


def redact_url(url: str) -> str:
    """Hide the password of rtsp://user:pass@host/... for anything shown on
    screen or printed; camera credentials must not end up in screenshots,
    screen recordings or field logs."""
    try:
        parts = urlsplit(url)
        if not parts.password:
            return url
        host = parts.hostname or ""
        if ":" in host:
            host = f"[{host}]"
        netloc = f"{parts.username or ''}:***@{host}" + (f":{parts.port}" if parts.port else "")
        return parts._replace(netloc=netloc).geturl()
    except ValueError:
        return "<invalid url>"


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

    spec: {"kind": "udp_rtp"|"udp_h265"|"udp_ts"|"mjpeg"|"rtsp"|"webcam"|"test",
           "port"?: int, "url"?: str, "index"?: int}
    """

    def __init__(self, hub: FrameHub) -> None:
        self._hub = hub
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self.kind = "test"
        self.detail = ""
        self.detected = ""  # udp_auto: the transport it found

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
            if self.kind == "udp_auto":
                self._run_udp_auto(int(self.detail or 5600))
            elif self.kind == "url":
                self._run_url(self.detail)
            elif self.kind in SDP_CODECS:
                port = int(self.detail or 5600)
                self._run_udp_rtp(port, self.kind)
            elif self.kind == "udp_ts":
                self._run_udp_ts(int(self.detail or 5000))
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
                # MSMF, which CAP_ANY picks first on Windows, opens slowly and
                # refuses many capture dongles; DirectShow is the reliable path.
                backend = cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY
                self._run_capture(cv2, self._camera_index(self.detail), backend)
            else:
                self._stop.wait(0.5)

    def _emit(self, img) -> None:
        self._hub.publish(img)

    def _sniff_udp(self, port: int, window: float = 2.0) -> str | None:
        """Listen briefly and vote on what the datagrams carry."""
        votes: dict[str, int] = {}
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        except OSError as exc:
            self._hub.last_error = f"auto: {exc}"
            return None
        try:
            sock.bind(("0.0.0.0", port))
            sock.settimeout(0.25)
            deadline = time.monotonic() + window
            seen = 0
            while time.monotonic() < deadline and seen < 60:
                if self._stop.is_set() or self._wake.is_set():
                    return None
                try:
                    data = sock.recv(65536)
                except socket.timeout:
                    continue
                seen += 1
                kind = classify_udp_payload(data)
                if kind:
                    votes[kind] = votes.get(kind, 0) + 1
        except OSError as exc:
            self._hub.last_error = f"auto: UDP {port}: {exc}"
            self._stop.wait(1.0)
            return None
        finally:
            sock.close()
        if not votes:
            self._hub.last_error = f"auto: no stream on UDP {port} yet"
            return None
        return max(votes, key=votes.get)

    def _run_udp_auto(self, port: int) -> None:
        """Find out what arrives on the port, play it, and look again once
        that stream ends (the air unit may have been switched to H.265)."""
        while not self._stop.is_set() and not self._wake.is_set():
            kind = self._sniff_udp(port)
            if kind is None:
                continue
            self.detected = detected_label(kind)
            if kind == "udp_ts":
                self._run_udp_ts(port, retry=False)
            else:
                self._run_udp_rtp(port, kind, retry=False)
            self.detected = ""

    def _run_url(self, url: str) -> None:
        """Any network stream FFmpeg can read, decoded through PyAV."""
        try:
            import av
        except Exception as exc:  # noqa: BLE001 — decoder missing must not kill the thread
            self._hub.last_error = f"url: PyAV unavailable ({exc})"
            self._stop.wait(2.0)
            return
        if urlsplit(url).scheme.lower() not in URL_SCHEMES:
            self._hub.last_error = "url: enter a stream URL (rtsp, rtmp, srt, udp, rtp, http)"
            self._stop.wait(2.0)
            return
        source = url
        if urlsplit(url).scheme.lower() == "udp" and "overrun_nonfatal" not in url:
            # While FFmpeg probes the stream, a fast sender fills the receive
            # FIFO; by default that overrun is a fatal I/O error. Same
            # settings as the MPEG-TS source.
            source = url + ("&" if "?" in url else "?") + "overrun_nonfatal=1&fifo_size=65536"
        self._demux(av, source, None, {
            "timeout": "5000000",
            "rw_timeout": "5000000",
            "protocol_whitelist": URL_PROTOCOLS,
            "fflags": "nobuffer",
            "flags": "low_delay",
        }, "url")

    def _run_udp_rtp(self, port: int, kind: str = "udp_rtp", retry: bool = True) -> None:
        """UDP H.264/H.265 RTP → SDP file → PyAV demux/decode (port of
        GCS/video/rtp_receiver.py, same reopen/timeout semantics)."""
        try:
            import av
        except Exception as exc:  # noqa: BLE001 — decoder missing must not kill the thread
            self._hub.last_error = f"rtp: PyAV unavailable ({exc})"
            self._stop.wait(2.0)
            return
        if not 1 <= port <= 65535:
            self._hub.last_error = f"rtp: invalid UDP port {port}"
            self._stop.wait(2.0)
            return
        # mkstemp (O_EXCL, 0600, random name): the old fixed name in /tmp could
        # be pre-created as a symlink by another local user, making this app
        # overwrite a file of the operator's, or swapped for a hostile SDP.
        try:
            fd, sdp_path = tempfile.mkstemp(prefix="gh_video_rtp_", suffix=".sdp")
            with os.fdopen(fd, "w") as fh:
                fh.write(SDP_TEMPLATE.format(port=port, codec=SDP_CODECS[kind]))
        except OSError as exc:
            self._hub.last_error = f"rtp: cannot write SDP file ({exc})"
            self._stop.wait(2.0)
            return
        try:
            self._demux(av, sdp_path, "sdp", {
                "timeout": "2000000",
                "protocol_whitelist": "file,udp,rtp",
                "buffer_size": "262144",
                "fflags": "nobuffer",
                "flags": "low_delay",
                "max_delay": "100000",
            }, f"rtp:{port}", retry)
        finally:
            try:
                os.unlink(sdp_path)
            except OSError:
                pass

    def _run_udp_ts(self, port: int, retry: bool = True) -> None:
        """MPEG-TS over UDP → PyAV demux/decode; the codec comes from the
        stream itself, so H.264 and H.265 encoders both work."""
        try:
            import av
        except Exception as exc:  # noqa: BLE001 — decoder missing must not kill the thread
            self._hub.last_error = f"mpegts: PyAV unavailable ({exc})"
            self._stop.wait(2.0)
            return
        if not 1 <= port <= 65535:
            self._hub.last_error = f"mpegts: invalid UDP port {port}"
            self._stop.wait(2.0)
            return
        self._demux(av, f"udp://0.0.0.0:{port}?overrun_nonfatal=1&fifo_size=65536", "mpegts", {
            "timeout": "2000000",
            "protocol_whitelist": "udp",
            "fflags": "nobuffer",
            "flags": "low_delay",
        }, f"mpegts:{port}", retry)

    def _demux(self, av, source: str, fmt: str | None, options: dict, tag: str, retry: bool = True) -> None:
        """Decode `source` into the hub. retry=False returns after the first
        session ends or fails, so udp_auto can look at the port again."""
        while not self._stop.is_set() and not self._wake.is_set():
            try:
                container = av.open(source, format=fmt, options=options)
            except Exception as exc:  # noqa: BLE001 — no stream (yet); keep probing
                # FFmpeg quotes the URL in its errors; keep passwords off screen.
                self._hub.last_error = f"{tag}: {exc}".replace(source, redact_url(source))
                self._stop.wait(1.0)
                if not retry:
                    return
                continue
            try:
                stream = next((s for s in container.streams if s.type == "video"), None)
                if stream is None:
                    raise RuntimeError("no video stream in this source")
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
                self._hub.last_error = f"{tag} stream ended; reopening"
                self._stop.wait(1.0)
            if not retry:
                return

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
        # urlopen also speaks file:// and ftp://. The controller validates the
        # scheme, but a URL restored from the settings file never went through
        # it, so enforce it at the point of use.
        if urlsplit(url).scheme.lower() not in ("http", "https"):
            self._hub.last_error = "mjpeg: URL must start with http:// or https://"
            self._stop.wait(2.0)
            return
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
                if api_preference == cv2.CAP_FFMPEG and not (
                        isinstance(source, str) and source.lower().startswith(("rtsp://", "rtsps://"))):
                    # FFmpeg would happily open local files, concat: or
                    # subfile: here; this path is for network cameras only.
                    self._hub.last_error = "rtsp: URL must start with rtsp://"
                    self._stop.wait(2.0)
                    return
                if api_preference != cv2.CAP_FFMPEG and isinstance(source, str) \
                        and not _CAPTURE_PATH.match(source):
                    # A value restored from the settings file never went through
                    # the controller's check, and CAP_ANY would open files too.
                    self._hub.last_error = "capture: device must be a number or /dev/videoN"
                    self._stop.wait(2.0)
                    return
                if isinstance(source, str) and source.lower().startswith("rtsp://"):
                    parts = urlsplit(source)
                    if parts.hostname and not _tcp_reachable(parts.hostname, parts.port or 554):
                        self._hub.last_error = f"rtsp host unreachable: {parts.hostname}:{parts.port or 554}"
                        self._stop.wait(1.0)
                        continue
                cap = cv2.VideoCapture(source, api_preference)
                if not cap.isOpened():
                    self._hub.last_error = f"open failed: {redact_url(str(source))} (retrying)"
                    self._stop.wait(1.0)
                    continue
            except Exception as exc:  # noqa: BLE001
                self._hub.last_error = str(exc)
                self._stop.wait(1.0)
                continue
            failures = 0
            try:
                while not self._stop.is_set() and not self._wake.is_set():
                    ok, img = cap.read()
                    if not ok or img is None:
                        self._hub.last_error = "capture returned no frame"
                        failures += 1
                        if failures >= MAX_READ_FAILURES:
                            break
                        self._stop.wait(0.2)
                        continue
                    failures = 0
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
