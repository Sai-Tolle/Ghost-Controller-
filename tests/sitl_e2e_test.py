#!/usr/bin/env python3
"""End-to-end SITL test: PROVEN backend + desktop video vs PX4 SITL (gz).

Orchestrates everything on this machine:
  1. installs the gcs_cam model (symlink) + airframe into ~/PX4-Autopilot
     (idempotent; --cleanup removes them again)
  2. boots PX4 SITL: prebuilt binary, vehicle_test_lite world (Zurich home),
     gz gstreamer camera → RTP/H.264 on UDP 5600
  3. boots the desktop BackendRuntime (same worker stack as the app) on
     udpin:127.0.0.1:14550 (PX4's GCS UDP port)
  4. asserts: connection event, telemetry events, preflight events
  5. asserts: real RTP/H.264 video frames decode through VideoWorker
  6. GH_SITL_FLY=1 additionally arms + takes off 25 m via the command
     queue (CommandHandler → command_guard → PX4), verifies climb, lands.

Usage:
    .venv-desktop/bin/python tests/sitl_e2e_test.py [--cleanup]
    GH_SITL_FLY=1 .venv-desktop/bin/python tests/sitl_e2e_test.py
"""
import argparse
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
BACKEND = ROOT / "backend"          # vendored backend (self-contained desktop)
PX4_DIR = Path(os.environ.get("PX4_DIR", Path.home() / "PX4-Autopilot"))
WORLD = BACKEND / "sitl" / "worlds" / "vehicle_test_lite.sdf"
MODEL_SRC = ROOT / "tools" / "sitl" / "gcs_cam"
MODEL_DST = PX4_DIR / "Tools" / "simulation" / "gz" / "models" / "gcs_cam"
# rcS matches airframe files by *${PX4_SIM_MODEL} → filename must end in
# _gz_gcs_cam. The runtime reads etc/init.d-posix from the BUILD dir, with
# ROMFS as the cmake source it re-copies — install into both.
AIRFRAME_NAME = "4030_gz_gcs_cam"
AIRFRAME_DSTS = (
    PX4_DIR / "ROMFS" / "px4fmu_common" / "init.d-posix" / "airframes" / AIRFRAME_NAME,
    PX4_DIR / "build" / "px4_sitl_default" / "etc" / "init.d-posix" / "airframes" / AIRFRAME_NAME,
)

MAV_PORT = 14550          # PX4 SITL GCS UDP port (QGC convention)
RTP_PORT = 5600           # PX4 gz gstreamer camera port (QGC convention)
WORLD_NAME = "vehicle_test_lite"
PX4_WORLDS_DIR = PX4_DIR / "Tools" / "simulation" / "gz" / "worlds"

