"""Static app metadata exposed to QML."""
from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import QObject, Property

_ROOT = Path(__file__).resolve().parents[2]


def _read_version() -> str:
    try:
        text = (_ROOT / "pyproject.toml").read_text()
    except OSError:
        return "0.0.0"
    # [project] section's version line (stdlib tomllib is 3.11+; the desktop
    # venv may be 3.10, so parse the one line we need instead).
    match = re.search(r'^\s*version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return match.group(1) if match else "0.0.0"


class AppInfoController(QObject):
    def __init__(self) -> None:
        super().__init__()
        self._version = _read_version()

    @Property(str, constant=True)
    def version(self) -> str:  # noqa: N802
        return self._version
