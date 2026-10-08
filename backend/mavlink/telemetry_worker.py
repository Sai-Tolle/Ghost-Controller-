import time
from queue import Empty
from typing import Dict, Any, Optional

from mavlink.mode_manager import decode_mode
from mavlink.battery_policy import battery_policy

# MODE REQUIREMENTS
_RC_MODES_PX4 = {"MANUAL", "STABILIZED", "ACRO", "RATTITUDE", "ALTCTL"}
_GPS_MODES_PX4 = {
    "POSCTL", "LOITER", "MISSION", "RTL", "RTGS",
    "TAKEOFF", "LAND", "FOLLOW_ME", "PRECLAND", "AUTO_READY",
}
_RC_MODES_ARDUCOPTER = {"STABILIZE", "ACRO", "ALT_HOLD", "DRIFT", "SPORT"}
_GPS_MODES_ARDUCOPTER = {"LOITER", "AUTO", "RTL", "CIRCLE", "LAND", "POSHOLD"}

UINT16_MAX = 65535
VELOCITY_STALE_S = 2.0      # EKF/VFR velocity older than this is dropped
KILL_MIN_ALT_M = 1.0        # armed->disarmed above this AGL is a mid-air cut
KILL_GROUND_CLEAR_S = 5.0   # disarmed + on the ground this long => kill state clears


def requires_manual_input(mode: str, autopilot: str = "PX4") -> bool:
    if autopilot == "PX4":
        return mode in _RC_MODES_PX4
    elif autopilot == "ArduPilot":
        return mode in _RC_MODES_ARDUCOPTER
    return False


def requires_gps(mode: str, autopilot: str = "PX4") -> bool:
    if autopilot == "PX4":
        return mode in _GPS_MODES_PX4
    elif autopilot == "ArduPilot":
        return mode in _GPS_MODES_ARDUCOPTER
    return False


def pack_voltage_v(msg) -> Optional[float]:
    """Pack voltage from BATTERY_STATUS.

    `voltages[]` holds PER-CELL millivolts (UINT16_MAX = unused). The old code
    took the first cell (~4 V) as the pack voltage, so the HUD flickered
    between ~16 V (SYS_STATUS) and ~4 V (BATTERY_STATUS)."""
    cells = list(getattr(msg, "voltages", []) or [])
    cells += list(getattr(msg, "voltages_ext", []) or [])
    valid = [v for v in cells if 0 < v < UINT16_MAX]
    return round(sum(valid) / 1000.0, 2) if valid else None


