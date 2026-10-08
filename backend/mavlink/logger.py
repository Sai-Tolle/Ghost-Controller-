from collections import deque
import time


class StatusTextLogger:
    def __init__(self, event_bus=None):
        self.messages = deque(maxlen=50)
        self.event_bus = event_bus

        # For reassembly
        self._buffer = ""
        self._last_time = 0

    def handle_message(self, msg):
        if msg.get_type() != "STATUSTEXT":
            return

        now = time.time()

        text = msg.text.strip("\x00").strip()

        #  REASSEMBLY 
        if now - self._last_time > 0.5:
            self._buffer = ""

        self._last_time = now

        self._buffer += text

        is_complete = len(text) < 50

        if not is_complete:
            return

        full_text = self._buffer.strip()
        self._buffer = ""

        #  STRUCTURE 
        entry = {
            "severity": msg.severity,
            "text": full_text,
            "type": self._classify(full_text),
            "timestamp": now
        }

        # print(f"[STATUS][{entry['type']}] {full_text}")
        self.messages.append(entry)
        
        if self.event_bus:
            is_not_ready = "arming denied" in full_text.lower()

            data = {
                "last_message": full_text,
                "severity": msg.severity,
                "type": entry["type"],
                "reason": self._extract_reason(full_text),
                "ts": time.time(),
            }
            # Only an arming denial changes readiness. Every other STATUSTEXT
            # used to publish ready=True and override the telemetry worker's
            # real LINK/GPS/RC/KILL decision (the HUD pill flipped green).
            if is_not_ready:
                data["ready"] = False
            self.event_bus.publish_sync({"type": "health", "data": data})

            # print("[EVENT BUS SENT]", full_text)
            # print("[RAW STATUSTEXT]", msg.text)
            
    # CLASSIFICATION 
    def _extract_reason(self, text):
        t = text.lower()
   
        if "arming denied" in t:
            return "ARM_BLOCK"

        if "gps" in t:
            return "GPS"
        if "ekf" in t:
            return "EKF"
        if "compass" in t:
            return "COMPASS"
        if "accel" in t:
            return "ACCEL"

        return "UNKNOWN"
    
    def _classify(self, text):
        t = text.lower()

        if "arming denied" in t:
            return "ARMING_DENIED"

        if "preflight fail" in t:
            return "PREFLIGHT_FAIL"

        if "gps" in t:
            return "GPS"

        if "ekf" in t:
            return "EKF"

        if "compass" in t:
            return "COMPASS"

        if "accel" in t:
            return "ACCEL"

        return "INFO"

    # FETCH 
    def fetch_and_clear(self):
        msgs = list(self.messages)
        self.messages.clear()
        return msgs
    
    def inject_reason(self, reason, message):
        if not self.event_bus:
            return

        self.event_bus.publish_sync({
            "type": "health",
            "data": {
                "last_message": message,
                "reason": reason,
                "ready": False,
                "ts": time.time()
            }
        })

        print(f"[INJECTED HEALTH] {reason} - {message}")