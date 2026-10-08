from mavlink.battery_policy import battery_policy
from dataclasses import dataclass
from typing import Optional
import asyncio
import time


@dataclass
class CheckResult:
    name: str
    status: str  # PASS / FAIL / WARNING
    reason: Optional[str] = None


class PreflightSystem:
    def __init__(self, shared_state, health):
        self.shared_state = shared_state
        self.health = health

    # INDIVIDUAL CHECKS
    def check_connection(self):
        state = self.shared_state.get()

        if not state["connected"]:
            return CheckResult("connection", "FAIL", "NOT_CONNECTED")

        return CheckResult("connection", "PASS")

    def check_sensors(self):
        sensors = self.health.get_health()["sensors"]

        if not sensors.get("gyro", False):
            return CheckResult("sensors", "FAIL", "GYRO_NOT_READY")

        if not sensors.get("accel", False):
            return CheckResult("sensors", "FAIL", "ACCEL_NOT_READY")

        if not sensors.get("mag", False):
            return CheckResult("sensors", "FAIL", "MAG_NOT_READY")

        # GPS can be WARNING instead of FAIL 
        if not sensors.get("gps", False):
            return CheckResult("sensors", "WARNING", "GPS_NOT_READY")

        return CheckResult("sensors", "PASS")

    def check_health(self):
        failsafe = self.health.get_health()["failsafe"]

        if not failsafe:
            return CheckResult("health", "PASS")

        text = failsafe.lower()

        # ONLY block truly dangerous cases
        if "emergency" in text or "critical" in text:
            return CheckResult("health", "FAIL", failsafe)

        if "low battery" in text or "battery" in text:
            return CheckResult("health", "FAIL", failsafe)

        # Everything else is just warning
        return CheckResult("health", "WARNING", failsafe)

    def check_battery(self):
        battery = self.health.get_health().get("battery", {})
        remaining = battery.get("remaining", 100)

        if remaining == -1:
            return CheckResult("battery", "WARNING", "UNKNOWN")

        if remaining < battery_policy.crit_pct:
            return CheckResult("battery", "FAIL", "LOW_BATTERY")

        if remaining < battery_policy.warn_pct:
            return CheckResult("battery", "WARNING", "BATTERY_LOW")

        return CheckResult("battery", "PASS")

    def check_arm_state(self):
        state = self.shared_state.get()

        if state["armed"]:
            return CheckResult("arm_state", "WARNING", "ALREADY_ARMED")
        return CheckResult("arm_state", "PASS")

    # MAIN RUNNER

    def run_preflight(self):

        state = self.shared_state.get()

        if state["armed"]:
            return {
                "timestamp": time.time(),
                "can_arm": True,
                "overall_status": "IN_FLIGHT",
                "checks": []
            }
    
        checks = [
            self.check_connection(),
            self.check_sensors(),
            self.check_health(),
            self.check_battery(),
            self.check_arm_state(),
        ]

        can_arm = True
        overall_status = "PASS"

        for check in checks:
            if check.status == "FAIL":
                can_arm = False
                overall_status = "FAILED"
                break
            elif check.status == "WARNING":
                if overall_status != "FAILED":
                    overall_status = "WARNING"

        return {
            "timestamp": time.time(),
            "can_arm": can_arm,
            "overall_status": overall_status,
            "checks": [check.__dict__ for check in checks]
        }
    
    async def stream(self, event_bus):
        last_result = None

        while True:
            result = self.run_preflight()

            # Only send if changed — compare WITHOUT the timestamp, which made
            # every result differ and republished at 1 Hz.
            comparable = {k: v for k, v in result.items() if k != "timestamp"}
            if comparable != last_result:
                await event_bus.publish({
                    "type": "preflight",
                    "data": result
                })
                last_result = comparable

            await asyncio.sleep(1)  # 1Hz update