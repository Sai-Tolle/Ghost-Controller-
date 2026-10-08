"""Offline map tile sources: XYZ directory, MBTiles (SQLite), PMTiles v3.

All readers implement:
    tile(z, x, y) -> bytes | None     # PNG/JPEG tile data, slippy-map XYZ
    name -> str

PMTiles reading implements the v3 specification (protomaps/PMTiles spec/v3):
    * 127-byte little-endian header
    * delta+varint encoded directories, gzip-compressed (internal compression)
    * Hilbert-curve cumulative tile IDs:  id(z,x,y) = (4^z - 1)/3 + d(z,x,y)
    * run-length entries; run length 0 = leaf-directory pointer
    * leaf directories resolved recursively (single level per spec)

MBTiles reading uses the SQLite image blobs (tiles table with
zoom_level/tile_column/tile_row, TMS y-axis flipped to XYZ).
"""
from __future__ import annotations

import gzip
import json
import os
import sqlite3
import struct
from pathlib import Path
from urllib.parse import urlparse


# --------------------------------------------------------------------------
# slippy-map math
# --------------------------------------------------------------------------

def lng_to_tile_x(lng: float, z: int) -> int:
    return int((lng + 180.0) / 360.0 * (1 << z))


def lat_to_tile_y(lat: float, z: int) -> int:
    import math

    lat_rad = math.radians(max(-85.05112878, min(85.05112878, lat)))
    return int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * (1 << z))


def tile_x_to_lng(x: float, z: int) -> float:
    return x / (1 << z) * 360.0 - 180.0


def tile_y_to_lat(y: float, z: int) -> float:
    import math

    n = math.pi - 2.0 * math.pi * y / (1 << z)
    return math.degrees(math.atan(0.5 * (math.exp(n) - math.exp(-n))))


# --------------------------------------------------------------------------
# PMTiles v3
# --------------------------------------------------------------------------

_MAGIC = b"PMTiles"
_COMPRESSION_NONE = 0x01
_COMPRESSION_GZIP = 0x02


