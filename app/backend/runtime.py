"""Run the PROVEN GCS backend worker stack in-process.

The backend is VENDORED in this repository (`<desktop>/backend/mavlink/`
holds the proven web GCS's MAVLink worker stack) so the desktop is fully
self-contained: no sibling checkout is needed. `GH_BACKEND_PATH` may still
point at an external backend checkout for A/B debugging, and
`GH_BACKEND_PATH=none` disables the stack entirely.

Construction mirrors `GCS/main.py` startup exactly — same construction order,
same thread layout — minus FastAPI/HTTP, vision and the AI assistant, which
the native shell does not ship:

    reader thread          mav_conn.recv_msg()  -> msg_queue
    telemetry_worker       msg_queue  -> shared_state + telemetry_queue (10 Hz)
    state_worker           state_queue -> shared_state (debounced state machine)
    command_worker         cmd_queue   -> CommandHandler (ACKed via event_bus)
    health_worker          health_queue -> health snapshots
    asyncio loop thread    preflight.stream + GCSHeartbeat (like main.py)

Every UI command is submitted to `cmd_queue` — the exact queue the web GCS's
REST API uses — so command_guard, preflight and mission-safety validation in
the proven backend apply unchanged. The desktop never talks MAVLink directly.

The EventBus gets a no-op WebSocketManager stand-in: `publish_sync` schedules
`publish` onto the loop, which broadcasts JSON to web clients. There are none
here, so broadcast is a cheap no-op; our own consumers hook events through
`EventBus.register` (a small desktop-side addition to the bus instance — the
stock publish path is untouched, so the web HUD still works if the backend
serves it elsewhere).
"""
from __future__ import annotations

import asyncio
import os
import sys
import threading
import time
from pathlib import Path
from queue import Empty, Queue

# Vendored proven backend, shipped inside this repository.
VENDORED_BACKEND = Path(__file__).resolve().parents[2] / "backend"


class _NullWebSocketManager:
    """Duck-types ws.manager.WebSocketManager for the EventBus."""

    active_connections: list = []

    def connect(self, websocket):  # pragma: no cover - parity only
        raise NotImplementedError("desktop runtime has no web sockets")

    def disconnect(self, websocket):  # pragma: no cover
        pass

    async def broadcast(self, message: str) -> None:
        return None  # no web clients in the native shell


def _ensure_backend_on_path(gcs_path: Path) -> None:
    path = str(gcs_path.resolve())
    if not (Path(path) / "mavlink" / "connection.py").exists():
        raise RuntimeError(f"{path} does not look like the GCS backend repo")
    if path not in sys.path:
        sys.path.insert(0, path)
    env_file = Path(path) / "gcs.env"
    if env_file.exists():
        try:
            from dotenv import load_dotenv

            load_dotenv(env_file)
        except ImportError:
            # Minimal parser so MAVLINK_CONNECTION etc. still work without
            # python-dotenv installed in the desktop venv.
            for line in env_file.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    os.environ.setdefault(key.strip(), value.strip().strip("'\""))


