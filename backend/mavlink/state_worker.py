import time
from queue import Empty

from mavlink.mode_manager import decode_mode


class StateWorker:
    def __init__(self, msg_queue, event_bus, shared_state, mav_conn=None):
        self.shared_state = shared_state
        self.msg_queue = msg_queue
        self.event_bus = event_bus
        self.mav_conn = mav_conn

        self.state = "DISCONNECTED"
        self.armed = False
        self.mode = "UNKNOWN"
        self.last_altitude = 0

        # State debounce
        self.last_state_change_time = 0
        self.min_state_duration = 1.0

        # Arm debounce
        self.arm_change_time = 0
        self.armed_since = 0.0

        # Publish optimization
        self._last_published = None

        self.last_heartbeat = None

    # STATE PUBLISH
    def _publish_state(self):
        if self._last_published == (self.state, self.armed, self.mode):
            return

        self._last_published = (self.state, self.armed, self.mode)

        self.event_bus.publish_sync({
            "type": "state",
            "timestamp": time.time(),
            "data": {
                "state": self.state,
                "armed": self.armed,
                "mode": self.mode
            }
        })

    def set_state(self, new_state):
        now = time.time()

        if now - self.last_state_change_time < self.min_state_duration:
            return

        if self.state != new_state:
            print(f"[STATE V2] {self.state} → {new_state}")
            self.state = new_state
            self.last_state_change_time = now
            self._publish_state()

    # MESSAGE HANDLERS
    def _handle_position(self, msg):
        if msg.get_srcComponent() != 1:
            return
        # RELATIVE altitude (above home). msg.alt is AMSL; using it made
        # "armed + alt > 1 m" true everywhere and corrupted every guard rule.
        self.last_altitude = msg.relative_alt / 1000.0
        has_pos = not (msg.lat == 0 and msg.lon == 0)
        self.shared_state.update(
            altitude=self.last_altitude,
            lat=msg.lat / 1e7 if has_pos else None,
            lon=msg.lon / 1e7 if has_pos else None,
        )

    def _handle_heartbeat(self, msg):
        if msg.get_srcComponent() != 1:
            return

        now = time.monotonic()
        self.last_heartbeat = now

        was_armed = self.armed
        new_armed = (msg.base_mode & 128) != 0

        # debounce
        if new_armed != self.armed:
            if now - self.arm_change_time > 0.5:
                self.armed = new_armed
                self.arm_change_time = now
                if new_armed:
                    self.armed_since = now
        else:
            self.arm_change_time = now

        # Auto-disarm detection: only a disarm while still on the ground right
        # after arming is a pre-flight timeout. A disarm after landing (state
        # ARMED because the vehicle never climbed past 1 m) is normal.
        if was_armed and not self.armed:
            if self.state in ["ARMED", "TAKEOFF"] and (now - self.armed_since) < 30.0 \
                    and self.last_altitude < 0.5:
                self.event_bus.publish_sync({
                    "type": "alert",
                    "timestamp": now,
                    "level": "warning",
                    "message": "AUTO DISARMED (PREFLIGHT TIMEOUT)"
                })

        autopilot = self.mav_conn.get_autopilot() if self.mav_conn else "PX4"
        self.mode = decode_mode(msg.custom_mode, autopilot or "PX4")

        alt = self.last_altitude

        if not self.armed:
            self.set_state("STANDBY")

        elif self.mode == "TAKEOFF":
            self.set_state("TAKEOFF")

        elif self.mode == "LAND":
            self.set_state("LANDING")

        elif self.mode == "RTL":
            self.set_state("RTL")

        elif self.mode == "MISSION":
            self.set_state("MISSION")

        elif self.mode in ["LOITER", "POSCTL", "ALTCTL", "OFFBOARD"]:
            if alt > 1.0:
                self.set_state("FLYING")
            else:
                self.set_state("ARMED")

        else:
            self.set_state("FLYING" if alt > 1.0 else "ARMED")

        self.shared_state.update(
            state=self.state,
            armed=self.armed,
            mode=self.mode
        )

    def _handle_status(self, msg):
        if msg.get_srcComponent() != 1:
            return

        text = msg.text.rstrip("\x00").strip().lower()

        if msg.severity <= 4 and ("failsafe" in text or "error" in text):
            self.set_state("ERROR")
            

    # MAIN LOOP
    def run(self):
        print(" State Worker started (V2)")

        while True:
            try:
                msg = self.msg_queue.get(timeout=0.5)
            except Empty:
                link_alive = (
                    self.mav_conn.is_vehicle_alive()
                    if self.mav_conn is not None
                    else bool(self.last_heartbeat and time.monotonic() - self.last_heartbeat <= 5.0)
                )
                if self.last_heartbeat and not link_alive:
                    self.shared_state.update(connected=False)
                    if self.state != "DISCONNECTED":
                        self.set_state("DISCONNECTED")
                continue
            msg_type = msg.get_type()

            if msg_type == "HEARTBEAT":
                self._handle_heartbeat(msg)

            elif msg_type == "GLOBAL_POSITION_INT":
                self._handle_position(msg)

            elif msg_type == "STATUSTEXT":
                self._handle_status(msg)

            # connection loss (shares the connection layer's liveness rule)
            alive = (self.mav_conn.is_vehicle_alive() if self.mav_conn is not None
                     else bool(self.last_heartbeat and time.monotonic() - self.last_heartbeat <= 5.0))
            if self.last_heartbeat and not alive and self.state != "DISCONNECTED":
                self.set_state("DISCONNECTED")
