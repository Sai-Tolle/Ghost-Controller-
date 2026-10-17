#!/usr/bin/env python3
"""Ghost Handler — native ground control station (PySide6 + QML).

Entry point. Usage:
    python main.py              # normal desktop launch (NO vehicle link
                                # unless GH_BACKEND_PATH is set — the HUD
                                # shows NO LINK, it never fakes a vehicle)
    python main.py --sim        # simulated flight for UI development/demo
    python main.py --smoke      # headless boot test: offscreen render, save
                                # build/smoke.png, exit 0 on success
"""
import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent
SMOKE = "--smoke" in sys.argv
SIM = "--sim" in sys.argv

if SIM:
    # Explicit simulation request — honoured by app.bridge.backend.build_source.
    import os

    os.environ["GH_SIM"] = "1"

if SMOKE:
    # Must be set before Qt is imported: force software QML rendering so the
    # boot test works on headless CI machines with no GPU/display.
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("QT_QUICK_BACKEND", "software")

sys.path.insert(0, str(APP_ROOT))


def _enable_crash_log() -> None:
    """Native crashes (Qt, FFmpeg, PySide) kill the process without a Python
    traceback, and a desktop launch has no terminal — the app just vanishes.
    faulthandler writes every thread's stack to a file on SIGSEGV/SIGABRT so
    a tester can send it. ~/.cache/ghost-controller/crash.log"""
    import faulthandler
    import os
    import time

    cache = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "ghost-controller"
    try:
        cache.mkdir(parents=True, exist_ok=True)
        log = cache / "crash.log"
        if log.exists() and log.stat().st_size > 1_000_000:   # keep it bounded
            log.unlink()
        fh = open(log, "a", buffering=1)
        fh.write(f"\n=== start {time.strftime('%Y-%m-%d %H:%M:%S')} pid {os.getpid()} ===\n")
        faulthandler.enable(file=fh, all_threads=True)
        globals()["_CRASH_LOG_FH"] = fh                       # keep the fd open for the handler
    except OSError:
        faulthandler.enable()                                 # fall back to stderr


_enable_crash_log()

from app.application import run  # noqa: E402

if __name__ == "__main__":
    sys.exit(run(app_root=APP_ROOT, smoke=SMOKE))