class BackendRuntime:
    """Owns the proven backend worker stack, wired exactly like main.py."""

    def __init__(self, gcs_path: Path | None = None) -> None:
        _ensure_backend_on_path(Path(gcs_path).expanduser().resolve() if gcs_path else VENDORED_BACKEND)

        # Imports happen HERE (not module level) so the desktop app can boot
        # without the backend and report a clear error instead of crashing.
        from mavlink.command_guard import CommandGuard
        from mavlink.command_worker import command_worker
        from mavlink.commands import CommandHandler
        from mavlink.connection import MAVLinkConnection
        from mavlink.event_bus import EventBus
        from mavlink.fence_download import FenceDownloader
        from mavlink.fence_upload import FenceUploader
        from mavlink.gcs_heartbeat import GCSHeartbeat
        from mavlink.health_worker import HealthWorker
        from mavlink.logger import StatusTextLogger
        from mavlink.mission_download import MissionDownloader
        from mavlink.mission_upload import MissionUploader
        from mavlink.mission_safety import MissionSafety
        from mavlink.preflight import PreflightSystem
        from mavlink.shared_state import SharedState
        from mavlink.state_worker import StateWorker
        from mavlink.telemetry_worker import telemetry_worker
        # NOTE: ws.manager is NOT imported — it would pull FastAPI into the
        # desktop venv. _NullWebSocketManager below duck-types the one method
        # EventBus uses (broadcast), keeping the desktop MAVLink layer
        # FastAPI-free. The AI orchestrator is likewise NOT constructed — the
        # desktop build ships without the AI flight assistant.

        self.msg_queue: Queue = Queue()
        self.cmd_queue: Queue = Queue()
        self.state_queue: Queue = Queue()
        self.health_queue: Queue = Queue()
        self.telemetry_queue: Queue = Queue()

        # --- construction order copied from GCS/main.py -------------------
        self.ws_manager = _NullWebSocketManager()
        self.event_bus = EventBus(self.ws_manager)
        # Desktop subscribers fire on the loop thread inside publish(); keep
        # callbacks cheap (dict assignments only).
        self.event_bus.subscribers.append(self._dispatch_event)
        self._event_subscribers: list = []

        self.mav_conn = MAVLinkConnection(event_bus=self.event_bus)
        self.health_worker = HealthWorker(self.health_queue, self.event_bus)
        self.commands = CommandHandler(self.mav_conn)
        self.status_logger = StatusTextLogger(event_bus=self.event_bus)
        self.mission_downloader = MissionDownloader(self.mav_conn)
        self.mission_uploader = MissionUploader(self.mav_conn)
        self.fence_uploader = FenceUploader(self.mav_conn)
        self.fence_downloader = FenceDownloader(self.mav_conn)
        self.shared_state = SharedState()
        self.preflight = PreflightSystem(self.shared_state, self.health_worker)
        self.guard = CommandGuard(self.shared_state, self.health_worker, self.event_bus, self.preflight)
        from mavlink.command_executor import CommandExecutor

        self.executor = CommandExecutor(self.guard, self.commands, self.event_bus)
        self.mission_safety = MissionSafety(self.preflight)
        self.gcs_heartbeat = GCSHeartbeat(self.mav_conn)
        self.state_worker = StateWorker(self.state_queue, self.event_bus, self.shared_state, self.mav_conn)
        from mavlink.params import ParamManager

        self.params = ParamManager(self.mav_conn, is_armed=lambda: bool(self.shared_state.armed))
        # Cached parameters belong to one vehicle: drop them synchronously on
        # every new / ended link session.
        self.mav_conn.session_listeners.append(lambda _status: self.params.reset())
        self._telemetry_worker_fn = telemetry_worker
        self._command_worker_fn = command_worker

        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

    # ------------------------------------------------------------------
    # desktop-side event subscription (additive; stock path untouched)
    # ------------------------------------------------------------------

    def subscribe(self, callback) -> None:
        self._event_subscribers.append(callback)

    def _dispatch_event(self, event: dict) -> None:
        for cb in tuple(self._event_subscribers):
            try:
                cb(event)
            except Exception as exc:  # noqa: BLE001 — observers must not kill the bus
                print(f"[backend] subscriber error: {exc}")

    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start reader, workers and the asyncio loop (preflight+heartbeat)."""
        self._stop.clear()

        def connection_thread() -> None:
            try:
                # Blocking by design: retries forever until a vehicle
                # heartbeat arrives (identical to backend behavior).
                self.mav_conn.connect()
            except Exception as exc:  # pragma: no cover — env specific
                print(f"[backend] connection thread ended: {exc}")

        def reader_thread() -> None:
            while not self._stop.is_set():
                try:
                    if not self.mav_conn.enabled:
                        time.sleep(0.2)          # operator disconnected: idle, don't spin
                        continue
                    msg = self.mav_conn.recv_msg()
                    if msg:
                        if self.mav_conn.is_vehicle_message(msg):
                            if msg.get_type() == "PARAM_VALUE":
                                # Parameter traffic goes straight to the
                                # parameter manager (can be 1000+ msgs in a
                                # burst; the telemetry worker has no use for it).
                                self.params.handle_message(msg)
                            else:
                                self.msg_queue.put(msg)
                    else:
                        time.sleep(0.01)
                except Exception as exc:
                    if not self._stop.is_set():
                        print(f"[backend] reader error: {exc}")
                    time.sleep(0.2)

        def telemetry_thread() -> None:
            self._telemetry_worker_fn(
                self.msg_queue, self.event_bus, self.state_queue,
                self.health_queue, self.shared_state, self.commands,
                self.mission_downloader, self.mission_uploader,
                self.fence_uploader, self.fence_downloader,
                self.status_logger, self.mav_conn,
                out_queue=self.telemetry_queue,
            )

        def command_thread() -> None:
            self._command_worker_fn(
                self.cmd_queue, self.commands, self.event_bus,
                self.mission_uploader, self.mission_safety,
                self.mission_downloader, self.fence_uploader, self.fence_downloader,
            )

        def health_thread() -> None:
            self.health_worker.run()

        def state_thread() -> None:
            self.state_worker.run()

        def loop_thread() -> None:
            loop = asyncio.new_event_loop()
            self._loop = loop
            asyncio.set_event_loop(loop)
            self.event_bus.set_loop(loop)  # plain sync setter (mavlink/event_bus.py)

            async def _start_tasks() -> None:
                self._preflight_task = asyncio.create_task(self.preflight.stream(self.event_bus))
                self._heartbeat_task = asyncio.create_task(self.gcs_heartbeat.run())

            loop.run_until_complete(_start_tasks())
            loop.run_forever()
            loop.close()

        # NOTE: telemetry_worker signature gains `out_queue` via keyword —
        # see the extension note in GCS/mavlink/telemetry_worker.py.
        for target in (connection_thread, reader_thread, telemetry_thread,
                       command_thread, health_thread, state_thread, loop_thread):
            t = threading.Thread(target=target, daemon=True, name=target.__name__)
            t.start()
            self._threads.append(t)

    def stop(self) -> None:
        """Signal shutdown and stop the asyncio loop.

        The worker threads are daemons by design — the proven backend runs
        them for the life of the process (same as GCS/main.py), so a desktop
        restart of the stack means rebuilding a BackendRuntime.
        """
        self._stop.set()
        try:
            # Also stops a connect loop that is still waiting for a heartbeat
            # (it used to keep retrying — and could reopen the port — after stop).
            self.mav_conn.set_enabled(False)
            self.mav_conn._close_candidate()
        except Exception:  # noqa: BLE001
            pass
        loop = self._loop
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(loop.stop)

    # ------------------------------------------------------------------
    # command submission — the same queue the web REST API feeds
    # ------------------------------------------------------------------

    def submit(self, cmd_type: str, data: dict | None = None) -> None:
        item: dict = {"type": cmd_type}
        if data is not None:
            item["data"] = data
        self.cmd_queue.put(item)

    # ------------------------------------------------------------------
    # guarded + emergency paths
    # ------------------------------------------------------------------

    def _publish_result(self, cmd_type: str, result: dict) -> None:
        from mavlink.command_worker import normalize_result

        self.event_bus.publish_sync({
            "type": "command_result", "command": cmd_type,
            "result": normalize_result(result),
        })

    def _guarded(self, ctype, cmd_type: str, data: dict | None = None) -> None:
        """Run the command through CommandGuard (preflight, cooldown, in-air
        rules) and only then enqueue it.

        The runtime used to drop UI commands straight into cmd_queue, so the
        guard that the module docs promise was never consulted: DISARM in the
        air, TAKEOFF while flying and double-clicked ARM all went through."""
        def run() -> None:
            loop = self._loop
            if loop is None or not loop.is_running():
                self._publish_result(cmd_type, {"error": "Backend not ready"})
                return
            try:
                fut = asyncio.run_coroutine_threadsafe(self.guard.validate(ctype), loop)
                allowed, reason = fut.result(timeout=3.0)
            except Exception as exc:  # noqa: BLE001
                self._publish_result(cmd_type, {"error": f"Guard error: {exc}"})
                return
            if not allowed:
                detail = reason if isinstance(reason, str) else (reason or {}).get("reason", "BLOCKED")
                self._publish_result(cmd_type, {"error": f"Blocked: {detail}", "blocked": True,
                                                "details": reason if isinstance(reason, dict) else None})
                return
            self.submit(cmd_type, data)

        threading.Thread(target=run, daemon=True, name=f"guard-{cmd_type}").start()

    def _emergency(self, cmd_type: str, fn) -> None:
        """Run on a dedicated thread: never wait behind the command queue."""
        def run() -> None:
            try:
                result = fn()
            except Exception as exc:  # noqa: BLE001
                result = {"error": str(exc)}
            self._publish_result(cmd_type, result)
            if cmd_type == "KILL" and "error" not in result:
                self.event_bus.publish_sync({
                    "type": "health",
                    "data": {"ready": False, "reason": "KILL",
                             "last_message": "KILL SWITCH — motors cut", "ts": time.time()},
                })

        threading.Thread(target=run, daemon=True, name=f"emergency-{cmd_type}").start()

    def set_mode(self, mode: str) -> None:
        self.submit("MODE", {"mode": mode})

    def arm(self) -> None:
        from mavlink.command_guard import CommandType
        self._guarded(CommandType.ARM, "ARM")

    def disarm(self) -> None:
        from mavlink.command_guard import CommandType
        self._guarded(CommandType.DISARM, "DISARM")

    def kill(self) -> None:
        self._emergency("KILL", self.commands.kill_switch)

    def takeoff(self, altitude: float) -> None:
        from mavlink.command_guard import CommandType
        self._guarded(CommandType.TAKEOFF, "TAKEOFF", {"altitude": float(altitude)})

    def land(self) -> None:
        from mavlink.command_guard import CommandType
        self._guarded(CommandType.LAND, "LAND")

    def rtl(self) -> None:
        self._emergency("RTL", self.commands.rtl)
