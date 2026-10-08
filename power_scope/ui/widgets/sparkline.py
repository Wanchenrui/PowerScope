"""sparkline.py — 迷你趋势线 + 变化箭头（P0-2）

仪表盘指标卡的「一眼趋势」组件：
  - 左：最近 N 个样本的迷你折线（无坐标轴，paintEvent 自绘）
  - 右：相对上一次公开值的方向箭头 ↑/↓（语义色）

数据走 core/trend_buffer.TrendBuffer，绘制不持缓冲区快照 —— 每帧直接
读 buffer.points()，量级 ≤64 点，开销可忽略。
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from ...core.trend_buffer import Delta, TrendBuffer, analyze_delta
from ..theme import ui_color

#: 箭头字形（字体缺字风险低：都是基本拉丁符号）
_ARROW = {"up": "↑", "down": "↓", "flat": "→"}


class Sparkline(QWidget):
    """纯绘制迷你趋势线。数据来自外部 TrendBuffer。"""

    def __init__(self, buffer: TrendBuffer, width: int = 72, height: int = 22,
                 color: str | None = None, parent=None):
        super().__init__(parent)
        self._buffer = buffer
        self._color_raw = color
        self.setFixedSize(width, height)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def apply_theme(self, theme_name=None):
        self.update()

    def _color(self) -> str:
        if self._color_raw:
            from ..theme import resolve_color
            return resolve_color(self._color_raw, "primary")
        return ui_color("primary")

    def paintEvent(self, event):
        points = self._buffer.points()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        if len(points) < 2:
            painter.end()
            return
        values = [v for _t, v in points]
        lo, hi = min(values), max(values)
        span = hi - lo
        w, h = self.width(), self.height()
        if span <= 1e-12:
            # 常量：画一条居中的平线
            mid = h / 2
            painter.setPen(QPen(QColor(self._color()), 1.2))
            painter.drawLine(2, int(mid), w - 2, int(mid))
            painter.end()
            return
        path_points: list[QPointF] = []
        for i, v in enumerate(values):
            x = 2 + (w - 4) * i / (len(values) - 1)
            y = h - 2 - (h - 4) * (v - lo) / span
            path_points.append(QPointF(x, y))
        painter.setPen(QPen(QColor(self._color()), 1.2))
        for i in range(1, len(path_points)):
            painter.drawLine(path_points[i - 1], path_points[i])
        # 末端点强调
        painter.setBrush(QColor(self._color()))
        painter.drawEllipse(path_points[-1], 1.6, 1.6)
        painter.end()


class DeltaArrow(QLabel):
    """方向箭头 + 变化率提示。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(30)
        self.setAlignment(Qt.AlignCenter)
        self.set_delta(None)

    def set_delta(self, delta: Delta | None):
        if delta is None:
            self.setText("")
            self.setToolTip("")
            return
        arrow = _ARROW.get(delta.direction, "→")
        color = {"up": ui_color("tx"), "down": ui_color("chart1"),
                 "flat": ui_color("text_dim")}.get(delta.direction,
                                                   ui_color("text_dim"))
        self.setText(arrow)
        self.setStyleSheet(f"color:{color};font-size:14px;font-weight:bold;")
        pct = "" if delta.percent in (float("inf"), float("-inf")) else \
            f" ({delta.percent:+.1f}%)"
        self.setToolTip(f"较上次变化 {delta.absolute:+.4g}{pct}")


class ValueTrend(QWidget):
    """组合件：[数值] [箭头] [sparkline]，供仪表盘卡片一行排布。"""

    def __init__(self, precision: int = 2, capacity: int = 48, parent=None):
        super().__init__(parent)
        self._buffer = TrendBuffer(capacity)
        self._precision = precision
        self._last_public: float | None = None
        self._sim_time = 0.0

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self._arrow = DeltaArrow()
        lay.addWidget(self._arrow)
        self._spark = Sparkline(self._buffer)
        lay.addWidget(self._spark)

    def push(self, value, timestamp: float | None = None) -> Delta | None:
        """喂入新值；返回相对上次公开值的 Delta（首次为 None）。"""
        try:
            v = float(value)
        except (TypeError, ValueError):
            return None
        if timestamp is None:
            self._sim_time += 1.0
            timestamp = self._sim_time
        previous = self._last_public
        self._buffer.append(timestamp, v)
        self._last_public = v
        if previous is None:
            self._arrow.set_delta(None)
            self._spark.update()
            return None
        delta = analyze_delta(previous, v)
        self._arrow.set_delta(delta)
        self._spark.update()
        return delta

    def clear(self):
        self._buffer.clear()
        self._last_public = None
        self._arrow.set_delta(None)
        self._spark.update()

    def apply_theme(self, theme_name=None):
        self._spark.apply_theme(theme_name)
        # 箭头颜色依赖主题令牌，用最近两点重算一次让颜色跟随新主题
        self._arrow.set_delta(self._arrow_last())

    def _arrow_last(self):
        # 用最近两点重算，让颜色跟随主题
        pts = self._buffer.points()
        if len(pts) < 2:
            return None
        return analyze_delta(pts[-2][1], pts[-1][1])
