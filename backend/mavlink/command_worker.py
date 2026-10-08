import time as _time


def normalize_result(result):
    """Give every result a boolean `success`.

    Handlers return {"status": ...} on success and {"error": ...} on failure,
    never `success`; the desktop bridge keyed its mission/fence adoption on
    result["success"], so a downloaded mission was silently ignored."""
    if not isinstance(result, dict):
        return {"success": False, "error": str(result)}
    out = dict(result)
    out.setdefault("success", "error" not in out)
    return out


def command_worker(cmd_queue, command_handler, event_bus, mission_uploader, mission_safety,
                   mission_downloader, fence_uploader, fence_downloader):
    print(" Command Worker started (V3)")

    def publish(cmd_type, result):
        event_bus.publish_sync({
            "type": "command_result",
            "command": cmd_type,
            "result": result,
        })

    def mission_upload(data):
        mission = data.get("mission")
        validation = mission_safety.validate(mission)
        if not validation["valid"]:
            return {"success": False, "error": "MISSION_INVALID", "details": validation}
        return mission_uploader.upload_mission(mission)

    def mission_clear(_data):
        result = command_handler.clear_mission()
        if hasattr(mission_uploader, "clear_cache"):
            mission_uploader.clear_cache()
        return result

    handlers = {
        "ARM": lambda d: command_handler.arm(),
        "DISARM": lambda d: command_handler.disarm(),
        "TAKEOFF": lambda d: command_handler.takeoff(d.get("altitude", 10)),
        "LAND": lambda d: command_handler.land(),
        "RTL": lambda d: command_handler.rtl(),
        "MISSION_START": lambda d: command_handler.start_mission(),
        "ORBIT": lambda d: command_handler.orbit(
            lat=d.get("lat"), lon=d.get("lon"), alt=d.get("alt", 10.0),
            radius=d.get("radius", 15.0), velocity=d.get("velocity", 2.0)),
        "MODE": lambda d: command_handler.set_mode(d.get("mode")),
        "MISSION_UPLOAD": mission_upload,
        "MISSION_DOWNLOAD": lambda d: mission_downloader.download_mission(),
        "MISSION_CLEAR": mission_clear,
        "FENCE_UPLOAD": lambda d: fence_uploader.upload_fence(d.get("fence")),
        "FENCE_DOWNLOAD": lambda d: fence_downloader.download_fence(),
        "FENCE_CLEAR": lambda d: fence_downloader.clear_fence(),
        # KILL is normally handled out-of-band by BackendRuntime.kill(); kept
        # here for callers that still enqueue it (e.g. the web REST layer).
        "KILL": lambda d: command_handler.kill_switch(),
    }

    while True:
        cmd = cmd_queue.get()
        cmd_type = cmd.get("type")
        data = cmd.get("data") or {}
        reply_q = cmd.get("reply")
        print(f" CMD RECEIVED: {cmd_type}")

        handler = handlers.get(cmd_type)
        try:
            result = handler(data) if handler else {"error": f"UNKNOWN_COMMAND: {cmd_type}"}
        except Exception as e:  # noqa: BLE001 — one bad command must not kill the worker
            print(" COMMAND ERROR:", e)
            result = {"error": str(e)}
        result = normalize_result(result)

        if handler:
            publish(cmd_type, result)
        if cmd_type == "KILL" and "error" not in result:
            event_bus.publish_sync({
                "type": "health",
                "data": {"ready": False, "reason": "KILL",
                         "last_message": "KILL SWITCH — motors cut", "ts": _time.time()},
            })

        print(f" RESULT: {result}")
        if reply_q:
            reply_q.put(result)
