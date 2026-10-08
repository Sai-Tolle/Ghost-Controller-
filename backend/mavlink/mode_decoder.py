def decode_mode(custom_mode: int) -> str:
    main_mode = (custom_mode >> 16) & 0xFF
    sub_mode  = (custom_mode >> 24) & 0xFF

    MANUAL     = 1
    ALTCTL     = 2
    POSCTL     = 3
    AUTO       = 4
    ACRO       = 5
    OFFBOARD   = 6
    STABILIZED = 7
    RATTITUDE  = 8

    AUTO_READY     = 1
    AUTO_TAKEOFF   = 2
    AUTO_LOITER    = 3
    AUTO_MISSION   = 4
    AUTO_RTL       = 5
    AUTO_LAND      = 6
    AUTO_RTGS      = 7
    AUTO_FOLLOW_ME = 8
    AUTO_PRECLAND  = 9

    if main_mode == MANUAL:     return "MANUAL"
    if main_mode == ALTCTL:     return "ALTCTL"
    if main_mode == POSCTL:     return "POSCTL"
    if main_mode == ACRO:       return "ACRO"
    if main_mode == OFFBOARD:   return "OFFBOARD"
    if main_mode == STABILIZED: return "STABILIZED"
    if main_mode == RATTITUDE:  return "RATTITUDE"

    if main_mode == AUTO:
        return {
            AUTO_READY:     "AUTO_READY",
            AUTO_TAKEOFF:   "TAKEOFF",
            AUTO_LOITER:    "LOITER",
            AUTO_MISSION:   "MISSION",
            AUTO_RTL:       "RTL",
            AUTO_LAND:      "LAND",
            AUTO_RTGS:      "RTGS",
            AUTO_FOLLOW_ME: "FOLLOW_ME",
            AUTO_PRECLAND:  "PRECLAND",
        }.get(sub_mode, f"AUTO({sub_mode})")

    return f"UNKNOWN({main_mode},{sub_mode})"