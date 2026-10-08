"""anim.py — 微动效预算与实现（P0-1）

设计规范（「chrome-only 动效预算」）——动效是状态语言，不是装饰：

  ├─ tab 切换淡入        120ms   页面切换有感但不迟滞
  ├─ 数值变化闪烁        300ms   「值刚变化」的余光信号（仪表盘/监视表）
  ├─ 告警/录制 LED 呼吸  ~1.1s   系统活着的连续信号（不等长闪烁，不抢注意力）
  └─ Toast 淡入淡出      ~160ms  （已有，见 widgets/toast.py）

绝对不动（写入即失真/眩晕）：
  - 数据表格刷新、日志滚动 —— 高频内容任何动效都会抖动
  - 主题切换交叉淡化     —— 全量 setStyleSheet 期间做透明度动画会闪烁，
                          评审记录的「先定规范再启用」，本版不启用

实现注意：
  - 全部用 QPropertyAnimation(windowOpacity) / QTimer 颜色插值，
    不碰 unpolish/polish（动态属性 hack 在切换主题时不可靠）；
  - 所有动画对 widget 的 isVisible/isDeleted 做防御，销毁后自动停定时器。
"""
from __future__ import annotations

from PySide6.QtCore import QPropertyAnimation, QTimer, Qt
from PySide6.QtGui import QColor

# ═══ 动效预算（唯一真源，禁止在视图里写死时长） ═══
MOTION = {
    "tab_fade_ms": 120,        # tab 切换页面淡入
    "value_flash_ms": 300,     # 数值变化高亮闪烁
    "pulse_period_ms": 1100,   # LED 呼吸周期（半周期亮/半周期暗）
    "pulse_steps": 22,         # 呼吸一帧的步进数（≈30fps）
    "theme_fade_ms": 0,        # 0 = 未启用（见模块 docstring）
}


def fade_in(widget, duration_ms: int | None = None) -> QPropertyAnimation | None:
    """让 widget 以 windowOpacity 0→1 淡入（Toast 同款机制，child widget 可用）。"""
    if widget is None:
        return None
    ms = MOTION["tab_fade_ms"] if duration_ms is None else duration_ms
    if ms <= 0:
        return None
    try:
        if not widget.isVisible():
            return None
    except Exception:
        return None
    anim = QPropertyAnimation(widget, b"windowOpacity", widget)
    anim.setDuration(ms)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.start()
    # 动画对象挂在 widget 上防 GC；结束一次后清理
    widget._ps_anim = anim
    anim.finished.connect(lambda: _safe_release(widget))
    return anim


def _safe_release(widget):
    try:
        widget._ps_anim = None
        widget.setWindowOpacity(1.0)
    except Exception:
        pass


def flash_value(widget, color: str, duration_ms: int | None = None) -> None:
    """数值变化高亮：把文字色临时改为 color，duration 后恢复。

    直接保存/恢复 stylesheet，不使用动态属性 + unpolish/polish。
    """
    if widget is None:
        return
    ms = MOTION["value_flash_ms"] if duration_ms is None else duration_ms
    previous = getattr(widget, "_ps_flash_prev", None)
    if previous is None:
        try:
            previous = widget.styleSheet()
        except Exception:
            previous = ""
        widget._ps_flash_prev = previous
        widget._ps_flash_timer = QTimer(widget)
        widget._ps_flash_timer.setSingleShot(True)
        widget._ps_flash_timer.timeout.connect(
            lambda: _restore_style(widget))
    try:
        widget.setStyleSheet(
            f"color:{color};font-weight:bold;{previous or ''}"
            if previous else f"color:{color};font-weight:bold;")
    except Exception:
        return
    widget._ps_flash_timer.start(max(80, ms))


def _restore_style(widget):
    try:
        previous = getattr(widget, "_ps_flash_prev", None)
        if previous is not None:
            widget.setStyleSheet(previous)
    except Exception:
        pass


class PulseLED:
    """让任意带 setStyleSheet 的 LED 控件呼吸（明暗按周期插值）。

    用法::

        pulse = PulseLED(led_widget, on_color)
        pulse.start()     # 「采集运行中」等连续状态
        pulse.stop()
    """

    def __init__(self, widget, color: str, color_dim: str | None = None):
        self._widget = widget
        self._color = QColor(color)
        self._color_dim = QColor(color_dim) if color_dim else _dim(self._color)
        self._timer = QTimer(widget)
        self._timer.setInterval(
            max(16, MOTION["pulse_period_ms"] // MOTION["pulse_steps"]))
        self._step = 0
        self._timer.timeout.connect(self._tick)

    @property
    def active(self) -> bool:
        return self._timer.isActive()

    def start(self):
        if not self.active:
            self._step = 0
            self._timer.start()

    def stop(self):
        self._timer.stop()
        self._apply(1.0)

    def _tick(self):
        half = MOTION["pulse_steps"] / 2
        phase = (self._step % MOTION["pulse_steps"]) / half
        import math
        level = (math.sin(phase * math.pi) + 1.0) / 2.0   # 0..1..0
        self._apply(0.35 + 0.65 * level)
        self._step += 1

    def _apply(self, level: float):
        level = max(0.0, min(1.0, level))
        c = QColor(
            int(self._color_dim.red() + (self._color.red() - self._color_dim.red()) * level),
            int(self._color_dim.green() + (self._color.green() - self._color_dim.green()) * level),
            int(self._color_dim.blue() + (self._color.blue() - self._color_dim.blue()) * level),
        )
        try:
            self._widget.setStyleSheet(
                f"background-color:{c.name()};border-radius:8px;"
                f"border:1px solid rgba(255,255,255,0.2);")
        except Exception:
            pass


def _dim(color: QColor, factor: float = 0.25) -> QColor:
    c = QColor(color)
    return QColor(int(c.red() * factor), int(c.green() * factor),
                  int(c.blue() * factor))


def flash_button_border(widget, color: str) -> None:
    """按钮反馈：短暂高亮边框（用于命令面板回车命中等瞬时确认）。"""
    flash_value(widget, color, MOTION["value_flash_ms"])
