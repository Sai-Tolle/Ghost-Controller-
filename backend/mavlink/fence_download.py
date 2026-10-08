from pymavlink import mavutil
import time


class FenceDownloader:
    def __init__(self, mav_conn):
        self.mav_conn = mav_conn

        # Shared queues populated by handle_message() from the reader thread
        self._count_queue: list = []
        self._item_queue:  list = []
        self._ack_queue:   list = []

    # Called from telemetry_worker for every incoming MAVLink message

    def handle_message(self, msg):
        msg_type = msg.get_type()

        if msg_type == "MISSION_COUNT":
            # Only capture fence-type counts
            mission_type = getattr(msg, "mission_type", 0)
            if mission_type == mavutil.mavlink.MAV_MISSION_TYPE_FENCE:
                self._count_queue.append(msg)

        elif msg_type in ("MISSION_ITEM", "MISSION_ITEM_INT"):
            mission_type = getattr(msg, "mission_type", 0)
            if mission_type == mavutil.mavlink.MAV_MISSION_TYPE_FENCE:
                self._item_queue.append(msg)

        elif msg_type == "MISSION_ACK":
            mission_type = getattr(msg, "mission_type", 0)
            if mission_type == mavutil.mavlink.MAV_MISSION_TYPE_FENCE:
                self._ack_queue.append(msg)

    # Internal helpers
    def _get_master(self):
        master = self.mav_conn.get_master()
        if not master:
            return None, None, None
        return master, master.target_system, master.target_component

    def _wait_for(self, queue: list, timeout: float = 5.0):
        """Block until queue has an item or timeout expires."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if queue:
                return queue.pop(0)
            time.sleep(0.02)
        return None

    # Public API called from command_worker
    def download_fence(self) -> dict:
        self._count_queue.clear()
        self._item_queue.clear()
        self._ack_queue.clear()

        master, ts, tc = self._get_master()
        if not master:
            return {"error": "No MAVLink connection"}

        print("[FENCE DL] Requesting fence count")

        #1 request the count
        self.mav_conn.send_mavlink(
            "mission_request_list_send",
            ts,
            tc,
            mavutil.mavlink.MAV_MISSION_TYPE_FENCE,
        )

        # 2 wait for MISSION_COUNT
        count_msg = self._wait_for(self._count_queue, timeout=5.0)
        if count_msg is None:
            return {"error": "Fence count timeout"}

        count = count_msg.count
        print(f"[FENCE DL] Fence has {count} points")

        if count == 0:
            # Send ACK so the vehicle stops waiting
            self.mav_conn.send_mavlink(
                "mission_ack_send",
                ts, tc,
                mavutil.mavlink.MAV_MISSION_ACCEPTED,
                mavutil.mavlink.MAV_MISSION_TYPE_FENCE,
            )
            return {"fence": []}

        # 3 request items one-by-one
        fence_points = []

        for seq in range(count):
            # Request item
            self.mav_conn.send_mavlink(
                "mission_request_int_send",
                ts,
                tc,
                seq,
                mavutil.mavlink.MAV_MISSION_TYPE_FENCE,
            )

            item = None
            retries = 0

            while item is None and retries < 3:
                item = self._wait_for(self._item_queue, timeout=3.0)

                if item is not None and item.seq != seq:
                    # Wrong seq put back and keep waiting
                    self._item_queue.insert(0, item)
                    item = None

                if item is None:
                    retries += 1
                    print(f"[FENCE DL] Retry seq={seq} ({retries})")
                    self.mav_conn.send_mavlink(
                        "mission_request_int_send",
                        ts, tc, seq,
                        mavutil.mavlink.MAV_MISSION_TYPE_FENCE,
                    )

            if item is None:
                return {"error": f"Timeout waiting for fence item {seq}"}

            fence_points.append({
                "lat": item.x / 1e7,
                "lon": item.y / 1e7,
            })

        # 4 send final ACK
        self.mav_conn.send_mavlink(
            "mission_ack_send",
            ts, tc,
            mavutil.mavlink.MAV_MISSION_ACCEPTED,
            mavutil.mavlink.MAV_MISSION_TYPE_FENCE,
        )

        print(f"[FENCE DL] Done – {len(fence_points)} points")
        return {"fence": fence_points}

    # Clear fence on vehicle
    def clear_fence(self) -> dict:
        self._ack_queue.clear()

        master, ts, tc = self._get_master()
        if not master:
            return {"error": "No MAVLink connection"}

        print("[FENCE] Clearing fence on vehicle")

        self.mav_conn.send_mavlink(
            "mission_clear_all_send",
            ts,
            tc,
            mavutil.mavlink.MAV_MISSION_TYPE_FENCE,
        )

        ack = self._wait_for(self._ack_queue, timeout=5.0)
        if ack is None:
            return {"error": "Fence clear timeout – no ACK"}

        if ack.type == mavutil.mavlink.MAV_MISSION_ACCEPTED:
            print("[FENCE] Cleared")
            return {"status": "Fence cleared"}

        return {"error": f"Fence clear rejected (type={ack.type})"}
