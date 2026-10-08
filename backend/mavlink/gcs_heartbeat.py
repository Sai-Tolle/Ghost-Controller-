import asyncio
from pymavlink import mavutil
import time


class GCSHeartbeat:
    def __init__(self, mav_conn):
        self.mav_conn = mav_conn  # store connection, not master
        self.last_client_seen = time.time()
        self.client_connected_flag = False

    async def run(self):
        while True:
            if self.mav_conn.is_vehicle_alive():
                self.mav_conn.send_mavlink(
                    "heartbeat_send",
                    mavutil.mavlink.MAV_TYPE_GCS,
                    mavutil.mavlink.MAV_AUTOPILOT_INVALID,
                    0,
                    0,
                    0,
                )

            await asyncio.sleep(1)

    def client_connected(self):
        print("GCS Client Connected")
        self.last_client_seen = time.time()
        self.client_connected_flag = True

    def client_disconnected(self):
        print("GCS Client Disconnected")
        self.last_client_seen = time.time()
        self.client_connected_flag = False
