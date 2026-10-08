# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for Ghost Handler Desktop (Linux first, then Windows).
#
#   pyinstaller packaging/ghost-handler.spec
#
# The backend is VENDORED inside this repository (backend/mavlink), so the
# bundle ships it like any other package — no external checkout needed.
# The desktop build contains NO AI / vision modules.
from pathlib import Path

APP_ROOT = Path(SPECPATH).parent

a = Analysis(
    [str(APP_ROOT / "main.py")],
    pathex=[str(APP_ROOT)],
    binaries=[],
    datas=[
        (str(APP_ROOT / "backend"), "backend"),
        (str(APP_ROOT / "qml"), "qml"),
        (str(APP_ROOT / "design"), "design"),
        (str(APP_ROOT / "assets"), "assets"),
    ],
    # pymavlink bundling: the vendored backend imports `from pymavlink import
    # mavutil` and uses `mavutil.mavlink` (a MAVLink dialect) + the DFReader /
    # mavextra / mavparm helpers. PyInstaller's static analysis does NOT see the
    # dynamic `importlib.import_module("pymavlink.dialects.vX0.<dialect>")` that
    # mavutil performs inside set_dialect(), so we must name every module the
    # backend (and mavutil's auto-dialect loading) can reach.
    #
    # Core pymavlink modules the backend touches directly:
    hiddenimports=[
        "pymavlink",
        "pymavlink.mavutil",        # from pymavlink import mavutil  (used everywhere)
        "pymavlink.DFReader",        # DF reading (mavlink log / telemetry)
        "pymavlink.mavextra",        # mavlink helpers the backend uses
        "pymavlink.mavparm",         # parameter file parsing
        "pymavlink.quaternion",
        "pymavlink.rotmat",
        "pymavlink.CSVReader",
        "pymavlink.fgFDM",
        # MAVLink dialects — comprehensive v1.0 + v2.0 "all" builds so the
        # backend has every MAV_CMD / MAV_RESULT / MAV_* constant for both PX4
        # (common) and ArduPilot (ardupilotmega) regardless of the dialect
        # pymavlink auto-selects at import time (default: v10.ardupilotmega).
        "pymavlink.dialects.v10.all",
        "pymavlink.dialects.v20.all",
        # serial / dotenv (backend gcs.env loader + MAVLink serial transport)
        "serial",
        "serial.tools",
        "dotenv",
    ],
    excludes=[
        # Desktop build ships NO AI / vision stack.
        "torch", "torchvision", "ultralytics", "openai",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ghost-handler",
    debug=False,
    strip=False,
    upx=False,
    console=True,  # keep stdout/stderr visible for field diagnostics
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="ghost-handler",
)