FAILURES = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(("PASS " if cond else "FAIL ") + name + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


def install_or_cleanup(cleanup: bool) -> None:
    if cleanup:
        for p in (MODEL_DST, *AIRFRAME_DSTS, PX4_WORLDS_DIR / f"{WORLD_NAME}.sdf"):
            if p.is_symlink():
                p.unlink()
                print(f"[cleanup] removed symlink {p}")
            elif p.exists():
                p.unlink()
                print(f"[cleanup] removed {p}")
        return
    if not PX4_DIR.exists():
        sys.exit(f"PX4-Autopilot not found at {PX4_DIR}")
    MODEL_DST.parent.mkdir(parents=True, exist_ok=True)
    if MODEL_DST.is_symlink() or MODEL_DST.exists():
        MODEL_DST.unlink()
    MODEL_DST.symlink_to(MODEL_SRC)
    # Mirror the stock 4001_gz_x500 airframe (known-good x500 geometry
    # params) + correct rc include path (etc/init.d/, NOT init.d-posix/).
    airframe_body = (
        "#!/bin/sh\n"
        "#\n# @name Gazebo gcs_cam (Ghost Handler desktop GCS test airframe)\n"
        "#\n# @type Quadrotor\n#\n"
        "# Installed by GCS-Desktop/tests/sitl_e2e_test.py — safe to delete.\n"
        ". ${R}etc/init.d/rc.mc_defaults\n"
        "PX4_SIMULATOR=${PX4_SIMULATOR:=gz}\n"
        "PX4_GZ_WORLD=${PX4_GZ_WORLD:=default}\n"
        "PX4_SIM_MODEL=${PX4_SIM_MODEL:=gcs_cam}\n"
        "param set-default SIM_GZ_EN 1\n"
        "param set-default CA_AIRFRAME 0\n"
        "param set-default CA_ROTOR_COUNT 4\n"
        "param set-default CA_ROTOR0_PX 0.13\n"
        "param set-default CA_ROTOR0_PY 0.22\n"
        "param set-default CA_ROTOR0_KM  0.05\n"
        "param set-default CA_ROTOR1_PX -0.13\n"
        "param set-default CA_ROTOR1_PY -0.20\n"
        "param set-default CA_ROTOR1_KM  0.05\n"
        "param set-default CA_ROTOR2_PX 0.13\n"
        "param set-default CA_ROTOR2_PY -0.22\n"
        "param set-default CA_ROTOR2_KM -0.05\n"
        "param set-default CA_ROTOR3_PX -0.13\n"
        "param set-default CA_ROTOR3_PY 0.20\n"
        "param set-default CA_ROTOR3_KM -0.05\n"
        "param set-default SIM_GZ_EC_FUNC1 101\n"
        "param set-default SIM_GZ_EC_FUNC2 102\n"
        "param set-default SIM_GZ_EC_FUNC3 103\n"
        "param set-default SIM_GZ_EC_FUNC4 104\n"
        "param set-default SIM_GZ_EC_MIN1 150\n"
        "param set-default SIM_GZ_EC_MIN2 150\n"
        "param set-default SIM_GZ_EC_MIN3 150\n"
        "param set-default SIM_GZ_EC_MIN4 150\n"
        "param set-default SIM_GZ_EC_MAX1 1000\n"
        "param set-default SIM_GZ_EC_MAX2 1000\n"
        "param set-default SIM_GZ_EC_MAX3 1000\n"
        "param set-default SIM_GZ_EC_MAX4 1000\n"
        "param set-default MPC_THR_HOVER 0.60\n"
        "param set-default NAV_DLL_ACT 2\n"
    )
    for dst in AIRFRAME_DSTS:
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(airframe_body)
    print(f"[setup] gcs_cam model + {AIRFRAME_NAME} installed in {PX4_DIR}")


class Sitl:
    """PX4 SITL process (make target launches px4 + gz world together)."""

    def __init__(self) -> None:
        self.proc = None
        self.log_path = ROOT / "build" / "sitl-px4.log"
        self.log_path.parent.mkdir(exist_ok=True)
        self._log_fh = None

    def start(self) -> None:
        # This PX4 version resolves PX4_GZ_WORLD by NAME inside its worlds
        # dir (absolute paths get prefixed+ suffixed). Copy our world in —
        # idempotent; removed again by --cleanup.
        PX4_WORLDS_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(WORLD, PX4_WORLDS_DIR / f"{WORLD_NAME}.sdf")
        env = dict(os.environ)
        env["PX4_GZ_WORLD"] = WORLD_NAME
        env["HEADLESS"] = "1"                     # no gz GUI client
        env["PX4_GZ_SIM_GUI"] = "0"
        self._log_fh = open(self.log_path, "w")
        self.proc = subprocess.Popen(
            ["make", "px4_sitl", "gz_gcs_cam"],
            cwd=str(PX4_DIR), env=env,
            stdout=self._log_fh, stderr=subprocess.STDOUT,
            preexec_fn=os.setsid,                 # own group → clean kill
        )
        print(f"[sitl] launched (pid {self.proc.pid}); log: {self.log_path}")

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            try:
                os.killpg(os.getpgid(self.proc.pid), 15)
            except Exception:
                self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except Exception:
                try:
                    os.killpg(os.getpgid(self.proc.pid), 9)
                except Exception:
                    pass
        if self._log_fh:
            self._log_fh.close()

    def tail(self, n: int = 30) -> str:
        try:
            return "\n".join(self.log_path.read_text(errors="replace").splitlines()[-n:])
        except Exception:
            return "<no log>"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cleanup", action="store_true", help="remove PX4 tree additions")
    ap.add_argument("--no-video", action="store_true")
    args = ap.parse_args()

    install_or_cleanup(args.cleanup)
    if args.cleanup:
        return 0

    os.environ["GH_BACKEND_PATH"] = str(BACKEND)
    os.environ.setdefault("MAVLINK_FALLBACK", f"udpin:127.0.0.1:{MAV_PORT}")
    os.environ["MAVLINK_REQUIRE_CONNECTION"] = "0"
    # Kill any stale local RTP receiver state by using a fresh SDP path (pid suffix).
    os.environ["GCS_TMPDIR"] = "/tmp"

    sitl = Sitl()
    runtime = None
    video_stop = threading.Event()
    try:
        from app.backend.runtime import BackendRuntime

        sitl.start()

        # ---- backend runtime (the app's own stack) -----------------------
        runtime = BackendRuntime(BACKEND)
        events = []
        runtime.subscribe(events.append)
        runtime.start()

        deadline = time.time() + 90   # first boot may compile/download nothing, still slow
        while time.time() < deadline:
            if runtime.shared_state.get()["connected"]:
                break
            time.sleep(0.5)
        check("SITL vehicle connected through BackendRuntime",
              runtime.shared_state.get()["connected"],
              f"tail:\n{sitl.tail(25)}")

        check("connection event observed",
              any(e.get("type") == "connection" for e in events))
        check("telemetry events flowing",
              any(e.get("type") == "telemetry" for e in events))
        check("preflight events flowing",
              any(e.get("type") == "preflight" for e in events))

        # ---- video: real RTP/H.264 from the gz gstreamer plugin -----------
        if not args.no_video:
            from app.video.worker import FrameHub, VideoWorker

            hub = FrameHub()
            worker = VideoWorker(hub)
            worker.detail = str(RTP_PORT)
            worker._thread = threading.Thread(target=worker._loop, daemon=True)
            worker._thread.start()
            worker.start({"kind": "udp_rtp"})

            deadline = time.time() + 45
            while time.time() < deadline and hub.frames < 10:
                time.sleep(0.25)
            check("SITL camera RTP/H.264 frames decoded", hub.frames >= 10,
                  f"frames={hub.frames} err={hub.last_error}")
            if hub.frames:
                frame = hub.latest(max_age=5.0)
                check("SITL frame is 640x480 BGR", frame is not None and frame.shape == (480, 640, 3),
                      f"shape={None if frame is None else frame.shape}")
            worker.stop()
        # ---- optional flight (command path through guard/preflight) -------
        if os.environ.get("GH_SITL_FLY") == "1":
            _fly(runtime, events)

    finally:
        if runtime:
            runtime.stop()
        sitl.stop()
        video_stop.set()

    print(f"\n{'SITL E2E PASSED' if not FAILURES else str(len(FAILURES)) + ' FAILURES'}")
    return 1 if FAILURES else 0


def _fly(runtime, events) -> None:
    """Arm + takeoff to 25 m, verify climb, land. Runs the full PROVEN
    command path (cmd_queue → command_worker → CommandHandler → MAVLink)."""
    from pymavlink import mavutil

    print("[fly] takeoff sequence via cmd_queue")
    runtime.set_mode("HOLD")
    time.sleep(1.5)
    runtime.arm()
    time.sleep(1.0)
    runtime.takeoff(25.0)

    def alt_of() -> float:
        tel = [e for e in events if e.get("type") == "telemetry"]
        if not tel:
            return -1.0
        return float(((tel[-1].get("data") or {}).get("position") or {}).get("alt", -1.0) or -1.0)

    deadline = time.time() + 45
    peak = 0.0
    while time.time() < deadline:
        peak = max(peak, alt_of())
        if peak > 2.0:
            break
        time.sleep(0.5)
    check("vehicle climbed after takeoff", peak > 2.0, f"peak_alt={peak}")

    time.sleep(4.0)  # collect in-flight telemetry
    check("telemetry continues while flying",
          sum(1 for e in events if e.get("type") == "telemetry") > 50)

    runtime.land()
    print("[fly] land commanded; waiting to settle")
    time.sleep(8.0)
    runtime.disarm()


if __name__ == "__main__":
    sys.exit(main())
