"""仪表盘状态灯与数值卡片。"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QProgressBar, QVBoxLayout

from ..theme import ui_color


class LedIndicator(QLabel):
    def __init__(self, color_on=None, color_off=None):
        super().__init__()
        self._theme_on = color_on is None
        self._theme_off = color_off is None
        self.color_on = color_on or ui_color("success")
        self.color_off = color_off or ui_color("log_dim")
        self._on = False
        self.setFixedSize(16, 16)
        self.setAccessibleName("状态指示灯")

    def set_on(self, on):
        on = bool(on)
        if self._on != on:
            self._on = on
            self.update()

    def apply_theme(self, theme_name=None):
        if self._theme_on:
            self.color_on = ui_color("success", theme_name)
        if self._theme_off:
            self.color_off = ui_color("log_dim", theme_name)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        color = QColor(self.color_on if self._on else self.color_off)
        halo = QColor(color)
        halo.setAlpha(42)
        painter.setPen(Qt.NoPen)
        painter.setBrush(halo)
        painter.drawEllipse(self.rect().adjusted(1, 1, -1, -1))
        painter.setBrush(color)
        painter.drawEllipse(self.rect().adjusted(4, 4, -4, -4))


class GaugeWidget(QFrame):
    def __init__(self, title, unit="", min_val=0, max_val=100, color=None,
                 variable="", scale=1.0, offset=0.0, precision=2):
        super().__init__()
        self.setObjectName("card")
        self._theme_color = color is None
        self._min, self._max = min_val, max_val
        self._color = color or ui_color("primary")
        self._variable = variable
        self._scale = float(scale)
        self._offset = float(offset)
        self._precision = int(precision)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(7)
        title_label = QLabel(title)
        title_label.setObjectName("metric_caption")
        layout.addWidget(title_label)

        value_row = QHBoxLayout()
        value_row.setSpacing(7)
        self._val = QLabel("---")
        self._val.setObjectName("metric_value")
        self._val.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._val.setMinimumWidth(112)
        unit_label = QLabel(unit)
        unit_label.setObjectName("unit")
        unit_label.setAlignment(Qt.AlignLeft | Qt.AlignBottom)
        value_row.addWidget(self._val, 1)
        value_row.addWidget(unit_label, 0, Qt.AlignBottom)
        layout.addLayout(value_row)

        self._bar = QProgressBar()
        self._bar.setRange(0, 1000)
        self._bar.setFixedHeight(5)
        self._bar.setTextVisible(False)
        self._bar.setProperty("compact", True)
        layout.addWidget(self._bar)
        self._refresh_color()

    def _refresh_color(self):
        self._val.setStyleSheet(f"color: {self._color};")
        self._bar.setStyleSheet(
            f"QProgressBar::chunk {{ background-color: {self._color}; border-radius: 2px; }}"
        )

    def apply_theme(self, theme_name=None):
        if self._theme_color:
            self._color = ui_color("primary", theme_name)
            self._refresh_color()

    def update_values(self, values):
        if not self._variable:
            return
        value = values.get(self._variable)
        if value is not None:
            self.set_value(value * self._scale + self._offset)

    def set_value(self, value):
        if self._max > self._min:
            percent = int(1000 * (value - self._min) / (self._max - self._min))
            self._bar.setValue(max(0, min(1000, percent)))
        text = f"{value:.{self._precision}f}"
        if self._val.text() != text:
            self._val.setText(text)
