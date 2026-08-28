"""仪表盘基础组件 — LED 指示灯 + 仪表盘数值显示"""
from PySide6.QtWidgets import QLabel, QFrame, QVBoxLayout, QProgressBar
from PySide6.QtCore import Qt

from ..theme import ui_color


class LedIndicator(QLabel):
    """LED 状态指示灯"""

    def __init__(self, color_on=None, color_off=None):
        super().__init__()
        # 默认色走主题语义令牌，随主题切换风格一致
        self.color_on = color_on or ui_color("success")
        self.color_off = color_off or ui_color("log_dim")
        self._on = False
        self.setFixedSize(16, 16)
        self._update_style()

    def set_on(self, on):
        self._on = on
        self._update_style()

    def _update_style(self):
        c = self.color_on if self._on else self.color_off
        self.setStyleSheet(
            f"background-color:{c};border-radius:8px;border:1px solid rgba(255,255,255,0.2);"
        )


class GaugeWidget(QFrame):
    """仪表盘数值显示组件 — 标题 + 大号数值 + 单位 + 进度条"""

    def __init__(self, title, unit="", min_val=0, max_val=100, color=None):
        super().__init__()
        self.setObjectName("card")
        color = color or ui_color("primary")
        self._min, self._max, self._color = min_val, max_val, color
        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignCenter)
        tl = QLabel(title)
        tl.setAlignment(Qt.AlignCenter)
        tl.setObjectName("dim")
        self._val = QLabel("---")
        self._val.setObjectName("value")
        self._val.setAlignment(Qt.AlignCenter)
        self._val.setStyleSheet(f"color:{color};font-size:28px;font-weight:bold;")
        ul = QLabel(unit)
        ul.setObjectName("unit")
        ul.setAlignment(Qt.AlignCenter)
        self._bar = QProgressBar()
        self._bar.setRange(0, 1000)
        self._bar.setFixedHeight(6)
        self._bar.setTextVisible(False)
        self._bar.setStyleSheet(
            f"QProgressBar::chunk{{background-color:{color};}}"
        )
        lay.addWidget(tl)
        lay.addWidget(self._val)
        lay.addWidget(ul)
        lay.addWidget(self._bar)

    def set_value(self, v):
        if self._max > self._min:
            pct = int(1000 * (v - self._min) / (self._max - self._min))
            self._bar.setValue(max(0, min(1000, pct)))
        self._val.setText(f"{v:.2f}")
