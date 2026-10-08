#!/usr/bin/env bash
# Run the native desktop GCS against PX4 SITL (gz_gcs_cam: x500 + nadir
# RTP/H.264 camera on UDP 5600, telemetry on UDP 14550).
#
# Steps:
#   1. install the gcs_cam model + airframe + world into ~/PX4-Autopilot
#      (idempotent; tests/sitl_e2e_test.py --cleanup removes them again)
#   2. start PX4 SITL headless (build/sitl-px4.log)
#   3. launch the desktop app with the VENDORED backend (backend/mavlink,
#      no external checkout) — the full in-process backend stack (telemetry,
#      commands, preflight) plus the video panel (auto mode detects the SITL
#      camera on 5600 first) and the offline Zurich basemap from
#      maps/osm-zurich.
#
# Usage: tools/run_sitl_desktop.sh [--no-video]
set -u
cd "$(dirname "$0")/.." || exit 1

PY=.venv-desktop/bin/python
[ -x "$PY" ] || { echo "desktop venv missing — see README"; exit 1; }

# 1. install SITL model/airframe/world (idempotent)
GH_BACKEND_PATH= "$PY" -c "
import sys; sys.path.insert(0, '.')
sys.argv = ['x']
from tests.sitl_e2e_test import install_or_cleanup
install_or_cleanup(False)
" || exit 1

# stop leftovers from a previous run
pkill -f "[b]in/px4" 2>/dev/null
pkill -f "[g]z sim" 2>/dev/null
sleep 1

# 2. PX4 SITL headless in the background
mkdir -p build
PX4_DIR="${PX4_DIR:-$HOME/PX4-Autopilot}"
(
  cd "$PX4_DIR" || exit 1
  HEADLESS=1 PX4_GZ_SIM_GUI=0 PX4_GZ_WORLD=vehicle_test_lite \
    make px4_sitl gz_gcs_cam
) > build/sitl-px4.log 2>&1 &
SITL_PID=$!
echo "[sitl] px4 starting (pid $SITL_PID, log build/sitl-px4.log)"

# 3. desktop app against it (vendored backend default; explicit override wins)
export GH_BACKEND_PATH="${GH_BACKEND_PATH:-$(pwd)/backend}"
export MAVLINK_FALLBACK="${MAVLINK_FALLBACK:-udpin:127.0.0.1:14550}"
export MAVLINK_REQUIRE_CONNECTION=0
echo "[desktop] launching with backend=$GH_BACKEND_PATH (video auto-detects udp/5600)"
exec "$PY" main.py
