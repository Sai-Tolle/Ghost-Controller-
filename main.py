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

from app.application import run  # noqa: E402

if __name__ == "__main__":
    sys.exit(run(app_root=APP_ROOT, smoke=SMOKE))
