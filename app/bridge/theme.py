"""Appearance preference: dark / light / system, plus the HUD ink colour.

Drives the generated design-token object (`Token.theme`), so every QML binding
on a Token colour restyles live. The preference persists in QSettings; with
"system" the OS colour scheme (Qt 6.5+ style hints) is followed live.

The HUD ink (`Token.hudInk`) colours everything drawn over live video. White
vanishes against snow, cloud or bright sky, so the operator picks a preset or
any custom colour; the outline (`Token.hudInkShadow`) flips between dark and
light automatically so the marks stay readable either way.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Property, Qt, Signal, Slot
from PySide6.QtGui import QColor, QGuiApplication

from app.bridge.settings import app_settings

KEY = "ui/appearance"
CHOICES = ("dark", "light", "system")
HUD_KEY = "ui/hudColor"
DEFAULT_HUD = "#FFFFFF"
# Presets shown as swatches; any other valid colour is accepted as "custom".
HUD_PRESETS = [
    {"name": "White", "color": "#FFFFFF"},
    {"name": "Green", "color": "#32FF6A"},
    {"name": "Yellow", "color": "#FFD60A"},
    {"name": "Cyan", "color": "#5AF0FF"},
    {"name": "Orange", "color": "#FF9F0A"},
    {"name": "Magenta", "color": "#FF4FD8"},
    {"name": "Black", "color": "#000000"},
]


def _shadow_for(color: QColor) -> str:
    """Dark outline under light inks, light outline under dark inks."""
    luma = 0.2126 * color.redF() + 0.7152 * color.greenF() + 0.0722 * color.blueF()
    return "#8C000000" if luma > 0.45 else "#B3FFFFFF"


class ThemeController(QObject):
    changed = Signal()

    def __init__(self, token_obj: QObject, app: QGuiApplication) -> None:
        super().__init__()
        self._token = token_obj
        self._app = app
        pref = str(app_settings().value(KEY, "dark"))
        self._pref = pref if pref in CHOICES else "dark"
        hud = QColor(str(app_settings().value(HUD_KEY, DEFAULT_HUD)))
        self._hud = hud.name().upper() if hud.isValid() else DEFAULT_HUD
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
        if self._token is not None:
            if self._token.property("theme") != theme:
                self._token.setProperty("theme", theme)
            ink = QColor(self._hud)
            self._token.setProperty("hudInk", ink)
            self._token.setProperty("hudInkShadow", QColor(_shadow_for(ink)))
        self.changed.emit()

    @Property(str, notify=changed)
    def preference(self) -> str:
        return self._pref

    @Property(str, notify=changed)
    def active(self) -> str:
        return self._token.property("theme") if self._token is not None else "dark"

    @Property(str, notify=changed)
    def hudColor(self) -> str:  # noqa: N802
        return self._hud

    @Property("QVariantList", constant=True)
    def hudPresets(self) -> list:  # noqa: N802
        return HUD_PRESETS

    @Slot(str)
    def setHudColor(self, color: str) -> None:  # noqa: N802
        c = QColor(color)
        if not c.isValid():
            return
        c.setAlpha(255)                      # translucent ink would vanish on video
        name = c.name().upper()
        if name == self._hud:
            return
        self._hud = name
        app_settings().setValue(HUD_KEY, name)
        self._apply()

    @Slot(str)
    def setPreference(self, pref: str) -> None:  # noqa: N802
        if pref not in CHOICES or pref == self._pref:
            return
        self._pref = pref
        app_settings().setValue(KEY, pref)
        self._apply()
