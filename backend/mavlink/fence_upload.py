from pymavlink import mavutil
import time


class FenceUploader:
    def __init__(self, mav_conn):
        self.mav_conn = mav_conn

        self.request_queue = []
        self.ack_queue = []

    # SAFE MASTER
    def _get_master(self):
        master = self.mav_conn.get_master()

        if not master:
            print("[FENCE UPLOAD] No MAVLink connection")
            return None, None, None

        return (
            master,
            master.target_system,
            master.target_component
        )

    # MESSAGE HANDLER
    def handle_message(self, msg):
        msg_type = msg.get_type()

        if msg_type in [
            "MISSION_REQUEST",
            "MISSION_REQUEST_INT"
        ]:
            self.request_queue.append(msg)

        elif msg_type == "MISSION_ACK":
            self.ack_queue.append(msg)

    # MAIN UPLOAD
    def upload_fence(self, fence):

        self.request_queue.clear()
        self.ack_queue.clear()

        count = len(fence)

        print(f"[FENCE] Uploading {count} fence points")

        master, ts, tc = self._get_master()

        if not master:
            return {"error": "No MAVLink connection"}

        # Send count
        self.mav_conn.send_mavlink(
            "mission_count_send",
            ts,
            tc,
            count,
            mavutil.mavlink.MAV_MISSION_TYPE_FENCE
        )

        retries = 0
        last_activity = time.time()

        while True:

            master, ts, tc = self._get_master()

            if not master:
                return {
                    "error": "Connection lost"
                }

            # REQUEST HANDLING
            if self.request_queue:

                msg = self.request_queue.pop(0)

                seq = msg.seq

                retries = 0
                last_activity = time.time()

                if seq >= count:
                    return {
                        "error": f"Invalid seq {seq}"
                    }

                p = fence[seq]

                self.mav_conn.send_mavlink(
                    "mission_item_int_send",
                    ts,
                    tc,
                    seq,
                    mavutil.mavlink.MAV_FRAME_GLOBAL,
                    mavutil.mavlink.MAV_CMD_NAV_FENCE_POLYGON_VERTEX_INCLUSION,
                    0,
                    0,
                    count,
                    0,
                    0,
                    0,
                    int(p["lat"] * 1e7),
                    int(p["lon"] * 1e7),
                    0,
                    mavutil.mavlink.MAV_MISSION_TYPE_FENCE
                )

            # ACK HANDLING
            elif self.ack_queue:

                ack = self.ack_queue.pop(0)

                if ack.type == mavutil.mavlink.MAV_MISSION_ACCEPTED:

                    print("[FENCE] Upload complete")

                    return {
                        "status": "Fence uploaded"
                    }

                return {
                    "error": f"Fence rejected ({ack.type})"
                }

            # TIMEOUT
            else:

                time.sleep(0.05)

                if time.time() - last_activity > 5:

                    retries += 1

                    last_activity = time.time()

                    print(f"[FENCE] Retry {retries}")

                if retries > 5:

                    return {
                        "error": "Fence upload timeout"
                    }
