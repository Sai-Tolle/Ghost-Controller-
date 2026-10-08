#!/usr/bin/env bash
# Fetch a small offline OSM basemap around the PX4 SITL home position
# (Zurich, 47.397742N 8.545594E) into maps/osm-zurich/{z}/{x}/{y}.png.
#
# Resumable: existing non-empty files are skipped, so re-running after a
# network hiccup continues where it left off. Politeness: 0.3 s between
# requests + a real User-Agent (tile.openstreetmap.org usage policy).
#
# Tile math (slippy map, XYZ): x = (lon+180)/360 * 2^z,
# y = (1 - asinh(tan(lat))/pi)/2 * 2^z. For 47.397742N 8.545594E:
#   z10 → (536,358)   z11 → (1072,717)  z12 → (2145,1434)
#   z13 → (4290,2868) z14 → (8580,5736)
#
# Usage: tools/fetch_osm_tiles.sh [max_zoom]   (default 14)
set -u
cd "$(dirname "$0")/.." || exit 1
BASE="maps/osm-zurich"
# OSM policy requires a UA identifying the app WITH contact info;
# generic app UAs receive soft-blocked placeholder tiles (HTTP 200).
UA="GhostHandlerDesktop/2.0 (https://github.com/ghost-handler/gcs-desktop; dev@ghost-handler.local)"
MAXZ="${1:-14}"
ok=0; fail=0; skip=0

fetch() { # z x y
  local z=$1 x=$2 y=$3 f="$BASE/$1/$2/$3.png" code
  if [ -s "$f" ]; then skip=$((skip+1)); return 0; fi
  mkdir -p "$BASE/$z/$x"
  for attempt in 1 2 3 4; do
    code=$(timeout 25 curl -sf -o "$f" -w "%{http_code}" --max-time 20 -A "$UA" \
      "https://tile.openstreetmap.org/$z/$x/$y.png" 2>/dev/null)
    if [ "${code:-000}" = "200" ] && [ -s "$f" ]; then ok=$((ok+1)); return 0; fi
    rm -f "$f"; sleep 3
  done
  fail=$((fail+1)); return 1
}

# Grids centered on the home tile: wide at low zoom, tighter at high zoom
# (a 3x3 block leaves the viewport mostly empty at flight zooms).
for z in 10 11 12 13 14; do
  [ "$z" -gt "$MAXZ" ] && break
  case $z in 10) x0=536;  y0=358;  n=1;;  11) x0=1072; y0=717;  n=2;;
             12) x0=2145; y0=1434; n=3;; 13) x0=4290; y0=2868; n=3;;
             14) x0=8580; y0=5736; n=3;; esac
  for dx in $(seq $((-n)) "$n"); do for dy in $(seq $((-n)) "$n"); do
    fetch $z $((x0+dx)) $((y0+dy)); sleep 0.3
  done; done
done
echo "TILES: ok=$ok skip=$skip fail=$fail"
[ "$fail" -eq 0 ]
