import math
import threading
import time
from collections import deque

from pymavlink import mavutil

from mavlink.command_guard import CommandType
from mavlink.mode_manager import get_mode_map

_RESULT_NAMES = {
    0: "ACCEPTED", 1: "TEMPORARILY_REJECTED", 2: "DENIED", 3: "UNSUPPORTED",
    4: "FAILED", 5: "IN_PROGRESS", 6: "CANCELLED",
}
_IN_PROGRESS = 5
POSITION_MAX_AGE_S = 3.0


def _result_name(code) -> str:
    return _RESULT_NAMES.get(int(code), f"CODE_{code}")


class CommandHandler:
    """MAVLink command layer.

    Thread model: commands run on the command worker thread, but KILL / RTL
    are executed on their own thread so they can never queue behind a slow
    ARM/TAKEOFF. COMMAND_ACKs are therefore stored per command id under a
    Condition — the previous shared list let one waiter pop (discard) the
    ACK another thread was waiting for.
    """

    def __init__(self, mav_conn):
        self.mav_conn = mav_conn
        self._cv = threading.Condition()
        self._acks = {}                              # command id -> COMMAND_ACK
        self.mission_ack_queue = deque(maxlen=64)    # bounded (was an unbounded list)
        self.heartbeat_queue = deque(maxlen=8)       # idem — grew ~6 msgs/s forever
        self.position_queue = deque(maxlen=8)

    # ------------------------------------------------------------------ plumbing
    def _get_master(self):
        master = self.mav_conn.get_master()
        if not master:
            print("[CMD] No MAVLink connection")
            return None, None, None
        return master, master.target_system, master.target_component

    def _get_autopilot(self):
        return self.mav_conn.get_autopilot() or "UNKNOWN"

    def _get_mode_map(self):
        return get_mode_map(self._get_autopilot())

    def handle_message(self, msg):
        msg_type = msg.get_type()
        if msg_type == "COMMAND_ACK":
            with self._cv:
                self._acks[int(msg.command)] = msg
                self._cv.notify_all()
        elif msg_type == "MISSION_ACK":
            self.mission_ack_queue.append(msg)
        elif msg_type == "HEARTBEAT":
            self.heartbeat_queue.append(msg)
        elif msg_type == "GLOBAL_POSITION_INT":
            self.position_queue.append((time.monotonic(), msg))

    def _latest_position(self):
        if not self.position_queue:
            return None
        ts, msg = self.position_queue[-1]
        return msg if time.monotonic() - ts <= POSITION_MAX_AGE_S else None

    def _is_armed(self):
        if not self.heartbeat_queue:
            return None
        return bool(self.heartbeat_queue[-1].base_mode & 128)

    def _send_and_wait(self, command_id, send, timeout=5.0, in_progress_timeout=30.0):
        """Send one command and wait for ITS ack.

        Returns (ack | None). Stale acks for the same command id are cleared
        first, so a late reply to an earlier attempt can't be mistaken for this
        one. IN_PROGRESS keeps waiting (long-running commands) instead of being
        reported as a rejection."""
        with self._cv:
            self._acks.pop(int(command_id), None)
        if not send():
            return None
        deadline = time.monotonic() + timeout
        with self._cv:
            while True:
                ack = self._acks.get(int(command_id))
                if ack is not None:
                    if ack.result != _IN_PROGRESS:
                        self._acks.pop(int(command_id), None)
                        return ack
                    self._acks.pop(int(command_id), None)
                    deadline = max(deadline, time.monotonic() + in_progress_timeout)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._cv.wait(timeout=min(remaining, 0.25))

    def _long(self, command_id, *params, timeout=5.0):
        """command_long with 7 params; returns the ACK or None."""
        master, ts, tc = self._get_master()
        if not master:
            return "NOT_CONNECTED"
        p = list(params) + [0] * (7 - len(params))

        def send():
            return self.mav_conn.send_mavlink(
                "command_long_send", ts, tc, command_id, 0, *p)

        return self._send_and_wait(command_id, send, timeout=timeout)

    @staticmethod
    def _verdict(ack, ok_text, name):
        if ack == "NOT_CONNECTED":
            return {"error": "Not connected"}
        if ack is None:
            return {"error": f"No {name} ACK"}
        if ack.result == mavutil.mavlink.MAV_RESULT_ACCEPTED:
            return {"status": ok_text}
        return {"error": f"{name.capitalize()} rejected ({_result_name(ack.result)})"}

    def execute(self, command: CommandType, **kwargs):
        if command == CommandType.ARM:
            return self.arm()
        elif command == CommandType.DISARM:
            return self.disarm()
        elif command == CommandType.TAKEOFF:
            return self.takeoff(kwargs.get("altitude", 10))
        elif command == CommandType.LAND:
            return self.land()
        elif command == CommandType.SET_MODE:
            mode = kwargs.get("mode")
            if mode is None:
                return {"error": "MODE_NOT_PROVIDED"}
            return self.set_mode(mode)
        return {"error": "UNKNOWN_COMMAND"}

    # ---------------------------------------------------------------------- MODE
    def set_mode(self, mode: str):
        mode_map = self._get_mode_map()
        if mode not in mode_map:
            return {"error": f"Unknown mode: {mode}"}
        autopilot = self._get_autopilot()
        value = mode_map[mode]
        if autopilot == "PX4":
            if not isinstance(value, tuple):
                return {"error": "Invalid PX4 mode encoding"}
            main_mode, sub_mode = value
            params = (mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED, main_mode, sub_mode)
        elif autopilot == "ArduPilot":
            if not isinstance(value, int):
                return {"error": "Invalid ArduPilot mode encoding"}
            params = (1, value, 0)
        else:
            return {"error": "Unknown autopilot"}
        ack = self._long(mavutil.mavlink.MAV_CMD_DO_SET_MODE, *params)
        if ack == "NOT_CONNECTED":
            return {"error": "Not connected"}
        if ack is None:
            return {"error": "No ACK received"}
        if ack.result == mavutil.mavlink.MAV_RESULT_ACCEPTED:
            return {"status": f"Mode set to {mode}"}
        return {"error": f"Mode rejected ({_result_name(ack.result)})"}

    # ----------------------------------------------------------------------- ARM
    def arm(self):
        """Arm once. Retries only when NO ack arrived (lost packet). A DENIED /
        FAILED answer is final — the old loop re-sent the arm request five
        times against an explicit refusal and blocked the worker ~30 s."""
        for attempt in range(2):
            ack = self._long(mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM, 1)
            if ack == "NOT_CONNECTED":
                return {"error": "Not connected"}
            if ack is None:
                continue
            if ack.result == mavutil.mavlink.MAV_RESULT_ACCEPTED:
                return {"status": "Armed"}
            return {"error": f"Arm rejected ({_result_name(ack.result)})"}
        return {"error": "Arm failed (no ACK)"}

    def disarm(self):
        if self._is_armed() is False:
            return {"status": "Already disarmed"}
        ack = self._long(mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM, 0)
        return self._verdict(ack, "Disarmed", "disarm")

    # ------------------------------------------------------------------- TAKEOFF
    def takeoff(self, altitude=10):
        try:
            altitude = float(altitude)
        except (TypeError, ValueError):
            return {"error": "Invalid takeoff altitude"}
        if not 1.0 <= altitude <= 120.0:
            return {"error": "Takeoff altitude must be 1-120 m"}

        # Check BEFORE touching the vehicle. The old order switched to HOLD
        # (aborting any running mission) and armed first, and only then
        # discovered "Already airborne".
        pos = self._latest_position()
        if pos is None:
            return {"error": "No position data"}
        rel = pos.relative_alt / 1000.0
        if rel > 0.5:
            return {"error": "Already airborne"}

        autopilot = self._get_autopilot()
        res = self.set_mode("GUIDED" if autopilot == "ArduPilot" else "HOLD")
        if "error" in res:
            return res

        if self._is_armed() is not True:
            time.sleep(0.5)
            res = self.arm()
            if "error" in res:
                return res
            time.sleep(1.0)

        if autopilot == "ArduPilot":
            target = altitude                              # relative to home
        else:
            # PX4 reads NAV_TAKEOFF altitude as AMSL. Relative+offset put the
            # target below ground anywhere above sea level.
            home_amsl = pos.alt / 1000.0 - rel
            target = home_amsl + altitude
        nan = float("nan")                                 # NaN lat/lon = "here"
        ack = self._long(mavutil.mavlink.MAV_CMD_NAV_TAKEOFF, 0, 0, 0, nan, nan, nan, target)
        return self._verdict(ack, f"Takeoff to {altitude:.0f} m", "takeoff")

    # ---------------------------------------------------------------------- LAND
    def land(self):
        """Command a landing and return as soon as it is ACKed. The old version
        polled for up to 45 s (always answering "Landed", even on timeout),
        which froze the worker and delayed KILL/RTL behind it."""
        if self._get_autopilot() == "ArduPilot":
            res = self.set_mode("LAND")
            return {"status": "Landing"} if "error" not in res else res
        ack = self._long(mavutil.mavlink.MAV_CMD_NAV_LAND, 0, 0, 0, float("nan"), 0, 0, 0)
        return self._verdict(ack, "Landing", "land")

    def rtl(self):
        ack = self._long(mavutil.mavlink.MAV_CMD_NAV_RETURN_TO_LAUNCH)
        return self._verdict(ack, "RTL triggered", "RTL")

    # ------------------------------------------------------------------- MISSION
    def start_mission(self):
        if self._is_armed() is False:
            return {"error": "Vehicle is not armed — arm first, then start the mission"}
        if self._get_autopilot() == "ArduPilot":
            res = self.set_mode("AUTO")
            if "error" in res:
                return res
        ack = self._long(mavutil.mavlink.MAV_CMD_MISSION_START, 0, 0)
        return self._verdict(ack, "Mission started", "mission start")

    # ---------------------------------------------------------------------- KILL
    def kill_switch(self):
        ack = self._long(mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM, 0, 21196, timeout=3)
        if ack == "NOT_CONNECTED":
            return {"error": "Not connected"}
        if ack is None:
            return {"status": "Kill switch sent (no ACK — motors may already be cut)"}
        if ack.result == mavutil.mavlink.MAV_RESULT_ACCEPTED:
            return {"status": "Kill switch engaged — motors cut"}
        return {"error": f"Kill switch rejected ({_result_name(ack.result)})"}

    # ------------------------------------------------------------- CLEAR MISSION
    def clear_mission(self):
        self.mission_ack_queue.clear()
        master, ts, tc = self._get_master()
        if not master:
            return {"error": "Not connected"}
        self.mav_conn.send_mavlink("mission_clear_all_send", ts, tc,
                                   mavutil.mavlink.MAV_MISSION_TYPE_MISSION)
        deadline = time.time() + 5
        while time.time() < deadline:
            if self.mission_ack_queue:
                ack = self.mission_ack_queue.popleft()
                if ack.type == mavutil.mavlink.MAV_MISSION_ACCEPTED:
                    return {"status": "Mission cleared"}
                return {"error": f"Clear failed ({ack.type})"}
            time.sleep(0.05)
        return {"error": "No MISSION_ACK received"}

    # --------------------------------------------------------------------- ORBIT
    def orbit(self, lat, lon, alt=10.0, radius=15.0, velocity=2.0):
        if lat is None or lon is None:
            return {"error": "Orbit needs a latitude and longitude"}
        master, ts, tc = self._get_master()
        if not master:
            return {"error": "Not connected"}
        ardu = self._get_autopilot() == "ArduPilot"
        cmd = mavutil.mavlink.MAV_CMD_NAV_LOITER_UNLIM if ardu else 31   # 31 = DO_ORBIT

        def send():
            return self.mav_conn.send_mavlink(
                "command_int_send", ts, tc,
                mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT, cmd, 0, 0,
                float(radius), float(velocity), 0.0, 0.0,
                int(float(lat) * 1e7), int(float(lon) * 1e7), float(alt))

        ack = self._send_and_wait(cmd, send)
        return self._verdict(ack, "Orbiting target location", "orbit")
