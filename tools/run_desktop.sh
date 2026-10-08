#!/usr/bin/env bash
# Launch the desktop GCS.
#
# The backend is VENDORED in this repository (backend/mavlink) and runs
# in-process — no sibling GCS checkout is needed or attached. Set
# MAVLINK_CONNECTION in backend/gcs.env (or override it here) to choose the
# vehicle transport; with nothing set it falls back to udpin:127.0.0.1:14550
# (the PX4 SITL convention). To point the runtime at an external backend
# checkout for debugging: GH_BACKEND_PATH=/path/to/backend tools/run_desktop.sh
#
# Usage: tools/run_desktop.sh [--sim] [extra main.py args]
set -euo pipefail
cd "$(dirname "$0")/.." || exit 1

# Vendored backend is the default; only honor an explicit override.
: "${GH_BACKEND_PATH:=$(pwd)/backend}"

echo "[run-desktop] backend: $GH_BACKEND_PATH" >&2
export GH_BACKEND_PATH

exec .venv-desktop/bin/python main.py "$@"
