from mavlink.battery_policy import battery_policy
from enum import Enum
from typing import Tuple
import time


class CommandType(str, Enum):
    ARM = "arm"
    DISARM = "disarm"
    TAKEOFF = "takeoff"
    LAND = "land"
    SET_MODE = "set_mode"

# CONTEXT

class CommandContext:
    def __init__(self, state, health):

        state_data = state.get()
        health_data = health.get_health()

        # State
        self.armed = state_data["armed"]
        self.flight_state = state_data["state"]
        self.altitude = state_data["altitude"]

        # Health
        self.is_healthy = health_data["failsafe"] is None
        self.sensors_ok = all(health_data["sensors"].values())

        battery = health_data.get("battery", {})
        self.battery_ok = battery.get("remaining", 100) > battery_policy.crit_pct

        # Telemetry
        self.connected = state_data["connected"]


# RULES


def can_arm(ctx: CommandContext, preflight) -> Tuple[bool, str]:
    result = preflight.run_preflight()

    if not result["can_arm"]:
        return False, result

    return True, "OK"


def can_disarm(ctx: CommandContext):
    if not ctx.armed:
        return False, "NOT_ARMED"

    # Prevent dangerous mid-air disarm
    if ctx.altitude > 1.0:
        return False, "DISARM_BLOCKED_IN_AIR"

    return True, "OK"


def can_takeoff(ctx: CommandContext):
    if not ctx.connected:
        return False, "NOT_CONNECTED"

    if ctx.altitude > 0.5:
        return False, "ALREADY_AIRBORNE"

    if not ctx.is_healthy:
        return False, "UNHEALTHY"

    return True, "OK"


def can_land(ctx: CommandContext):
    if not ctx.armed:
        return False, "NOT_ARMED"

    if ctx.altitude < 0.3:
        return False, "ALREADY_LANDED"

    return True, "OK"



# GUARD CORE

class CommandGuard:
    def __init__(self, shared_state, health, event_bus, preflight):
        self.shared_state = shared_state
        self.health = health
        self.event_bus = event_bus
        self.preflight = preflight

        # Rules
        self.rules = {
            CommandType.ARM: can_arm,
            CommandType.DISARM: can_disarm,
            CommandType.TAKEOFF: can_takeoff,
            CommandType.LAND: can_land,
        }

        # Cooldown system
        self.last_command_time = {}
        self.cooldown_map = {
            CommandType.ARM: 2,
            CommandType.DISARM: 2,
            CommandType.TAKEOFF: 5,
            CommandType.LAND: 3,
        }

        #  Lock system
        self.locked_command = None
        self.lock_time = 0

    #  STATE-BASED UNLOCK

    def _should_unlock(self, ctx: CommandContext):
        if not self.locked_command:
            return False

        # Unlock after takeoff 
        if self.locked_command == CommandType.TAKEOFF:
            return ctx.altitude > 1.0

        # Unlock after landing 
        if self.locked_command == CommandType.LAND:
            return ctx.altitude < 0.3

        return False

    # VALIDATE
    async def validate(self, command: CommandType):
        ctx = CommandContext(self.shared_state, self.health)
        now = time.time()


        # UNLOCK LOGIC
        if self._should_unlock(ctx):
            self.locked_command = None

        # Fallback safety unlock 
        if self.locked_command and (now - self.lock_time > 10):
            self.locked_command = None


        # LOCK CHECK
        if self.locked_command and command != self.locked_command:
            reason = f"LOCKED_BY_{self.locked_command.value.upper()}"

            await self.event_bus.publish({
                "type": "command_rejected",
                "timestamp": now,
                "command": command.value,
                "reason": reason
            })

            return False, reason

        # COOLDOWN CHECK
        cooldown = self.cooldown_map.get(command, 1)
        last_time = self.last_command_time.get(command)

        if last_time and (now - last_time < cooldown):
            reason = "COOLDOWN"

            await self.event_bus.publish({
                "type": "command_rejected",
                "timestamp": now,
                "command": command.value,
                "reason": reason
            })

            return False, reason


        # RULE VALIDATION
        rule = self.rules.get(command)

        if not rule:
            return False, "UNKNOWN_COMMAND"

        if command == CommandType.ARM:
            allowed, reason = rule(ctx, self.preflight)
        else:
            allowed, reason = rule(ctx)

        if not allowed:
            await self.event_bus.publish({
                "type": "command_rejected",
                "timestamp": now,
                "command": command.value,
                "reason": reason,
                "context": {
                    "armed": ctx.armed,
                    "altitude": ctx.altitude,
                    "connected": ctx.connected,
                    "healthy": ctx.is_healthy
                }
            })

            if isinstance(reason, dict):
                await self.event_bus.publish({
                    "type": "command_rejected",
                    "timestamp": now,
                    "command": command.value,
                    "reason": "PREFLIGHT_FAILED",
                    "details": reason
                })

                return False, {
                    "reason": "PREFLIGHT_FAILED",
                    "details": reason
                }

            # A rule that says "no" with a plain string reason (NOT_ARMED,
            # DISARM_BLOCKED_IN_AIR, ALREADY_AIRBORNE, ALREADY_LANDED, ...)
            # used to fall through to the UPDATE STATE block below and return
            # (True, "OK"): the event was logged but the command was ALLOWED.
            return False, reason


        # UPDATE STATE
        self.last_command_time[command] = now

        if command in [CommandType.TAKEOFF, CommandType.LAND]:
            self.locked_command = command
            self.lock_time = now

        return True, "OK"