def _varint(buf: bytes, pos: int) -> tuple[int, int]:
    """Read a LEB128 little-endian variable-width int. Returns (value, new_pos)."""
    result = 0
    shift = 0
    while True:
        b = buf[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            return result, pos
        shift += 7


def _decode_directory(buf: bytes, compression: int) -> list[dict]:
    if compression == _COMPRESSION_GZIP:
        buf = gzip.decompress(buf)
    elif compression not in (_COMPRESSION_NONE,):
        raise ValueError(f"Unsupported PMTiles directory compression: {compression}")

    n, pos = _varint(buf, 0)
    ids: list[int] = []
    for _ in range(n):
        v, pos = _varint(buf, pos)
        ids.append(v if not ids else ids[-1] + v)  # delta-decoded
    run_lengths = []
    for _ in range(n):
        v, pos = _varint(buf, pos)
        run_lengths.append(v)
    lengths = []
    for _ in range(n):
        v, pos = _varint(buf, pos)
        lengths.append(v)
    offsets = []
    last_sum = 0
    for i in range(n):
        v, pos = _varint(buf, pos)
        offsets.append(v - 1 if v != 0 else last_sum)
        last_sum = offsets[-1] + lengths[i]
    return [
        {"tile_id": ids[i], "offset": offsets[i], "length": lengths[i], "run_length": run_lengths[i]}
        for i in range(n)
    ]


def _hilbert_d(z: int, x: int, y: int) -> int:
    """Hilbert curve distance matching the PMTiles v3 orientation.

    Spec ground truth (v3 spec §4.1 table): z=1 orders (0,0)→1, (0,1)→2,
    (1,1)→3, (1,0)→4, i.e. the classic Wikipedia xy2d algorithm unmodified
    (verified against the spec's z=12 vector: (12,3423,1763) → 19078479).
    """
    side = 1 << z
    d = 0
    s = side // 2
    while s > 0:
        rx = 1 if (x & s) else 0
        ry = 1 if (y & s) else 0
        d += s * s * ((3 * rx) ^ ry)
        if ry == 0:
            if rx == 1:
                x = side - 1 - x
                y = side - 1 - y
            x, y = y, x
        s >>= 1
    return d


def _tile_id(z: int, x: int, y: int) -> int:
    return ((1 << (2 * z)) - 1) // 3 + _hilbert_d(z, x, y)


class PmtilesSource:
    """Reads PMTiles v3 archives (raster tiles: PNG/JPEG/WebP)."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._io_lock = __import__("threading").RLock()   # shared handle: seek+read must be atomic
        self._fh = open(path, "rb")
        header = self._fh.read(127)
        if header[:7] != _MAGIC or header[7] != 3:
            raise ValueError(f"{path} is not a PMTiles v3 archive")
        u64 = lambda off: struct.unpack_from("<Q", header, off)[0]  # noqa: E731
        self._root_off, self._root_len = u64(8), u64(16)
        self._meta_off, self._meta_len = u64(24), u64(32)
        self._leaf_off, self._leaf_len = u64(40), u64(48)
        self._tile_off = u64(56)
        # Byte layout after the nine 8-byte fields (offset 96): C, IC, TC, TT,
        # MinZ, MaxZ, MinPos(8), MaxPos(8), CenZ, CenPos(8) = 127 bytes total.
        self._internal_compression = header[97]
        self._tile_compression = header[98]
        self.min_zoom, self.max_zoom = header[100], header[101]
        self.name = f"pmtiles:{path.name}"
        self._root: list[dict] = self._read_dir(self._root_off, self._root_len)

    def _read_dir(self, offset: int, length: int) -> list[dict]:
        self._fh.seek(offset)
        return _decode_directory(self._fh.read(length), self._internal_compression)

    def metadata(self) -> dict:
        self._fh.seek(self._meta_off)
        raw = self._fh.read(self._meta_len)
        if self._internal_compression == _COMPRESSION_GZIP:
            raw = gzip.decompress(raw)
        try:
            return json.loads(raw)
        except Exception:
            return {}

    def _find(self, tid: int, entries: list[dict]) -> dict | None:
        """Last entry with tile_id <= tid.

        run_length 0 = leaf-directory pointer covering every id from its
        tile_id up to the next entry, so it matches any tid >= tile_id.
        """
        lo, hi = 0, len(entries) - 1
        candidate = None
        while lo <= hi:
            mid = (lo + hi) // 2
            e = entries[mid]
            if tid < e["tile_id"]:
                hi = mid - 1
            else:
                candidate = e
                lo = mid + 1
        if candidate is None:
            return None
        if candidate["run_length"] == 0:  # leaf pointer: open-ended coverage
            return candidate
        if tid < candidate["tile_id"] + candidate["run_length"]:
            return candidate
        return None

    def tile(self, z: int, x: int, y: int) -> bytes | None:
        with self._io_lock:
            return self._tile_locked(z, x, y)

    def _tile_locked(self, z: int, x: int, y: int) -> bytes | None:
        tid = _tile_id(z, x, y)
        entry = self._find(tid, self._root)
        if entry is None:
            return None
        if entry["run_length"] == 0:  # leaf directory pointer
            leaf = self._read_dir(self._leaf_off + entry["offset"], entry["length"])
            entry = self._find(tid, leaf)
            if entry is None:
                return None
        if entry["run_length"] == 0:
            return None
        self._fh.seek(self._tile_off + entry["offset"])
        return self._fh.read(entry["length"])

    def close(self) -> None:
        self._fh.close()


# --------------------------------------------------------------------------
# MBTiles (SQLite)
# --------------------------------------------------------------------------

class MbtilesSource:
    def __init__(self, path: Path) -> None:
        if not path.exists():
            raise FileNotFoundError(path)
        self._lock = __import__("threading").Lock()
        # Tiles are fetched from Qt image-provider worker threads. A default
        # sqlite3 connection is bound to its creating thread, so every tile
        # raised ProgrammingError (swallowed as sqlite3.Error) and offline
        # MBTiles maps never rendered a single tile.
        self._db = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
        self._db.execute("SELECT 1")
        self.name = f"mbtiles:{path.name}"
        # Real zoom coverage so the map can clamp (a blank map above the top
        # stored zoom looks like a broken basemap otherwise).
        try:
            zs = [int(r[0]) for r in self._db.execute(
                "SELECT DISTINCT zoom_level FROM tiles").fetchall()]
        except sqlite3.Error:
            zs = []
        self.min_zoom = min(zs) if zs else 0
        self.max_zoom = max(zs) if zs else 22

    def tile(self, z: int, x: int, y: int) -> bytes | None:
        tms_y = (1 << z) - 1 - y
        with self._lock:
            row = self._db.execute(
                "SELECT tile_data FROM tiles WHERE zoom_level=? AND tile_column=? AND tile_row=?",
                (z, x, tms_y),
            ).fetchone()
        return row[0] if row else None

    def close(self) -> None:
        try:
            self._db.close()
        except sqlite3.Error:
            pass


# --------------------------------------------------------------------------
# XYZ directory tree  (…/z/x/y.png)
# --------------------------------------------------------------------------

class XyzDirSource:
    _EXTS = (".png", ".jpg", ".jpeg", ".webp")

    def __init__(self, root: Path) -> None:
        self._root = root
        if not root.is_dir():
            raise FileNotFoundError(root)
        self.name = f"xyz:{root.name}"
        # Scan the zoom dirs present on disk so the map view can clamp its
        # zoom to real coverage (empty dir → permissive 0..22).
        zs = [int(d.name) for d in root.iterdir() if d.is_dir() and d.name.isdigit()]
        self.min_zoom = min(zs) if zs else 0
        self.max_zoom = max(zs) if zs else 22

    def tile(self, z: int, x: int, y: int) -> bytes | None:
        for ext in self._EXTS:
            p = self._root / str(z) / str(x) / f"{y}{ext}"
            if p.exists():
                return p.read_bytes()
        return None


# --------------------------------------------------------------------------
# resolver
# --------------------------------------------------------------------------

def open_tile_source(path_str: str):
    """Open a tile source from a path (or https:// URL handled by caller).
    Returns (source, error). Raises nothing."""
    try:
        path = Path(path_str).expanduser()
        suffix = path.suffix.lower()
        if suffix == ".pmtiles":
            return PmtilesSource(path), None
        if suffix in (".mbtiles", ".sqlite"):
            return MbtilesSource(path), None
        if path.is_dir():
            return XyzDirSource(path), None
        return None, f"unsupported tile source: {path_str}"
    except Exception as exc:  # noqa: BLE001 — resolver must never crash the app
        return None, str(exc)


def autodetect_map_source() -> str:
    """GH_MAP_SOURCE env → ./maps (dir OR .pmtiles/.mbtiles file) → empty
    (graceful 'no tiles' mode).

    If the maps dir is a container (single subdirectory holding the actual
    {z}/{x}/{y} layout, e.g. maps/osm-zurich/10/...), descend into it."""
    env = os.environ.get("GH_MAP_SOURCE", "")
    if env:
        return env

    def has_zoom_layout(p: Path) -> bool:
        try:
            return p.is_dir() and any(x.name.isdigit() for x in p.iterdir())
        except OSError:  # unreadable dir must never crash the boot
            return False

    here = Path(__file__).resolve().parents[2]  # .../GCS-Desktop
    maps = here / "maps"
    if not maps.is_dir():
        return ""
    # Archives dropped into maps/ are first-class sources too.
    for archive in sorted(maps.glob("*.pmtiles")) + sorted(maps.glob("*.mbtiles")):
        return str(archive)
    try:
        entries = list(maps.iterdir())
    except OSError:
        return ""
    if entries:
        if not has_zoom_layout(maps):
            subs = [d for d in entries if d.is_dir()]
            if len(subs) == 1 and has_zoom_layout(subs[0]):
                return str(subs[0])
        return str(maps)
    return ""
