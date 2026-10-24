"""PowerScope 垂直主导航。"""

import math

from PySide6.QtCore import (
    QEasingCurve,
    Property,
    QPropertyAnimation,
    QRectF,
    Qt,
)
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QTabBar

from ..theme import get_theme
from .icons import paint_icon


class SideTabBar(QTabBar):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("primary_nav")
        self._icons = {}
        self._indicator_position = 0.0
        self._animation = QPropertyAnimation(self, b"indicatorPosition", self)
        self._animation.setDuration(150)
        self._animation.setEasingCurve(QEasingCurve.OutCubic)
        self.setExpanding(False)
        self.setDrawBase(False)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.currentChanged.connect(self._animate_to)

    def _get_indicator_position(self):
        return self._indicator_position

    def _set_indicator_position(self, value):
        self._indicator_position = float(value)
        self.update()

    indicatorPosition = Property(float, _get_indicator_position, _set_indicator_position)

    def set_icon(self, index: int, name: str):
        if self._icons.get(index) != name:
            self._icons[index] = name
            self.update()

    def set_glyph(self, index: int, glyph: str):
        legacy = {"⌁": "msg", "⇧": "upgrade"}
        self.set_icon(index, legacy.get(glyph, "dashboard"))

    def tabSizeHint(self, index):
        size = super().tabSizeHint(index)
        size.transpose()
        size.setWidth(148)
        size.setHeight(48)
        return size

    def tabInserted(self, index):
        super().tabInserted(index)
        self._update_tooltip(index)

    def tabTextChanged(self, index):
        super().tabTextChanged(index)
        self._update_tooltip(index)

    def _update_tooltip(self, index):
        if 0 <= index < self.count():
            suffix = f"  Ctrl+{index + 1}" if index < 9 else ""
            self.setTabToolTip(index, self.tabText(index) + suffix)

    def _animate_to(self, index):
        self._animation.stop()
        if index < 0:
            return
        if abs(self._indicator_position - index) < 0.001:
            self._indicator_position = float(index)
            self.update()
            return
        self._animation.setStartValue(self._indicator_position)
        self._animation.setEndValue(float(index))
        self._animation.start()

    def _indicator_rect(self):
        if not self.count():
            return QRectF()
        position = max(0.0, min(self._indicator_position, self.count() - 1))
        lower = int(math.floor(position))
        upper = min(lower + 1, self.count() - 1)
        fraction = position - lower
        first = QRectF(self.tabRect(lower))
        second = QRectF(self.tabRect(upper))
        rect = QRectF(
            first.x() + (second.x() - first.x()) * fraction,
            first.y() + (second.y() - first.y()) * fraction,
            first.width() + (second.width() - first.width()) * fraction,
            first.height() + (second.height() - first.height()) * fraction,
        )
        return rect.adjusted(7, 4, -7, -4)

    def paintEvent(self, event):
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)
        theme = get_theme()
        painter.fillRect(self.rect(), QColor(theme["bg_alt"]))

        selected_rect = self._indicator_rect()
        if self.currentIndex() >= 0 and not selected_rect.isEmpty():
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(theme["accent_bg"]))
            painter.drawRoundedRect(selected_rect, 8, 8)
            marker = QRectF(selected_rect.left(), selected_rect.center().y() - 10, 3, 20)
            painter.setBrush(QColor(theme["primary"]))
            painter.drawRoundedRect(marker, 1.5, 1.5)

        for index in range(self.count()):
            rect = QRectF(self.tabRect(index))
            enabled = self.isTabEnabled(index)
            selected = index == self.currentIndex()
            hovered = self.underMouse() and rect.contains(self.mapFromGlobal(self.cursor().pos()))
            if hovered and not selected and enabled:
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(theme["surface_hover"]))
                painter.drawRoundedRect(rect.adjusted(7, 4, -7, -4), 8, 8)
            if not enabled:
                color = theme["text_faint"]
            elif selected:
                color = theme["primary"]
            elif hovered:
                color = theme["text"]
            else:
                color = theme["text_dim"]

            icon_rect = QRectF(rect.left() + 16, rect.center().y() - 10, 20, 20)
            paint_icon(painter, self._icons.get(index, "dashboard"), icon_rect, color)
            text_rect = rect.adjusted(48, 0, -12, 0)
            font = QFont(self.font())
            font.setWeight(QFont.DemiBold if selected else QFont.Normal)
            painter.setFont(font)
            painter.setPen(QColor(color))
            text = self.fontMetrics().elidedText(
                self.tabText(index), Qt.ElideRight, max(0, int(text_rect.width())))
            painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, text)
            if selected and self.hasFocus():
                pen = QPen(QColor(theme["border_strong"]))
                pen.setWidthF(1.0)
                painter.setPen(pen)
                painter.setBrush(Qt.NoBrush)
                painter.drawRoundedRect(selected_rect.adjusted(1, 1, -1, -1), 7, 7)
