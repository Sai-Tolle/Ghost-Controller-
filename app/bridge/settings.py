"""QSettings access with test isolation.

Production defaults to org/app ("Ghost Handler", "Ghost Handler"). Tests and
demo tools set GH_QSETTINGS_APP so their writes never pollute the operator's
real configuration (a past run of the video tests persisted mode=test, which
made the app boot into the synthetic test pattern — fake video on startup).
"""
from __future__ import annotations

import os

from PySide6.QtCore import QSettings

ORG = "Ghost Handler"
APP_ENV = "GH_QSETTINGS_APP"


def app_settings() -> QSettings:
    return QSettings(ORG, os.environ.get(APP_ENV, ORG))
