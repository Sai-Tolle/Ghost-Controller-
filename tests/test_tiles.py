#!/usr/bin/env python3
"""Tile source tests. Runnable directly (no pytest needed):

    .venv-desktop/bin/python tests/test_tiles.py
"""
import json
import sqlite3
import struct
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.map.tiles import (
    MbtilesSource, PmtilesSource, XyzDirSource,
    _tile_id, _varint, lng_to_tile_x, lat_to_tile_y,
)

FAILURES = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(("PASS " if cond else "FAIL ") + name + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


# ---------------------------------------------------------------------------
# PMTiles spec vectors (v3 spec §4.1 table) — these pin Hilbert conformance
# ---------------------------------------------------------------------------

def test_hilbert_spec_table() -> None:
    vectors = {
        (0, 0, 0): 0,
        (1, 0, 0): 1,
        (1, 0, 1): 2,
        (1, 1, 1): 3,
        (1, 1, 0): 4,
        (2, 0, 0): 5,
    }
    for (z, x, y), expected in vectors.items():
        got = _tile_id(z, x, y)
        check(f"tile_id z{z} x{x} y{y} == {expected}", got == expected, f"got {got}")


def test_varint_roundtrip() -> None:
    ok = True
    for v in [0, 1, 127, 128, 300, 16384, 2**31, 2**53 - 1]:
        buf = bytearray()
        val = v
        while True:
            b = val & 0x7F
            val >>= 7
            buf.append(b | (0x80 if val else 0))
            if not val:
                break
        got, pos = _varint(bytes(buf), 0)
        if got != v or pos != len(buf):
            ok = False
            print(f"  varint mismatch {v} -> {got}")
    check("varint roundtrip", ok)


def test_xyz_source() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "tiles"
        tile_path = root / "15" / "17060" / "10790.png"
        tile_path.parent.mkdir(parents=True)
        tile_path.write_bytes(b"\x89PNG-fake")
        src = XyzDirSource(root)
        check("xyz finds tile", src.tile(15, 17060, 10790) == b"\x89PNG-fake")
        check("xyz missing tile -> None", src.tile(15, 1, 1) is None)


def test_mbtiles_source() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "map.mbtiles"
        db = sqlite3.connect(p)
        db.execute("CREATE TABLE tiles (zoom_level int, tile_column int, tile_row int, tile_data blob)")
        tms_y = (1 << 7) - 1 - 40   # XYZ y=40 at z=7 -> TMS 87
        db.execute("INSERT INTO tiles VALUES (7, 60, ?, ?)", (tms_y, b"MBTILE-DATA"))
        db.commit()
        db.close()
        src = MbtilesSource(p)
        check("mbtiles y-flip read", src.tile(7, 60, 40) == b"MBTILE-DATA")
        check("mbtiles missing -> None", src.tile(7, 60, 41) is None)


def _build_pmtiles(tmp: Path, with_leaf: bool) -> Path:
    """Construct a minimal but spec-conformant v3 archive with one tile at
    z=1 x=1 y=1 (tile_id 3), exercising the leaf-directory path too."""
    payload = b"PMTILE-TILE-PAYLOAD-0123456789"
    tid = 3

    def entry(eid, offset, length, run):
        return (eid, offset, length, run)

    def encode_dir(entries):
        def vi(v):
            out = bytearray()
            while True:
                b = v & 0x7F
                v >>= 7
                out.append(b | (0x80 if v else 0))
                if not v:
                    return bytes(out)
        buf = bytearray()
        buf += vi(len(entries))
        last = 0
        for eid, _, _, _ in entries:
            buf += vi(eid - last)
            last = eid
        for _, _, _, run in entries:
            buf += vi(run)
        for _, _, length, _ in entries:
            buf += vi(length)
        prev_sum = 0
        for _, offset, length, _ in entries:
            buf += vi(0 if offset == prev_sum else offset + 1)
            prev_sum = offset + length
        return bytes(buf)

    if with_leaf:
        # Spec: entry Length MUST be > 0 — leaf pointers carry the leaf's size.
        leaf_dir = encode_dir([entry(tid, 0, len(payload), 1)])
        root_entry = entry(0, 0, len(leaf_dir), 0)   # leaf pointer from id 0
        tile_data = payload
        root_dir = encode_dir([root_entry])
        leaf_off = 127 + len(root_dir)
        tile_off = leaf_off + len(leaf_dir)
        leaf_len = len(leaf_dir)
    else:
        root_dir = encode_dir([entry(tid, 0, len(payload), 1)])
        tile_data = payload
        leaf_off, leaf_len = 0, 0
        tile_off = 127 + len(root_dir)

    header = bytearray(127)
    header[0:7] = b"PMTiles"
    header[7] = 3
    struct.pack_into("<Q", header, 8, 127)            # root dir offset
    struct.pack_into("<Q", header, 16, len(root_dir))
    struct.pack_into("<Q", header, 24, 127 + len(root_dir))   # metadata offset
    struct.pack_into("<Q", header, 32, 0)             # metadata length
    struct.pack_into("<Q", header, 40, leaf_off)      # leaf dirs offset
    struct.pack_into("<Q", header, 48, leaf_len)
    struct.pack_into("<Q", header, 56, tile_off)      # tile data offset
    struct.pack_into("<Q", header, 64, len(tile_data))
    header[97] = 0x01   # internal compression: none
    header[98] = 0x01   # tile compression: none
    header[99] = 0x02   # tile type: png
    header[100] = 0     # min zoom
    header[101] = 3     # max zoom

    out = tmp / ("leaf.pmtiles" if with_leaf else "flat.pmtiles")
    body = bytes(header) + root_dir + (leaf_dir if with_leaf else b"") + tile_data
    out.write_bytes(body)
    return out


def test_pmtiles_flat_and_leaf() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        for with_leaf in (False, True):
            p = _build_pmtiles(Path(tmp), with_leaf)
            src = PmtilesSource(p)
            kind = "leaf" if with_leaf else "flat"
            check(f"pmtiles[{kind}] magic/zoom", (src.min_zoom, src.max_zoom) == (0, 3))
            check(f"pmtiles[{kind}] finds tile", src.tile(1, 1, 1) == b"PMTILE-TILE-PAYLOAD-0123456789")
            check(f"pmtiles[{kind}] missing -> None", src.tile(1, 0, 0) is None)
            src.close()


def test_slippy_math_roundtrip() -> None:
    """Correct invariant at any zoom: the tile's center point maps back into
    the same integer tile (fixed-precision Mercator roundtrip)."""
    from app.map.tiles import tile_x_to_lng, tile_y_to_lat  # type: ignore

    ok = True
    for z in (2, 5, 14):
        for lng, lat in ((8.545594, 47.397742), (-122.4, 37.8), (0, 0)):
            tx, ty = lng_to_tile_x(lng, z), lat_to_tile_y(lat, z)
            back_tx = lng_to_tile_x(tile_x_to_lng(tx + 0.5, z), z)
            back_ty = lat_to_tile_y(tile_y_to_lat(ty + 0.5, z), z)
            if (back_tx, back_ty) != (tx, ty):
                ok = False
                print(f"  roundtrip mismatch z={z} ({lng},{lat}): {(tx, ty)} -> {(back_tx, back_ty)}")
    check("slippy math roundtrip", ok)


def test_pmtiles_spec_z12_vector() -> None:
    """The v3 spec's own worked example: z=12, x=3423, y=1763 → id 19078479."""
    got = _tile_id(12, 3423, 1763)
    check("pmtiles spec z12 vector (12,3423,1763)==19078479", got == 19078479, f"got {got}")


if __name__ == "__main__":
    test_hilbert_spec_table()
    test_varint_roundtrip()
    test_xyz_source()
    test_mbtiles_source()
    test_pmtiles_flat_and_leaf()
    test_slippy_math_roundtrip()
    test_pmtiles_spec_z12_vector()
    print(f"\n{'ALL TILE TESTS PASSED' if not FAILURES else f'{len(FAILURES)} FAILURES'}")
    sys.exit(1 if FAILURES else 0)