# TELEMETRY WORKER
def telemetry_worker(
    msg_queue,
    event_bus,
    state_queue,
    health_queue,
    shared_state,
    command_handler,
    mission_downloader,
    mission_uploader,
    fence_uploader,
    fence_downloader,
    status_logger,
    mav_conn=None,
    out_queue=None,
):
    print("Telemetry Worker started (V3)")

    last_heartbeat_time = None
    connection_alive = False

    last_publish_time = 0
    publish_interval = 0.1  # 10Hz

    state: Dict[str, Optional[Dict[str, Any]]] = {
        "attitude": None, "position": None, "battery": None, "heartbeat": None,
        "gps_raw": None, "signal": None, "velocity": None,
    }
    stamps: Dict[str, float] = {}   # monotonic time of last update per key
    ekf_velocity_ts = 0.0

    health_state = {"ready": False, "reason": "INIT", "message": "Initializing..."}

    gps_ok = False
    rc_ok = False
    current_mode = "UNKNOWN"
    last_rc_ok_time = 0.0
    RC_LOST_TIMEOUT = 2.0
    last_gps_ok_time = 0.0

    last_not_ready_time = 0.0
    last_ready_time = 0.0
    READY_HYSTERESIS = 2.5
    NOT_READY_HOLD = 1.5

    kill_switch_active = False
    kill_since = 0.0
    was_armed = False

    def autopilot_name() -> str:
        return (mav_conn.get_autopilot() if mav_conn else None) or "PX4"

    def link_alive() -> bool:
        # ONE liveness definition shared with the reader and state worker
        # (was 2 s here vs 5 s in connection.py, so the HUD flapped).
        if mav_conn is not None:
            return mav_conn.is_vehicle_alive()
        return bool(last_heartbeat_time and time.monotonic() - last_heartbeat_time <= 5.0)

    def snapshot() -> Dict[str, Any]:
        # sub-dicts are replaced (never mutated) so a shallow copy is a safe
        # point-in-time view for the consumer threads.
        return dict(state)

    def emit_telemetry(now: float, alive: bool) -> None:
        event = {
            "type": "telemetry",
            "timestamp": now,
            "connected": alive,
            "data": snapshot() if alive else None,
        }
        event_bus.publish_sync(event)
        # Desktop mirror. This MUST also carry link-loss events: previously the
        # "connected: False" event only went to the web bus, so the desktop HUD
        # froze on the last frame and kept claiming a live vehicle.
        if out_queue is not None:
            out_queue.put(event)

    def rel_alt() -> float:
        pos = state.get("position")
        return float(pos["alt"]) if pos and pos.get("alt") is not None else 0.0

    while True:
        try:
            msg = msg_queue.get(timeout=0.5)
        except Empty:
            if connection_alive and not link_alive():
                now = time.time()
                connection_alive = False
                shared_state.update(connected=False)
                for key in state:
                    state[key] = None       # never show stale data after a drop
                health_state.update(ready=False, reason="LINK", message="Vehicle not connected")
                event_bus.publish_sync({
                    "type": "health",
                    "data": {"ready": False, "reason": "LINK",
                             "last_message": "Vehicle not connected", "ts": now},
                })
                emit_telemetry(now, False)
            continue

        # Ignore other systems/components (second GCS, gimbal, companion...).
        if mav_conn is not None and not mav_conn.is_vehicle_message(msg):
            continue

        state_queue.put(msg)
        health_queue.put(msg)

        command_handler.handle_message(msg)
        mission_downloader.handle_message(msg)
        mission_uploader.handle_message(msg)
        fence_uploader.handle_message(msg)
        fence_downloader.handle_message(msg)
        status_logger.handle_message(msg)

        msg_type = msg.get_type()
        mono = time.monotonic()

        if msg_type == "ATTITUDE":
            yaw_deg = (msg.yaw * 180.0 / 3.141592653589793) % 360.0
            state["attitude"] = {"roll": msg.roll, "pitch": msg.pitch, "yaw": msg.yaw}
            shared_state.update(yaw=yaw_deg)

        elif msg_type == "GLOBAL_POSITION_INT":
            # lat/lon (0,0) is "no fix yet", not Null Island: publishing it
            # teleported the map marker and latched planner HOME at (0,0).
            has_pos = not (msg.lat == 0 and msg.lon == 0)
            prev = state.get("position") or {}
            state["position"] = {
                "lat": msg.lat / 1e7 if has_pos else None,
                "lon": msg.lon / 1e7 if has_pos else None,
                # HUD altitude is height ABOVE HOME. `msg.alt` is AMSL: on any
                # site above ~0 m it made every normal landing look like a kill
                # switch and broke the command guard's airborne checks.
                "alt": msg.relative_alt / 1000.0,
                "alt_msl": msg.alt / 1000.0,
                "hdg": (msg.hdg / 100.0) if msg.hdg != UINT16_MAX else prev.get("hdg"),
            }

        elif msg_type == "SYS_STATUS":
            previous = state["battery"] or {}
            voltage = (msg.voltage_battery / 1000.0
                       if 0 < msg.voltage_battery < UINT16_MAX else previous.get("voltage", 0))
            remaining = (msg.battery_remaining
                         if 0 <= msg.battery_remaining <= 100 else previous.get("remaining"))
            state["battery"] = {
                "voltage": voltage,
                "remaining": battery_policy.remaining(remaining, voltage),
                "remaining_vehicle": remaining,
            }

        elif msg_type == "BATTERY_STATUS":
            previous = state["battery"] or {}
            voltage = pack_voltage_v(msg)
            remaining = (msg.battery_remaining
                         if 0 <= msg.battery_remaining <= 100 else previous.get("remaining"))
            pack_v = voltage if voltage is not None else previous.get("voltage", 0)
            state["battery"] = {
                "voltage": pack_v,
                "remaining": battery_policy.remaining(remaining, pack_v),
                "remaining_vehicle": remaining,
            }

        elif msg_type == "HEARTBEAT":
            last_heartbeat_time = mono
            shared_state.update(connected=True)
            if not connection_alive:
                print(" Vehicle connected (V3 worker)")
            connection_alive = True

            current_mode = decode_mode(msg.custom_mode, autopilot_name())
            is_armed = bool(msg.base_mode & 128)
            state["heartbeat"] = {"armed": is_armed, "mode": current_mode}

            if was_armed and not is_armed and rel_alt() > KILL_MIN_ALT_M:
                kill_switch_active = True
                kill_since = time.time()
                print(f"KILL SWITCH DETECTED — alt={rel_alt():.1f}m AGL")
                event_bus.publish_sync({
                    "type": "health",
                    "data": {"ready": False, "reason": "KILL",
                             "last_message": "⚠ KILL SWITCH — motors cut", "ts": time.time()},
                })
            elif is_armed and kill_switch_active:
                kill_switch_active = False
                print("Kill switch cleared — re-armed")
            was_armed = is_armed

            if msg.base_mode & 64:
                rc_ok = True
                last_rc_ok_time = time.time()
            elif time.time() - last_rc_ok_time > RC_LOST_TIMEOUT:
                rc_ok = False

        elif msg_type == "STATUSTEXT":
            severity = msg.severity   # 0 Emergency … 4 Warning, 6 Info
            text = msg.text.rstrip("\x00").strip()
            upper = text.upper()
            # Only an explicit KILL SWITCH message latches the KILL state. A PX4
            # "Failsafe mode enabled" (very common in SITL / without RC), a
            # crash-detected or motor warning is an ALERT, not a kill: latching
            # it left the HUD on "NOT READY · KILL" while disarmed on the ground.
            if "KILL SWITCH" in upper:
                kill_switch_active = True
                kill_since = time.time()
                print(f"STATUSTEXT [{severity}]: {text}")
                event_bus.publish_sync({
                    "type": "health",
                    "data": {"ready": False, "reason": "KILL",
                             "last_message": f"⚠ {text}", "ts": time.time()},
                })
            elif severity <= 2 or (severity <= 4 and any(k in upper for k in ("FAILSAFE", "CRASH"))) \
                    or (severity <= 3 and "MOTOR" in upper):
                print(f"STATUSTEXT [{severity}]: {text}")
                event_bus.publish_sync({
                    "type": "alert", "timestamp": time.time(),
                    "level": "critical" if severity <= 2 else "warning",
                    "message": text[:80],
                })

        elif msg_type == "GPS_RAW_INT":
            fix_type = msg.fix_type
            if fix_type >= 3:
                gps_ok = True
                last_gps_ok_time = time.time()
            elif time.time() - last_gps_ok_time > 1.0:
                gps_ok = False
            state["gps_raw"] = {
                "fix_type": fix_type,
                "satellites": msg.satellites_visible,
                "hdop": msg.eph / 100.0 if msg.eph != UINT16_MAX else None,
                "vdop": msg.epv / 100.0 if msg.epv != UINT16_MAX else None,
                "cog": msg.cog / 100.0 if msg.cog != UINT16_MAX else None,
                "vel": msg.vel / 100.0 if msg.vel != UINT16_MAX else None,
            }

        elif msg_type == "LOCAL_POSITION_NED":
            vx, vy, vz = msg.vx, msg.vy, msg.vz
            state["velocity"] = {
                "vx": vx, "vy": vy, "vz": vz,
                "speed": round((vx ** 2 + vy ** 2) ** 0.5, 2),
                "vertical": round(-vz, 2),
                "source": "EKF",
            }
            ekf_velocity_ts = mono
            stamps["velocity"] = mono

        elif msg_type == "VFR_HUD":
            # Fallback only while the EKF stream is absent *or has gone stale*
            # (the old one-way latch never resumed VFR_HUD after an EKF drop).
            if mono - ekf_velocity_ts > VELOCITY_STALE_S:
                state["velocity"] = {
                    "vx": None, "vy": None, "vz": None,
                    "speed": round(msg.groundspeed, 2),
                    "vertical": round(msg.climb, 2),
                    "source": "VFR_HUD",
                }
                stamps["velocity"] = mono

        elif msg_type in ("RC_CHANNELS", "RADIO_STATUS"):
            rssi = msg.rssi
            sig = {"rssi": rssi,
                   "percent": round((rssi / 254) * 100) if rssi != 255 else None,
                   "source": msg_type}
            if msg_type == "RADIO_STATUS":
                sig.update(noise=msg.noise, remrssi=msg.remrssi)
            state["signal"] = sig

        # THROTTLED PUBLISH
        now = time.time()
        if now - last_publish_time >= publish_interval:
            if connection_alive and not link_alive():
                connection_alive = False
                shared_state.update(connected=False)

            vel = state.get("velocity")
            if vel and mono - stamps.get("velocity", mono) > VELOCITY_STALE_S:
                state["velocity"] = None

            # A kill that has landed (disarmed, on the ground) clears itself; it
            # must not strand the HUD in NOT READY until the next arm.
            hb_state = state.get("heartbeat") or {}
            if kill_switch_active and not hb_state.get("armed", False) \
                    and rel_alt() <= 0.5 and now - kill_since > KILL_GROUND_CLEAR_S:
                kill_switch_active = False
                print("Kill state cleared — vehicle is on the ground")

            autopilot = autopilot_name()
            not_ready_reason = None
            not_ready_msg = None
            if not connection_alive:
                not_ready_reason, not_ready_msg = "LINK", "Vehicle not connected"
            elif kill_switch_active:
                # KILL used to be published once and then overwritten by the
                # next 10 Hz readiness tick (gone in <3 s). It now holds until
                # the operator re-arms.
                not_ready_reason, not_ready_msg = "KILL", "Motors cut / failsafe"
            elif requires_manual_input(current_mode, autopilot) and not rc_ok:
                not_ready_reason, not_ready_msg = "RC", "No manual control input"
            elif requires_gps(current_mode, autopilot) and not gps_ok:
                not_ready_reason, not_ready_msg = "GPS", "No GPS lock"

            if not_ready_reason:
                if now - last_ready_time > NOT_READY_HOLD or not_ready_reason == "KILL":
                    last_not_ready_time = now
                    health_state.update(ready=False, reason=not_ready_reason, message=not_ready_msg)
            elif now - last_not_ready_time > READY_HYSTERESIS:
                health_state.update(ready=True, reason="OK", message="System ready")
                last_ready_time = now

            event_bus.publish_sync({
                "type": "health",
                "data": {"ready": health_state["ready"], "reason": health_state["reason"],
                         "last_message": health_state["message"], "ts": now},
            })
            emit_telemetry(now, connection_alive)
            last_publish_time = now
