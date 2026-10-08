import threading


class SharedState:
    def __init__(self):
        self._lock = threading.Lock()

        self.state = "DISCONNECTED"
        self.armed = False
        self.mode = "UNKNOWN"
        self.altitude = 0      # metres ABOVE HOME (relative), not AMSL
        self.lat = None
        self.lon = None
        self.yaw = None
        self.connected = False

    def update(self, state=None, armed=None, mode=None, altitude=None, lat=None, lon=None, yaw=None, connected=None):
        with self._lock:
            if state is not None:
                self.state = state
            if armed is not None:
                self.armed = armed
            if mode is not None:
                self.mode = mode
            if altitude is not None:
                self.altitude = altitude
            if lat is not None:
                self.lat = lat
            if lon is not None:
                self.lon = lon
            if yaw is not None:
                self.yaw = yaw
            if connected is not None:
                self.connected = connected

    def get(self):
        with self._lock:
            return {
                "state": self.state,
                "armed": self.armed,
                "mode": self.mode,
                "altitude": self.altitude,
                "lat": self.lat,
                "lon": self.lon,
                "yaw": self.yaw,
                "connected": self.connected
            }