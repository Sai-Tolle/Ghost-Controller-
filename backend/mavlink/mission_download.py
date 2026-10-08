from pymavlink import mavutil
import time
import math


def safe_float(value):
    if value is None:
        return 0.0
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return 0.0
    return float(value)


class MissionDownloader:
    def __init__(self, mav_conn):
        self.mav_conn = mav_conn

        self.count_queue = []
        self.item_queue = []

        self.command_map = {
            16: "WAYPOINT",
            20: "RTL",
            21: "LAND",
            22: "TAKEOFF",
            17: "LOITER",
            19: "LOITER_TIME"
        }

    # SAFE MASTER 
    def _get_master(self):
        master = self.mav_conn.get_master()

        if not master:
            print("[MISSION DOWNLOAD] No MAVLink connection")
            return None, None, None

        return master, master.target_system, master.target_component

    # MESSAGE HANDLER
    def handle_message(self, msg):
        msg_type = msg.get_type()

        if msg_type == "MISSION_COUNT":
            self.count_queue.append(msg)

        elif msg_type in ["MISSION_ITEM", "MISSION_ITEM_INT"]:
            self.item_queue.append(msg)

    # MAIN DOWNLOAD 
    def download_mission(self):
        self.count_queue.clear()
        self.item_queue.clear()

        max_retries = 3

        # REQUEST COUNT 
        count_msg = None

        for attempt in range(max_retries):
            print(f"Requesting mission list (attempt {attempt + 1}/{max_retries})")

            master, ts, tc = self._get_master()
            if not master:
                return {"error": "Not connected"}

            self.mav_conn.send_mavlink(
                "mission_request_list_send",
                ts,
                tc,
                mavutil.mavlink.MAV_MISSION_TYPE_MISSION
            )

            start = time.time()

            while time.time() - start < 5:
                if self.count_queue:
                    count_msg = self.count_queue.pop(0)
                    break

                time.sleep(0.05)

            if count_msg:
                break

        if not count_msg:
            return {"error": "No mission count received after retries"}

        total = count_msg.count
        print(f"Mission count: {total}")

        if total == 0:
            return {"mission": []}

        mission = []

        # FETCH ITEMS 
        for i in range(total):
            item = None

            for attempt in range(max_retries):

                # Refresh connection EVERY retry
                master, ts, tc = self._get_master()
                if not master:
                    return {"error": "Connection lost during download"}

                # Remove stale items
                self.item_queue = [m for m in self.item_queue if m.seq != i]

                self.mav_conn.send_mavlink(
                    "mission_request_int_send",
                    ts,
                    tc,
                    i,
                    mavutil.mavlink.MAV_MISSION_TYPE_MISSION
                )

                start = time.time()

                while time.time() - start < 5:
                    for idx, msg in enumerate(self.item_queue):
                        if msg.seq == i:
                            item = self.item_queue.pop(idx)
                            break

                    if item:
                        break

                    time.sleep(0.05)

                if item:
                    break

                print(f"Retry item {i} (attempt {attempt + 1}/{max_retries})")

            if not item:
                # Send NACK before exit
                master, ts, tc = self._get_master()
                if master:
                    self.mav_conn.send_mavlink(
                        "mission_ack_send",
                        ts,
                        tc,
                        mavutil.mavlink.MAV_MISSION_ERROR,
                        mavutil.mavlink.MAV_MISSION_TYPE_MISSION
                    )

                return {"error": f"Failed to get item {i}"}

            #  EXTRACT DATA 

            if item.get_type() == 'MISSION_ITEM_INT':
                lat = item.x / 1e7
                lon = item.y / 1e7
            else:
                lat = item.x
                lon = item.y

            mission.append({
                "seq": item.seq,
                "command": self.command_map.get(item.command, f"UNKNOWN_{item.command}"),
                "frame": item.frame,
                "lat": safe_float(lat),
                "lon": safe_float(lon),
                "alt": safe_float(item.z),
                "params": {
                    "param1": safe_float(item.param1),
                    "param2": safe_float(item.param2),
                    "param3": safe_float(item.param3),
                    "param4": safe_float(item.param4),
                }
            })

            print(f"Downloaded item {i}")

        # FINAL ACK 
        master, ts, tc = self._get_master()
        if master:
            self.mav_conn.send_mavlink(
                "mission_ack_send",
                ts,
                tc,
                mavutil.mavlink.MAV_MISSION_ACCEPTED,
                mavutil.mavlink.MAV_MISSION_TYPE_MISSION
            )

        print("Mission download complete")

        return {"mission": mission}
