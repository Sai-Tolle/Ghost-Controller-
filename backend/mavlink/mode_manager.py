"""
Unified mode management for both PX4 and ArduPilot autopilots
"""

# PX4 MODE CONSTANTS
PX4_MODES = {
    "MANUAL":      (1, 0),
    "ALTCTL":      (2, 0),
    "POSCTL":      (3, 0),
    "ACRO":        (5, 0),
    "OFFBOARD":    (6, 0),
    "STABILIZED":  (7, 0),
    "RATTITUDE":   (8, 0),
    # AUTO sub-modes
    "AUTO_READY":  (4, 1),
    "TAKEOFF":     (4, 2),
    "LOITER":      (4, 3),
    "HOLD":        (4, 3),
    "MISSION":     (4, 4),
    "RTL":         (4, 5),
    "LAND":        (4, 6),
    "RTGS":        (4, 7),
    "FOLLOW_ME":   (4, 8),
    "PRECLAND":    (4, 9),
}

# ArduCopter MODE CONSTANTS
ARDUCOPTER_MODES = {
    "STABILIZE":   0,
    "ACRO":        1,
    "ALT_HOLD":    2,
    "AUTO":        3,
    "GUIDED":      4,
    "LOITER":      5,
    "RTL":         6,
    "CIRCLE":      7,
    "LAND":        9,
    "DRIFT":       11,
    "SPORT":       13,
    "FLIP":        14,
    "AUTOTUNE":    15,
    "POSHOLD":     16,
    "BRAKE":       17,
    "THROW":       18,
    "AVOID_ADGPS": 19,
    "GUIDED_NOGPS":20,
}

# Reverse mappings for decoding
# "HOLD" is an alias of "LOITER" (same (4, 3) tuple). A plain {v: k} dict
# comprehension lets the LAST key win, which decoded Loiter as "HOLD" — a name
# the UI mode list and the health GPS gate (requires_gps) do not know. Keep the
# FIRST name for each tuple so the canonical LOITER survives.
PX4_MODES_ALIASES = {"HOLD"}
PX4_MODES_REVERSE = {}
for _name, _tuple in PX4_MODES.items():
    if _name in PX4_MODES_ALIASES:
        continue
    PX4_MODES_REVERSE.setdefault(_tuple, _name)
ARDUCOPTER_MODES_REVERSE = {v: k for k, v in ARDUCOPTER_MODES.items()}


def decode_px4_mode(custom_mode: int) -> str:
    """Decode PX4 custom mode format"""
    main_mode = (custom_mode >> 16) & 0xFF
    sub_mode  = (custom_mode >> 24) & 0xFF
    
    mode_tuple = (main_mode, sub_mode)
    if mode_tuple in PX4_MODES_REVERSE:
        return PX4_MODES_REVERSE[mode_tuple]
    
    return f"UNKNOWN_PX4({main_mode},{sub_mode})"


def decode_arducopter_mode(custom_mode: int) -> str:
    """Decode ArduCopter mode (simple integer)"""
    if custom_mode in ARDUCOPTER_MODES_REVERSE:
        return ARDUCOPTER_MODES_REVERSE[custom_mode]
    
    return f"UNKNOWN_ARDUPILOT({custom_mode})"


def decode_mode(custom_mode: int, autopilot: str = "PX4") -> str:
    """
    Universal mode decoder
    
    Args:
        custom_mode: The mode value from heartbeat
        autopilot: "PX4" or "ArduPilot"
    
    Returns:
        Human-readable mode string
    """
    if autopilot == "PX4":
        return decode_px4_mode(custom_mode)
    elif autopilot == "ArduPilot":
        return decode_arducopter_mode(custom_mode)
    else:
        return f"UNKNOWN({custom_mode})"


def get_mode_map(autopilot: str):
    """Get the mode map for the specified autopilot"""
    if autopilot == "PX4":
        return PX4_MODES
    elif autopilot == "ArduPilot":
        return ARDUCOPTER_MODES
    else:
        return {}


def encode_px4_mode(mode_name: str) -> tuple | None:
    """
    Encode mode name to PX4 format
    
    Returns:
        (main_mode, sub_mode) tuple or None if not found
    """
    return PX4_MODES.get(mode_name)


def encode_arducopter_mode(mode_name: str) -> int | None:
    """
    Encode mode name to ArduCopter format
    
    Returns:
        Custom mode integer or None if not found
    """
    return ARDUCOPTER_MODES.get(mode_name)
