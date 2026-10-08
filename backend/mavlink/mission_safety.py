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

        for i, wp in enumerate(mission):
            command = wp.get("command")
            lat = wp.get("lat")
            lon = wp.get("lon")
            alt = wp.get("alt")

            # RTL carries no coordinates on the wire (PX4 expects
            # INT32_MAX/NaN for it), so don't require them here either.
            if command != "RTL" and (lat is None or lon is None):
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
            if alt is None or alt < min_alt:
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