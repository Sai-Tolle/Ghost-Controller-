"""Appearance preference: dark / light / system.

Drives the generated design-token object (`Token.theme`), so every QML binding
on a Token colour restyles live. The preference persists in QSettings; with
"system" the OS colour scheme (Qt 6.5+ style hints) is followed live.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Property, Qt, Signal, Slot
from PySide6.QtGui import QGuiApplication

from app.bridge.settings import app_settings

KEY = "ui/appearance"
CHOICES = ("dark", "light", "system")


class ThemeController(QObject):
    changed = Signal()

    def __init__(self, token_obj: QObject, app: QGuiApplication) -> None:
        super().__init__()
        self._token = token_obj
        self._app = app
        pref = str(app_settings().value(KEY, "dark"))
        self._pref = pref if pref in CHOICES else "dark"
        hints = app.styleHints()
        if hasattr(hints, "colorSchemeChanged"):
            hints.colorSchemeChanged.connect(lambda *_: self._apply())
        self._apply()

    def _system_theme(self) -> str:
        hints = self._app.styleHints()
        scheme = getattr(hints, "colorScheme", lambda: None)()
        return "light" if scheme == Qt.ColorScheme.Light else "dark"

    def _apply(self) -> None:
        theme = self._system_theme() if self._pref == "system" else self._pref
        if self._token is not None and self._token.property("theme") != theme:
            self._token.setProperty("theme", theme)
        self.changed.emit()

    @Property(str, notify=changed)
    def preference(self) -> str:
        return self._pref

    @Property(str, notify=changed)
    def active(self) -> str:
        return self._token.property("theme") if self._token is not None else "dark"

    @Slot(str)
    def setPreference(self, pref: str) -> None:  # noqa: N802
        if pref not in CHOICES or pref == self._pref:
            return
        self._pref = pref
        app_settings().setValue(KEY, pref)
        self._apply()
