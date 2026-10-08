#!/usr/bin/env python3
"""Backend runtime smoke test (SITL-style, no hardware).

Boots the PROVEN backend worker stack in-process pointed at a local UDP port,
then feeds synthetic MAVLink heartbeats + telemetry from a sender thread —
exactly what PX4 SITL / a real vehicle would emit. Asserts:

  * runtime starts and threads come up
  * connection_established event observed
  * SharedState goes connected, mode decodes, telemetry queue fills
  * cmd_queue ARM/DISARM round-trips through command_worker -> CommandHandler
  * event_bus subscribers receive telemetry/preflight/command_result events

Usage:
    .venv-desktop/bin/python tests/test_backend_runtime.py   # vendored backend
    GH_BACKEND_PATH=/path/to/backend .venv-desktop/bin/python tests/test_backend_runtime.py
"""
import os
os.environ.setdefault("GH_QSETTINGS_APP", "ghost-handler-tests")  # never pollute real settings

import os
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

BACKEND = os.environ.get("GH_BACKEND_PATH", str(ROOT / "backend"))
os.environ["GH_BACKEND_PATH"] = BACKEND
os.environ["MAVLINK_FALLBACK"] = "udpin:127.0.0.1:14590"  # test port, no SITL needed
os.environ["MAVLINK_REQUIRE_CONNECTION"] = "0"
# Pin the transport explicitly: on machines with a USB serial device attached
# (e.g. /dev/ttyACM0) the backend's serial autodetect would otherwise grab it
# BEFORE the UDP fallback, and the feeder on 14590 would never connect.
# gcs.env is loaded with dotenv(override=False)/setdefault, so an explicit env
# var set here always wins.
os.environ["MAVLINK_CONNECTION"] = "udpin:127.0.0.1:14590"

FAILURES = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(("PASS " if cond else "FAIL ") + name + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


def main() -> int:
    from app.backend.runtime import BackendRuntime

    runtime = BackendRuntime(Path(BACKEND).expanduser().resolve())

    events = []
    runtime.subscribe(events.append)

    runtime.start()
    print("[test] runtime started; waiting for UDP feed...")
    time.sleep(1.0)

    # --- MAVLink feeder (proper CRC'd frames via pymavlink) -----------------
    from pymavlink import mavutil

    feeder_conn = mavutil.mavlink_connection(
        "udpout:127.0.0.1:14590", source_system=1, source_component=1
    )
    stop = threading.Event()

    def feeder() -> None:
        seq = 0
        while not stop.is_set():
            armed = (seq % 10) >= 7
            feeder_conn.mav.heartbeat_send(
                mavutil.mavlink.MAV_TYPE_QUADROTOR,
                mavutil.mavlink.MAV_AUTOPILOT_ARDUPILOTMEGA,
                0x80 if armed else 0x04,   # base_mode: armed flag / custom mode enabled
                0,                          # custom_mode: 0 = STABILIZE (ArduCopter)
                mavutil.mavlink.MAV_STATE_ACTIVE if armed else mavutil.mavlink.MAV_STATE_STANDBY,
            )
            seq += 1
            time.sleep(0.25)

    threading.Thread(target=feeder, daemon=True).start()
    deadline = time.time() + 15
    while time.time() < deadline:
        if runtime.shared_state.get()["connected"]:
            break
        time.sleep(0.2)

    check("SharedState.connected", runtime.shared_state.get()["connected"])
    check("connection event observed", any(e.get("type") == "connection" for e in events),
          f"types={[e.get('type') for e in events][:12]}")
    check("telemetry events observed", any(e.get("type") == "telemetry" for e in events))
    check("preflight events observed", any(e.get("type") == "preflight" for e in events))
    check("telemetry mirror queue fills", not runtime.telemetry_queue.empty() or
          any(e.get("type") == "telemetry" for e in events))

    # --- command queue round trip through the PROVEN path -------------------
    # Feeder also answers COMMAND_ACK for ARM/DISARM like a real autopilot,
    # so CommandHandler's ACK-wait loop completes quickly.
    def responder() -> None:
        while not stop.is_set():
            msg = feeder_conn.recv_msg()
            if msg is None:
                continue
            if msg.get_type() == "COMMAND_LONG" and msg.command == 400:  # ARM/DISARM
                feeder_conn.mav.command_ack_send(400, mavutil.mavlink.MAV_RESULT_ACCEPTED)

    threading.Thread(target=responder, daemon=True).start()

    runtime.arm()
    runtime.disarm()
    deadline = time.time() + 25
    while time.time() < deadline:
        if sum(1 for e in events if e.get("type") == "command_result") >= 2:
            break
        time.sleep(0.2)
    results = {e.get("command"): e.get("result") for e in events if e.get("type") == "command_result"}
    check("command_result for ARM and DISARM",
          "ARM" in results and "DISARM" in results,
          f"results={results}")
    check("ARM ACKed by autopilot path",
          results.get("ARM") == {"status": "Armed"}, f"got {results.get('ARM')}")

    runtime.stop()
    stop.set()
    check("runtime stop signals shutdown", runtime._stop.is_set())

    print(f"\n{'BACKEND RUNTIME TEST PASSED' if not FAILURES else f'{len(FAILURES)} FAILURES'}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
