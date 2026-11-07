"""USB capture device discovery for the capture video source.

Analog receivers and HDMI capture cards reach the desktop as ordinary
UVC/V4L2 cameras, so this is what lets an operator pick one by name.

Linux reads names from sysfs without touching the hardware. Elsewhere OpenCV
offers no names or list, so each index is opened once: that is slow and may
light a camera LED, which is why callers run this on demand off the GUI thread.
"""
from __future__ import annotations

import sys
from pathlib import Path

SYSFS_VIDEO = Path("/sys/class/video4linux")
# Raspberry Pi media blocks register as video nodes but are not cameras.
_NOT_CAPTURE = ("bcm2835-", "rpivid", "rp1-cfe", "pispbe")
MAX_PROBE_INDEX = 6


def _read(path: Path) -> str:
    try:
        return path.read_text().strip()
    except OSError:
        return ""


def _linux_devices(sysfs: Path) -> list[dict]:
    found = []
    for node in sysfs.glob("video*"):
        number = node.name[len("video"):]
        # One physical camera registers several nodes; index 0 is the picture,
        # the others carry metadata and cannot be opened for video.
        if not number.isdecimal() or _read(node / "index") not in ("", "0"):
            continue
        name = _read(node / "name") or node.name
        if name.startswith(_NOT_CAPTURE):
            continue
        found.append((int(number), name))
    return [{"id": str(n), "label": f"{name} (video{n})"} for n, name in sorted(found)]


def _probed_devices(selected: str) -> list[dict]:
    import cv2

    backend = cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY
    found = []
    misses = 0
    for index in range(MAX_PROBE_INDEX):
        # The selected device may be streaming right now, and capture devices
        # usually allow one user at a time: list it without opening it again.
        if str(index) == selected:
            ok = True
        else:
            cap = cv2.VideoCapture(index, backend)
            ok = cap.isOpened()
            cap.release()
        if ok:
            found.append({"id": str(index), "label": f"Capture device {index}"})
            misses = 0
        else:
            misses += 1
            if misses >= 2:
                break
    return found


def list_capture_devices(selected: str = "", sysfs: Path = SYSFS_VIDEO) -> list[dict]:
    """[{id, label}], where id is what VideoController.setCustomUrl("webcam", id) takes."""
    if sysfs.is_dir():
        return _linux_devices(sysfs)
    return _probed_devices(selected)
