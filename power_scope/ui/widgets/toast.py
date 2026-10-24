"""非阻塞浮层通知，支持堆叠、主题与淡入淡出。"""

import html
import weakref

from PySide6.QtCore import QEvent, QPropertyAnimation, Qt, QTimer
from PySide6.QtWidgets import QGraphicsOpacityEffect, QLabel

from ..theme import ui_color


_ICON = {"success": "✓", "warning": "⚠", "error": "✕", "info": "●"}
_active = weakref.WeakKeyDictionary()


def _level_colors(level: str) -> tuple[str, str]:
    foreground = {
        "success": ui_color("success"),
        "warning": ui_color("warning"),
        "error": ui_color("danger"),
        "info": ui_color("primary"),
    }.get(level, ui_color("primary"))
    return ui_color("surface"), foreground


def level_from_message(msg: str) -> str:
    message = (msg or "").lstrip()
    if message.startswith("✗"):
        return "error"
    if message.startswith("⚠"):
        return "warning"
    if message.startswith("✓"):
        return "success"
    return "info"


class Toast(QLabel):
    MAX_VISIBLE = 5

    def __init__(self, parent, message, level="info", duration_ms=3200):
        super().__init__("", parent)
        self._level = level
        self._message = str(message).lstrip()
        for marker in ("✗", "⚠", "✓", "ℹ"):
            if self._message.startswith(marker):
                self._message = self._message[len(marker):].lstrip()
                break
        self._closing = False
        self.setWordWrap(True)
        self.setTextFormat(Qt.RichText)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setFocusPolicy(Qt.NoFocus)
        self.setAccessibleName(self._message)
        self.setObjectName("toast")
        self.refresh_theme()

        self._opacity = QGraphicsOpacityEffect(self)
        self._opacity.setOpacity(0.0)
        self.setGraphicsEffect(self._opacity)
        self._fade = QPropertyAnimation(self._opacity, b"opacity", self)
        self._fade.setDuration(160)
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.finished.connect(self._on_fade_finished)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._fade_out)
        self._timer.start(duration_ms)

        entries = _active.setdefault(parent, [])
        entries.append(self)
        while len(entries) > self.MAX_VISIBLE:
            oldest = entries.pop(0)
            oldest.close()
        parent.installEventFilter(self)
        self._restack(parent)

    def refresh_theme(self):
        background, foreground = _level_colors(self._level)
        icon = _ICON.get(self._level, _ICON["info"])
        message = html.escape(self._message).replace("\n", "<br>")
        self.setText(
            f"<span style='color:{foreground};font-weight:600'>{icon}</span>"
            f"&nbsp;&nbsp;<span style='color:{ui_color('text')}'>{message}</span>")
        self.setStyleSheet(
            f"background:{background}; border:1px solid {ui_color('border_strong')};"
            f"border-left:3px solid {foreground}; border-radius:8px;"
            "padding:10px 14px; font-size:13px;")
        self.adjustSize()

    def eventFilter(self, watched, event):
        parent = self.parentWidget()
        if watched is parent:
            if event.type() == QEvent.Resize:
                self._restack(parent)
            elif event.type() in (QEvent.StyleChange, QEvent.PaletteChange):
                self.refresh_theme()
        return super().eventFilter(watched, event)

    def _restack(self, parent):
        if parent is None:
            return
        margin = 18
        y = parent.height() - 44
        width = min(400, max(220, parent.width() - 40))
        for toast in reversed(list(_active.get(parent, []))):
            toast.setFixedWidth(width)
            toast.adjustSize()
            y -= toast.height()
            x = parent.width() - toast.width() - margin
            toast.move(max(8, x), max(8, y))
            y -= 8

    def _fade_out(self):
        if self._closing:
            return
        self._closing = True
        self._timer.stop()
        self._fade.stop()
        self._fade.setDuration(180)
        self._fade.setStartValue(self._opacity.opacity())
        self._fade.setEndValue(0.0)
        self._fade.start()

    def _on_fade_finished(self):
        if self._closing:
            self.close()

    def closeEvent(self, event):
        self._closing = True
        self._timer.stop()
        self._fade.stop()
        parent = self.parentWidget()
        if parent is not None:
            parent.removeEventFilter(self)
            entries = _active.get(parent)
            if entries and self in entries:
                entries.remove(self)
            if not entries:
                _active.pop(parent, None)
            self._restack(parent)
        super().closeEvent(event)
        self.deleteLater()

    @property
    def level(self) -> str:
        return self._level

    @classmethod
    def show_message(cls, parent, message, level="info", duration_ms=3200):
        if level is None:
            level = level_from_message(message)
        toast = cls(parent, message, level, duration_ms)
        toast.show()
        toast.raise_()
        toast._fade.start()
        return toast
