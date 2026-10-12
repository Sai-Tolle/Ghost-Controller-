import math


def _is_number(value, lo, hi):
    """Finite real number inside [lo, hi] (bool is not a coordinate)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return math.isfinite(value) and lo <= value <= hi


class MissionSafety:
    def __init__(self, preflight):
        self.preflight = preflight

    def validate(self, mission):
        issues = []

        # PREFLIGHT CHECK
        preflight = self.preflight.run_preflight()

        if not preflight["can_arm"]:
            issues.append({
                "type": "PREFLIGHT",
                "reason": "SYSTEM_NOT_READY",
                "details": preflight
            })

        # WAYPOINT VALIDATION
        if not mission or len(mission) == 0:
            issues.append({
                "type": "MISSION",
                "reason": "EMPTY_MISSION"
            })

        for i, wp in enumerate(mission or []):
            if not isinstance(wp, dict):
                issues.append({"type": "WAYPOINT", "index": i, "reason": "INVALID_ITEM"})
                continue
            command = wp.get("command")
            lat = wp.get("lat")
            lon = wp.get("lon")
            alt = wp.get("alt")

            # RTL carries no coordinates on the wire (PX4 expects
            # INT32_MAX/NaN for it), so don't require them here either.
            # NaN / Infinity / out-of-range values pass a plain `is None` test
            # and `alt < min_alt` is False for NaN, so they used to reach the
            # vehicle (or raise in int(lat * 1e7) mid-upload).
            if command != "RTL" and not (_is_number(lat, -90.0, 90.0)
                                         and _is_number(lon, -180.0, 180.0)):
                issues.append({
                    "type": "WAYPOINT",
                    "index": i,
                    "reason": "INVALID_COORDINATES"
                })

            # LAND waypoints may sit at ground level (alt 0); RTL altitude is
            # ignored by PX4; all other items must be at least 1 m to avoid a
            # zero-altitude cruise leg.
            if command == "RTL":
                continue
            min_alt = 0 if command == "LAND" else 1
            if not _is_number(alt, min_alt, 10000.0):
                issues.append({
                    "type": "WAYPOINT",
                    "index": i,
                    "reason": "INVALID_ALTITUDE"
                })

        # RESULT
        if issues:
            return {
                "valid": False,
                "issues": issues
            }

        return {
            "valid": True
        }