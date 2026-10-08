#!/usr/bin/env python3
"""Record an MP4 walkthrough of the Ghost Handler HUD (headless, simulated flight).

Boots the app offscreen (software rendering — same path as the smoke test),
captures window frames while driving the UI through its milestones, then
encodes build/gcs-demo.mp4 with ffmpeg. Phase stills land in
build/screenshots/:

    01-flight.png      flight view: video-first HUD (horizon, tapes, actions)
    02-map.png         expanded map with the FLIGHT DATA panel
    03-planner.png     mission planner with map tools
    04-video-panel.png video source panel drawer
    05-final.png       settled flight HUD

Usage:
    .venv-desktop/bin/python tools/record_demo.py [--seconds 12] [--fps 10]
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Must be set before Qt is imported.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=12.0)
    ap.add_argument("--fps", type=float, default=10.0)
    args = ap.parse_args()
    if shutil.which("ffmpeg") is None:
        print("FAIL: ffmpeg not found on PATH (needed for MP4 encode)", file=sys.stderr)
        return 1

    total_frames = max(2, int(args.seconds * args.fps))
    frames_dir = ROOT / "build" / "demo-frames"
    shots_dir = ROOT / "build" / "screenshots"
    frames_dir.mkdir(parents=True, exist_ok=True)
    shots_dir.mkdir(parents=True, exist_ok=True)
    for old in frames_dir.glob("f*.png"):
        old.unlink()

    from PySide6.QtCore import QTimer
    from PySide6.QtQuick import QQuickWindow

    state = {"frame": 0}

    def driver(root, app, ctrl) -> None:
        f_map = int(total_frames * 0.30)
        f_planner = int(total_frames * 0.55)
        f_video_open = int(total_frames * 0.75)
        f_back = int(total_frames * 0.90)

        def grab(path: Path) -> None:
            win = root if isinstance(root, QQuickWindow) else root.findChild(QQuickWindow)
            if win is None:
                return
            win.grabWindow().save(str(path))

        stills = {
            8: "01-flight.png",
            f_map + int(total_frames * 0.08): "02-map.png",
            f_planner + int(total_frames * 0.08): "03-planner.png",
            f_video_open + int(total_frames * 0.10): "04-video-panel.png",
            total_frames - 2: "05-final.png",
        }

        def tick() -> None:
            f = state["frame"]
            if f == f_map:
                root.setProperty("viewMode", "map")
            if f == f_planner:
                root.setProperty("viewMode", "planner")
            if f == f_video_open:
                root.setProperty("videoOpen", True)
            if f == f_back:
                root.setProperty("videoOpen", False)
                root.setProperty("viewMode", "flight")
            if f in stills:
                grab(shots_dir / stills[f])
            grab(frames_dir / f"f{f:04d}.png")
            state["frame"] += 1
            if state["frame"] % 30 == 0:
                print(f"  frame {state['frame']}/{total_frames}", flush=True)
            if state["frame"] >= total_frames:
                app.quit()

        timer = QTimer(app)  # parented: a local QTimer dies before exec runs
        timer.setInterval(int(1000 / args.fps))
        timer.timeout.connect(tick)
        timer.start()

    from app.application import run

    rc = run(app_root=ROOT, driver=driver)
    if rc != 0:
        print(f"FAIL: app exited {rc}", file=sys.stderr)
        return 1
    n = state["frame"]
    print(f"captured {n} frames -> {frames_dir.relative_to(ROOT)}")

    out = ROOT / "build" / "gcs-demo.mp4"
    enc = subprocess.run(
        ["ffmpeg", "-y", "-framerate", str(args.fps),
         "-i", str(frames_dir / "f%04d.png"),
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "23",
         "-movflags", "+faststart", str(out)],
        capture_output=True, text=True, timeout=300,
    )
    if enc.returncode != 0 or not out.exists() or out.stat().st_size < 10_000:
        print("FAIL: ffmpeg encode", file=sys.stderr)
        print(enc.stderr[-2000:], file=sys.stderr)
        return 1
    print(f"PASS: {out.relative_to(ROOT)} ({out.stat().st_size // 1024} KiB, "
          f"{n} frames @ {args.fps:.0f} fps)")
    for p in sorted(shots_dir.glob("*.png")):
        print(f"  still: {p.relative_to(ROOT)} ({p.stat().st_size // 1024} KiB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
