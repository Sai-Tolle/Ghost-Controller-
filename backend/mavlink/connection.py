import os
import threading
import time
from typing import Any, Optional

from pymavlink import mavutil
from serial.tools import list_ports


HEARTBEAT_TIMEOUT = 5.0

# PORT AUTO-DETECTION
def detect_hardware_port() -> Optional[str]:
    ports = list_ports.comports()
    for port in ports:
        # Linux: ttyUSB/ttyACM; macOS: cu.usbmodem/cu.usbserial; Windows: COMx
        if any(x in port.device for x in ("ttyUSB", "ttyACM", "usbmodem", "usbserial")) \
                or port.device.upper().startswith("COM"):
            return port.device
    return None


class MAVLinkConnection:
    def __init__(
        self,
        connection_string: Optional[str] = None,
        baud: int = 115200,
        event_bus=None
    ):
        self.connection_string = (connection_string
                                  or os.getenv("MAVLINK_CONNECTION")
                                  or None)
        # An explicitly EMPTY MAVLINK_CONNECTION (gcs.env shipped with
        # "MAVLINK_CONNECTION=") means "not configured" — do NOT wrap an
        # empty string around to truthiness and fall through to serial
        # autodetect, which then silently beats the UDP fallback whenever a
        # USB serial device is plugged in.
        self.baud = int(os.getenv("MAVLINK_BAUD", baud))
        self.event_bus = event_bus

        self.master: Optional[Any] = None
        self.conn_type: Optional[str] = None
        
        # Vehicle type detection
        self.autopilot: Optional[str] = None  # "PX4", "ArduCopter", "ArduPlane", etc.
        self.vehicle_type: Optional[str] = None  # "copter", "plane", "rover"

        # Monotonic time avoids false timeouts if the system clock changes.
        self.last_heartbeat: float = 0.0
        self.connected: bool = False
        self.last_error: Optional[str] = None

        # All reads and writes use the same lock.  MAVLink frames written by
        # the command worker and GCS heartbeat must not interleave on serial.
        self._io_lock = threading.RLock()
        self._connect_lock = threading.Lock()

        # Runtime link control (desktop CONNECTION settings).
        #   _enabled    False = operator pressed DISCONNECT / auto-connect off:
        #               connect() returns at once instead of retrying forever.
        #   _generation bumped on every reconfigure/enable change; a connect
        #               loop started under an older generation aborts, so a new
        #               link string takes effect within ~0.5 s instead of after
        #               the current 10 s heartbeat wait.
        #   _wake       interrupts the 2 s back-off between attempts.
        auto = os.getenv("MAVLINK_AUTOCONNECT", "1").strip().lower()
        self._enabled = auto not in ("0", "false", "no", "off")
        self._generation = 0
        self._wake = threading.Event()
        self.attempts = 0
        self.active_target: Optional[str] = None   # what the transport is opened on
        # Called SYNCHRONOUSLY when a link session starts or ends (before the
        # link reads as alive / right after it drops), for per-vehicle caches
        # such as parameters. Event-bus delivery is async and raced requests
        # made right after connecting.
        self.session_listeners: list = []

    # RUNTIME LINK CONTROL
    def configure(self, connection_string: Optional[str], baud: Optional[int] = None) -> None:
        """Switch the link target at runtime. Empty/None = AUTO (serial
        autodetect, then MAVLINK_FALLBACK UDP). Drops the current transport;
        the reader reconnects on the new target if the link is enabled."""
        conn = (connection_string or "").strip() or None
        with self._io_lock:
            self.connection_string = conn
            if baud:
                self.baud = int(baud)
            self._generation += 1
        self._wake.set()
        self._handle_disconnect("link reconfigured")

    def set_enabled(self, enabled: bool) -> None:
        """Operator CONNECT / DISCONNECT. While disabled nothing reconnects."""
        with self._io_lock:
            changed = self._enabled != bool(enabled)
            self._enabled = bool(enabled)
            self._generation += 1
            if enabled:
                self.last_error = None       # a fresh attempt: drop "disconnected by operator"
                self.attempts = 0
        self._wake.set()
        if not enabled:
            self._handle_disconnect("disconnected by operator")
            if changed:
                self._publish_connection("disabled")

    @property
    def enabled(self) -> bool:
        return self._enabled

    def _aborted(self, generation: int) -> bool:
        return (not self._enabled) or generation != self._generation

    def describe_target(self) -> str:
        """Human-readable target for the UI."""
        if self.connection_string:
            conn = self.connection_string
            return conn if conn.startswith(("udp", "tcp", "mcast")) else f"{conn} @ {self.baud}"
        return "auto (serial → " + os.getenv("MAVLINK_FALLBACK", "udpin:127.0.0.1:14550") + ")"

    # CONNECTION CREATION
    def _create_connection(self) -> Any:
        if self.connection_string:
            conn = self.connection_string.strip()

            if conn.startswith(("udp", "tcp", "mcast")):
                self.conn_type = "network"
                self.active_target = conn
                return mavutil.mavlink_connection(conn)
            else:
                self.conn_type = "hardware"
                self.active_target = f"{conn} @ {self.baud}"
                return mavutil.mavlink_connection(conn, baud=self.baud)

        hw = detect_hardware_port()
        if hw:
            print(f"[MAV] Using hardware: {hw} at {self.baud} baud")
            self.conn_type = "hardware"
            self.active_target = f"{hw} @ {self.baud}"
            return mavutil.mavlink_connection(hw, baud=self.baud)

        if os.getenv("MAVLINK_REQUIRE_CONNECTION", "0") == "1":
            raise RuntimeError("No MAVLink serial device found")

        fallback = os.getenv("MAVLINK_FALLBACK", "udpin:127.0.0.1:14550")
        print(f"[MAV] Falling back to {fallback}")
        self.conn_type = "network"
        self.active_target = fallback
        return mavutil.mavlink_connection(fallback)

    def _wait_vehicle_heartbeat(self, candidate, generation: int, timeout: float = 10.0):
        """Like wait_heartbeat(), but (a) skips heartbeats from other GCSs,
        gimbals and companions, which wait_heartbeat() accepted, and (b)
        aborts within 0.5 s when the operator changes or disables the link."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._aborted(generation):
                return None
            hb = candidate.recv_match(type="HEARTBEAT", blocking=True, timeout=0.5)
            if hb is None:
                continue
            if candidate.probably_vehicle_heartbeat(hb):
                return hb
        return None

    # CONNECT LOOP
    def connect(self):
        """Keep trying until a real vehicle heartbeat is received.

        Returns False (without retrying) when the link is disabled or was
        reconfigured meanwhile; the reader calls connect() again, which then
        uses the new target."""
        if not self._enabled:
            return False
        with self._connect_lock:
            if self.is_vehicle_alive():
                return True
            generation = self._generation
            if self._aborted(generation):
                return False

            # A stale transport must be closed before replacing it.  This is
            # important for USB serial devices and prevents old readers/writers
            # from surviving into the next reconnect attempt.
            if self.master:
                self._handle_disconnect("heartbeat timeout")

            while True:
                if self._aborted(generation):
                    return False
                candidate = None
                self._wake.clear()
                self.attempts += 1
                try:
                    candidate = self._create_connection()
                    if candidate is None:
                        raise RuntimeError("Failed to create MAVLink connection")

                    with self._io_lock:
                        if self._aborted(generation):
                            raise InterruptedError("link reconfigured")
                        self.master = candidate
                    self._publish_connection("connecting", target=self.active_target)

                    print("[MAV] Waiting for vehicle heartbeat...")
                    heartbeat = self._wait_vehicle_heartbeat(candidate, generation)
                    if heartbeat is None:
                        if self._aborted(generation):
                            raise InterruptedError("link reconfigured")
                        raise TimeoutError("No vehicle heartbeat within 10 seconds")
                    candidate.target_system = heartbeat.get_srcSystem()
                    candidate.target_component = heartbeat.get_srcComponent()

                    self._detect_autopilot(heartbeat)
                    self._setup_streams()

                    self._notify_session("connected")
                    with self._io_lock:
                        if self._aborted(generation) or self.master is not candidate:
                            raise InterruptedError("link reconfigured")
                        self.last_heartbeat = time.monotonic()
                        self.connected = True
                        self.last_error = None
                        self.attempts = 0

                    print(
                        f"[MAV] Connected ({self.conn_type}) "
                        f"system={candidate.target_system} "
                        f"component={candidate.target_component}"
                    )
                    self._publish_connection(
                        "connected",
                        autopilot=self.autopilot,
                        vehicle_type=self.vehicle_type,
                        system=candidate.target_system,
                        component=candidate.target_component,
                    )
                    return True

                except Exception as exc:
                    self._close_candidate(candidate)
                    if self._aborted(generation):
                        return False
                    self.last_error = str(exc)
                    print(f"[MAV] Connection attempt failed: {exc}")
                    self._publish_connection("disconnected", error=str(exc))
                    self._wake.wait(2.0)      # back-off, cut short by reconfigure

    def _close_candidate(self, candidate=None):
        with self._io_lock:
            current = self.master
            if candidate is None or current is candidate:
                self.master = None
                self.connected = False
                self.last_heartbeat = 0.0

            target = candidate or current
            try:
                if target:
                    target.close()
            except Exception:
                pass

    def _notify_session(self, status: str) -> None:
        for cb in tuple(self.session_listeners):
            try:
                cb(status)
            except Exception as exc:  # noqa: BLE001
                print(f"[MAV] session listener error: {exc}")

    def _publish_connection(self, status: str, **details):
        if not self.event_bus:
            return
        self.event_bus.publish_sync({
            "type": "connection",
            "payload": {"status": status, **details},
        })
    
    # DETECT AUTOPILOT TYPE
    def _detect_autopilot(self, heartbeat=None):
        if heartbeat is None:
            with self._io_lock:
                heartbeat = self.master.messages.get("HEARTBEAT") if self.master else None
        if not heartbeat:
            raise RuntimeError("Heartbeat received but could not be decoded")
        
        autopilot_id = heartbeat.autopilot
        vehicle_type = heartbeat.type
        
        # Detect autopilot firmware
        if autopilot_id == mavutil.mavlink.MAV_AUTOPILOT_PX4:
            self.autopilot = "PX4"
        elif autopilot_id == mavutil.mavlink.MAV_AUTOPILOT_ARDUPILOTMEGA:
            self.autopilot = "ArduPilot"
        else:
            self.autopilot = "UNKNOWN"
        
        # Detect vehicle type
        if vehicle_type == mavutil.mavlink.MAV_TYPE_QUADROTOR:
            self.vehicle_type = "copter"
        elif vehicle_type == mavutil.mavlink.MAV_TYPE_FIXED_WING:
            self.vehicle_type = "plane"
        elif vehicle_type == mavutil.mavlink.MAV_TYPE_GROUND_ROVER:
            self.vehicle_type = "rover"
        else:
            self.vehicle_type = "unknown"
        
        print(f"[MAV] Detected: {self.autopilot} {self.vehicle_type}")


    # STREAM SETUP
    def _request_message(self, msg_id, frequency_hz):
        if not self.master:
            return

        interval_us = int(1e6 / frequency_hz)

        self._send_mavlink_locked(
            "command_long_send",
            self.master.target_system,
            self.master.target_component,
            mavutil.mavlink.MAV_CMD_SET_MESSAGE_INTERVAL,
            0,
            msg_id,
            interval_us,
            0, 0, 0, 0, 0
        )

    def _setup_streams(self):
        with self._io_lock:
            if not self.master:
                return

            print("[MAV] Requesting telemetry streams...")
            # Keep rates radio-friendly while covering every message consumed
            # by telemetry_worker and the frontend.
            streams = (
                (mavutil.mavlink.MAVLINK_MSG_ID_HEARTBEAT, 1),
                (mavutil.mavlink.MAVLINK_MSG_ID_ATTITUDE, 5),
                (mavutil.mavlink.MAVLINK_MSG_ID_GLOBAL_POSITION_INT, 5),
                (mavutil.mavlink.MAVLINK_MSG_ID_SYS_STATUS, 1),
                (mavutil.mavlink.MAVLINK_MSG_ID_BATTERY_STATUS, 1),
                (mavutil.mavlink.MAVLINK_MSG_ID_GPS_RAW_INT, 2),
                (mavutil.mavlink.MAVLINK_MSG_ID_LOCAL_POSITION_NED, 5),
                (mavutil.mavlink.MAVLINK_MSG_ID_VFR_HUD, 2),
                (mavutil.mavlink.MAVLINK_MSG_ID_RC_CHANNELS, 2),
                (mavutil.mavlink.MAVLINK_MSG_ID_RADIO_STATUS, 1),
                (mavutil.mavlink.MAVLINK_MSG_ID_STATUSTEXT, 1),
            )
            for msg_id, frequency in streams:
                try:
                    self._request_message(msg_id, frequency)
                except Exception as exc:
                    # Older firmware may reject individual requests without
                    # invalidating an otherwise healthy heartbeat link.
                    print(f"[MAV] Stream request failed for {msg_id}: {exc}")

    # THREAD-SAFE OUTBOUND MAVLINK
    def _send_mavlink_locked(self, method: str, *args, **kwargs) -> bool:
        if not self.master:
            return False
        getattr(self.master.mav, method)(*args, **kwargs)
        return True

    def send_mavlink(self, method: str, *args, **kwargs) -> bool:
        """Send one MAVLink packet while holding the transport write lock."""
        with self._io_lock:
            if not self.master or not self.connected:
                return False
            try:
                return self._send_mavlink_locked(method, *args, **kwargs)
            except Exception as exc:
                print(f"[MAV] Send failed: {exc}")
                self._handle_disconnect(f"send failed: {exc}")
                return False

    # RECEIVE MESSAGE
    def recv_msg(self):
        if not self.master or not self.is_vehicle_alive():
            self.connect()

        with self._io_lock:
            if not self.master:
                return None

            try:
                msg = self.master.recv_match(blocking=False)

                if msg and msg.get_type() == "HEARTBEAT" and self.is_vehicle_message(msg):
                    self.last_heartbeat = time.monotonic()
                    self.connected = True

                if self.last_heartbeat and time.monotonic() - self.last_heartbeat > HEARTBEAT_TIMEOUT:
                    raise TimeoutError("Heartbeat timeout")

                return msg

            except Exception as exc:
                print(f"[MAV] Connection lost: {exc}")
                self._handle_disconnect(str(exc))
                return None

    # SOURCE FILTER
    _NON_VEHICLE_TYPES = None

    def is_vehicle_message(self, msg) -> bool:
        """True when `msg` came from the vehicle we are connected to.

        pymavlink hands us every packet on the link. A second GCS, a gimbal, a
        companion computer or an ADS-B receiver all send HEARTBEATs too; the old
        code decoded their custom_mode/base_mode as the vehicle's mode and armed
        state. We accept only the connected system, and for HEARTBEAT only the
        autopilot component."""
        master = self.master
        if master is None:
            return True
        try:
            sysid = int(getattr(master, "target_system", 0) or 0)
            if sysid and msg.get_srcSystem() != sysid:
                return False
            if msg.get_type() == "HEARTBEAT":
                mav = mavutil.mavlink
                if msg.type in (mav.MAV_TYPE_GCS, mav.MAV_TYPE_ONBOARD_CONTROLLER,
                                mav.MAV_TYPE_GIMBAL, mav.MAV_TYPE_ADSB,
                                mav.MAV_TYPE_CAMERA):
                    return False
                if msg.autopilot == mav.MAV_AUTOPILOT_INVALID:
                    return False
                comp = int(getattr(master, "target_component", 0) or 0)
                if comp and msg.get_srcComponent() != comp:
                    return False
        except Exception:  # noqa: BLE001 — never let a malformed packet kill the reader
            return True
        return True

    # SEND MESSAGE
    def send(self, msg):
        return self.send_mavlink("send", msg)

    # DISCONNECT HANDLER
    def _handle_disconnect(self, reason: str = "connection lost"):
        with self._io_lock:
            master = self.master
            self.master = None
            was_connected = self.connected
            self.connected = False
            self.last_heartbeat = 0.0
            self.last_error = reason
            try:
                if master:
                    master.close()
            except Exception:
                pass

        if was_connected:
            self._notify_session("lost")
            self._publish_connection("lost", error=reason)

    # ACCESSOR
    def get_master(self) -> Optional[Any]:
        with self._io_lock:
            # Do not expose a half-handshaken transport to command workers.
            return self.master if self.connected else None
    
    def get_autopilot(self) -> Optional[str]:
        return self.autopilot
    
    def get_vehicle_type(self) -> Optional[str]:
        return self.vehicle_type

    def heartbeat_age(self) -> float:
        with self._io_lock:
            if not self.last_heartbeat:
                return float("inf")
            return time.monotonic() - self.last_heartbeat

    def is_vehicle_alive(self) -> bool:
        return self.connected and self.heartbeat_age() <= HEARTBEAT_TIMEOUT
