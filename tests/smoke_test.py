#!/usr/bin/env python3
"""Headless boot test for Ghost Handler Desktop.

Runs `main.py --smoke` (offscreen + software QML rendering) and asserts:
  * process exits 0
  * SMOKE_OK was printed (QML loaded, window grabbed, PNG saved)
  * build/smoke.png exists and is non-trivial

Usage:  python tests/smoke_test.py
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "build" / "smoke.png"


def main() -> int:
    if OUT.exists():
        OUT.unlink()

    proc = subprocess.run(
        [sys.executable, str(ROOT / "main.py"), "--smoke"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    print(proc.stdout, end="")
    if proc.returncode != 0 or "SMOKE_OK" not in proc.stdout:
        print(proc.stderr, file=sys.stderr)
        print(f"FAIL: exit={proc.returncode}")
        return 1

    if not OUT.exists() or OUT.stat().st_size < 5000:
        print(f"FAIL: {OUT} missing or too small")
        return 1

    print(f"PASS: boot OK, screenshot {OUT.relative_to(ROOT)} "
          f"({OUT.stat().st_size // 1024} KiB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
