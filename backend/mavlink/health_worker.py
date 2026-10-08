import time
from mavlink.battery_policy import battery_policy
from pymavlink import mavutil


class HealthWorker:
    def __init__(self, health_queue, event_bus):
        self.queue = health_queue
        self.event_bus = event_bus

        self.last_publish_time = 0
        self.publish_interval = 0.5

        self.failsafe_timeout = 5.0
        self.last_failsafe_time = 0

        self.health = {
            "sensors": {"gyro": False, "accel": False, "mag": False, "gps": False},
            "system_status": "UNKNOWN",
            "failsafe": None,
            "last_message": None,
            "battery": {},
            "ekf": {"ok": True, "flags": {}}
        }

    def _trigger_failsafe(self, message, now):
        self.health["failsafe"] = message
        self.last_failsafe_time = now

        self.event_bus.publish_sync({
            "type": "alert",
            "timestamp": now,
            "level": "critical",
            "message": message
        })

    def run(self):
        print("Health Worker started (V2)")

        while True:
            msg = self.queue.get()
            msg_type = msg.get_type()
            now = time.time()

            # clear stale failsafe
            if self.health["failsafe"] and (now - self.last_failsafe_time > self.failsafe_timeout):
                self.health["failsafe"] = None

            # SYS_STATUS
            if msg_type == "SYS_STATUS":
                bits = msg.onboard_control_sensors_health

                self.health["sensors"] = {
                    "gyro": bool(bits & mavutil.mavlink.MAV_SYS_STATUS_SENSOR_3D_GYRO),
                    "accel": bool(bits & mavutil.mavlink.MAV_SYS_STATUS_SENSOR_3D_ACCEL),
                    "mag": bool(bits & mavutil.mavlink.MAV_SYS_STATUS_SENSOR_3D_MAG),
                    "gps": bool(bits & mavutil.mavlink.MAV_SYS_STATUS_SENSOR_GPS)
                }

                # 65535 mV is MAVLink for "unknown", not 65.5 V
                voltage = msg.voltage_battery / 1000.0 if 0 < msg.voltage_battery < 65535 else 0.0
                remaining = msg.battery_remaining

                self.health["battery"] = {
                    "voltage": voltage,
                    "remaining": remaining
                }

                effective = battery_policy.remaining(remaining, voltage)
                self.health["battery"]["remaining"] = effective if effective is not None else -1
                if effective is not None and effective < battery_policy.crit_pct:
                    self._trigger_failsafe(f"LOW BATTERY ({effective:.0f}%)", now)

            # HEARTBEAT
            elif msg_type == "HEARTBEAT":
                status_map = {
                    mavutil.mavlink.MAV_STATE_STANDBY: "STANDBY",
                    mavutil.mavlink.MAV_STATE_ACTIVE: "ACTIVE",
                    mavutil.mavlink.MAV_STATE_CRITICAL: "CRITICAL"
                }

                self.health["system_status"] = status_map.get(msg.system_status, "UNKNOWN")

            # STATUSTEXT
            elif msg_type == "STATUSTEXT":
                text = msg.text.strip("\x00").strip()
                if text:
                    self.health["last_message"] = text

                    # Only serious statustext counts as a failsafe (severity
                    # 0-4). Info lines such as "Failsafe disabled" must not.
                    if msg.severity <= 4 and "fail" in text.lower():
                        self._trigger_failsafe(text.upper(), now)

            # PUBLISH
            if now - self.last_publish_time > self.publish_interval:
                self.last_publish_time = now

                self.event_bus.publish_sync({
                    "type": "health",
                    "timestamp": now,
                    "data": self.health
                })

    def get_health(self):
        # Hand out a snapshot: consumers (guard, preflight) run on other
        # threads while this worker keeps replacing sub-dicts.
        return dict(self.health)