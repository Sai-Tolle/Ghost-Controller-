from pymavlink import mavutil
import time


class MissionUploader:
    def __init__(self, mav_conn):
        self.mav_conn = mav_conn

        self.request_queue = []
        self.ack_queue = []

        self.command_map = {
            "WAYPOINT": mavutil.mavlink.MAV_CMD_NAV_WAYPOINT,
            "LAND": mavutil.mavlink.MAV_CMD_NAV_LAND,
            "RTL": mavutil.mavlink.MAV_CMD_NAV_RETURN_TO_LAUNCH,
            "TAKEOFF": mavutil.mavlink.MAV_CMD_NAV_TAKEOFF
        }

        # Human-readable names for MISSION_ACK failure codes so the operator
        # sees why PX4 rejected a mission instead of a bare integer.
        # Hardcoded from the MAVLink spec's MAV_MISSION_RESULT enum: some
        # pymavlink releases lack MAV_MISSION_INVALID_PARAM5..7 in the
        # ardupilotmega dialect, and dialect numbering can differ from what
        # PX4 (common dialect) actually sends.
        self.ack_names = {
            0: "ACCEPTED",
            1: "GENERIC_ERROR",
            2: "UNSUPPORTED_FRAME",
            3: "UNSUPPORTED",
            4: "NO_SPACE",
            5: "INVALID",
            6: "INVALID_PARAM1",
            7: "INVALID_PARAM2",
            8: "INVALID_PARAM3",
            9: "INVALID_PARAM4",
            10: "INVALID_PARAM5_X",
            11: "INVALID_PARAM6_Y",
            12: "INVALID_PARAM7_ALT",
            13: "INVALID_SEQUENCE",
            14: "DENIED",
            15: "OPERATION_CANCELLED",
        }

    @staticmethod
    def _mission_item_params(command: int):
        """Per-command param1..param4 for MISSION_ITEM_INT uploads.

        PX4 validates every param against its per-MAV_CMD support table
        (mavlink_command_params.hpp) and rejects the whole transfer with
        "IGN MISSION_ITEM: Invalid item" when an unsupported param is not
        NaN/0. Most notably MAV_CMD_NAV_RETURN_TO_LAUNCH (RTL) declares zero
        supported params, so lat/lon/alt must arrive as INT32_MAX/NaN.

        Returns (param1, param2, param3, param4, use_coords).
        """
        if command == mavutil.mavlink.MAV_CMD_NAV_RETURN_TO_LAUNCH:
            # RTL takes no params at all.
            return 0.0, 0.0, 0.0, 0.0, False

        if command == mavutil.mavlink.MAV_CMD_NAV_WAYPOINT:
            # param1: hold time (s), param2: acceptance radius (0 = default),
            # param4: yaw (NaN = face next waypoint).
            return 0.0, 0.0, 0.0, float('nan'), True

        if command == mavutil.mavlink.MAV_CMD_NAV_TAKEOFF:
            # param1: minimum pitch for FW (ignored for MC, 0 is accepted);
            # param4: yaw (NaN = current heading).
            return 0.0, 0.0, 0.0, float('nan'), True

        if command == mavutil.mavlink.MAV_CMD_NAV_LAND:
            # param1: abort altitude (0 = use MIS_LND_ABRT_ALT),
            # param2: precision (0 = default), param4: yaw (NaN = auto).
            return 0.0, 0.0, 0.0, float('nan'), True

        return 0.0, 0.0, 0.0, 0.0, True

    def _get_master(self):
        master = self.mav_conn.get_master()

        if not master:
            print("[MISSION UPLOAD] No MAVLink connection")
            return None, None, None

        return master, master.target_system, master.target_component

    def handle_message(self, msg):
        msg_type = msg.get_type()

        if msg_type in ["MISSION_REQUEST", "MISSION_REQUEST_INT"]:
            self.request_queue.append(msg)

        elif msg_type == "MISSION_ACK":
            self.ack_queue.append(msg)

    def _request_cb(self, msg):
        self.request_queue.append(msg)

    def _ack_cb(self, msg):
        self.ack_queue.append(msg)

    def upload_mission(self, mission):
        self.request_queue.clear()
        self.ack_queue.clear()

        count = len(mission)
        print(f"Uploading {count} mission items...")

        master, ts, tc = self._get_master()
        if not master:
            return {"error": "No MAVLink connection"}

        self.mav_conn.send_mavlink(
            "mission_count_send",
            ts,
            tc,
            count,
            mavutil.mavlink.MAV_MISSION_TYPE_MISSION
        )

        retries = 0
        last_activity = time.time()

        while True:
            # Always refresh connection
            master, ts, tc = self._get_master()
            if not master:
                return {"error": "Connection lost during upload"}

            # REQUEST HANDLING 
            if self.request_queue:
                msg = self.request_queue.pop(0)
                seq = msg.seq
                retries = 0
                last_activity = time.time()

                if seq >= count:
                    return {"error": f"Invalid seq requested: {seq}"}

                wp = mission[seq]
                cmd = wp.get("command", "WAYPOINT")
                mav_cmd = self.command_map.get(
                    cmd,
                    mavutil.mavlink.MAV_CMD_NAV_WAYPOINT
                )

                p1, p2, p3, p4, use_coords = self._mission_item_params(mav_cmd)

                self.mav_conn.send_mavlink(
                    "mission_item_int_send",
                    ts,
                    tc,
                    seq,
                    mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT,
                    mav_cmd,
                    1 if seq == 0 else 0,
                    1,
                    p1, p2, p3, p4,
                    # PX4 rejects coordinate values on param-less commands
                    # (e.g. RTL): it expects INT32_MAX lat/lon and NaN alt.
                    int(wp["lat"] * 1e7) if use_coords else 2147483647,
                    int(wp["lon"] * 1e7) if use_coords else 2147483647,
                    float(wp["alt"]) if use_coords else float('nan'),
                    mavutil.mavlink.MAV_MISSION_TYPE_MISSION
                )

            # ACK HANDLING 
            elif self.ack_queue:
                ack = self.ack_queue.pop(0)

                if ack.type == mavutil.mavlink.MAV_MISSION_ACCEPTED:
                    return {"status": "Mission uploaded"}

                name = self.ack_names.get(ack.type, f"CODE_{ack.type}")
                return {"error": f"Mission rejected ({name})"}

            # TIMEOUT HANDLING
            else:
                time.sleep(0.05)

                # timeout based on activity
                if time.time() - last_activity > 5:
                    retries += 1
                    last_activity = time.time()
                    print(f"[MISSION] Retry timeout {retries}")

                if retries > 5:
                    return {"error": "Mission upload timeout"}
