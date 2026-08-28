"""step_capture.py — 阶跃响应数据采集 (Task 2 Slice 3)

订阅 EventBus 的 var/updated，按反馈通道名记录一段 (timestamp, phys_value) 采样窗口，
供 StepResponseAnalyzer 分析。窗口收尾有两个触发：
  ① 采样时间跨度达到 duration（数据驱动，正常情况）；
  ② QTimer 兜底超时（流中途冻结时仍能收尾，不会卡死）。

mark_step() 把"阶跃施加时刻"记为当前最后一个采样的时间戳（与采样同一时钟，即 MCU
微秒时间戳），供分析时对齐 t_step；无采样时留空，由调用方在分析前判空。

纯 PC 侧、无硬件依赖；MCU 无 TRIGGER_STEP，阶跃由 Slice 4 主动 WRITE_MEM 施加。
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Signal, QCoreApplication

from .event_bus import EventBus


class StepCaptureController(QObject):
    """录制单个反馈通道的 var/updated 采样窗口。"""

    finished = Signal(object)   # 发出 list[(t_seconds, phys_value)]

    def __init__(self, feedback_name, duration_s, timeout_factor=3.0, parent=None):
        super().__init__(parent)
        self._name = feedback_name
        self._duration = max(0.0, float(duration_s))
        self._samples: list[tuple[float, float]] = []
        self._t0 = None
        self._t_step = None
        self._active = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._finish)
        # 兜底超时(ms)：即使流冻结也在窗口的 timeout_factor 倍后收尾。
        self._timeout_ms = max(50, int(self._duration * timeout_factor * 1000) + 200)

    # --- 属性 ---
    @property
    def samples(self) -> list:
        return list(self._samples)

    @property
    def t_step(self):
        return self._t_step

    @property
    def is_active(self) -> bool:
        return self._active

    # --- 控制 ---
    def start(self) -> None:
        if self._active:
            return
        self._samples = []
        self._t0 = None
        self._t_step = None
        self._active = True
        EventBus.instance().subscribe("var/updated", self._on_var)
        if QCoreApplication.instance() is not None:
            self._timer.start(self._timeout_ms)

    def mark_step(self) -> None:
        """记录阶跃施加时刻为当前最后一个采样的时间戳（无采样则保持空）。"""
        if self._samples:
            self._t_step = self._samples[-1][0]

    def stop(self) -> None:
        """中止采集，不发 finished（供安全异常/取消时调用）。"""
        self._teardown()

    # --- 内部 ---
    def _on_var(self, event) -> None:
        if not self._active or getattr(event, "name", None) != self._name:
            return
        t = float(getattr(event, "timestamp", 0.0))
        v = float(getattr(event, "phys_value", 0.0))
        if self._t0 is None:
            self._t0 = t
        self._samples.append((t, v))
        if self._duration > 0 and (t - self._t0) >= self._duration:
            self._finish()

    def _finish(self) -> None:
        if not self._active:
            return
        samples = list(self._samples)
        self._teardown()
        self.finished.emit(samples)

    def _teardown(self) -> None:
        if not self._active:
            return
        self._active = False
        self._timer.stop()
        try:
            EventBus.instance().unsubscribe("var/updated", self._on_var)
        except Exception:
            pass