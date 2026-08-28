"""realtime_plot.py — 动态多通道实时波形组件（基于 pyqtgraph）

与 widgets/waveform.py（配置固定通道）不同，本组件支持运行时增删通道，
并以 MCU 时间戳为 X 轴绘制物理量，供「波形」示波器视图使用。

性能设计：
  - 每通道 RingSeries 环形缓冲，add_sample O(1)
  - 30Hz QTimer 合帧重绘（仅重绘有新数据的通道），高频流下 UI 不卡顿
  - apply_theme() 跟随全局主题切换背景/前景/曲线调色板

非 GUI 的数据缓冲/导出逻辑可独立单测（需 QApplication 实例化 pyqtgraph）。
"""
from PySide6.QtWidgets import QWidget, QVBoxLayout
from PySide6.QtCore import QTimer

from ..theme import chart_color, get_theme, current_theme
from .ring_series import RingSeries

_REDRAW_MS = 33  # ~30fps 合帧重绘


class RealtimePlotWidget(QWidget):
    """动态多通道实时波形。

    用法::
        w = RealtimePlotWidget()
        w.add_channel("Vdc")
        w.add_sample("Vdc", t_seconds, value)
    """

    def __init__(self, time_window=10.0, max_points=4000, parent=None):
        super().__init__(parent)
        import pyqtgraph as pg

        self._pg = pg
        self._time_window = float(time_window)
        self._max_points = int(max_points)
        self._paused = False
        self._autoscale = True
        self._channels = {}      # name -> {series, curve, color, visible}
        self._color_idx = 0
        self._t0 = None          # 首个样本时间戳，用于相对时间

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self._plot = pg.PlotWidget()
        self._plot.setObjectName("card")
        self._plot.showGrid(x=True, y=True, alpha=0.3)
        self._plot.setLabel("bottom", "时间", "s")
        self._plot.setLabel("left", "值")
        self._plot.addLegend()
        self._plot.setMenuEnabled(False)
        lay.addWidget(self._plot)

        # 合帧重绘定时器 — 数据写入只进环形缓冲，这里统一 setData
        self._redraw_timer = QTimer(self)
        self._redraw_timer.timeout.connect(self._redraw)
        self._redraw_timer.start(_REDRAW_MS)

    # ---- 通道管理 ----
    def channel_names(self):
        return list(self._channels)

    def has_channel(self, name):
        return name in self._channels

    def channel_color(self, name):
        ch = self._channels.get(name)
        return ch["color"] if ch else None

    def add_channel(self, name, color=None):
        if not name or name in self._channels:
            return self._channels.get(name, {}).get("color")
        color = color or chart_color(self._color_idx)
        self._color_idx += 1
        pen = self._pg.mkPen(color=color, width=2)
        curve = self._plot.plot([], [], pen=pen, name=name)
        self._channels[name] = {
            "series": RingSeries(self._max_points, self._time_window),
            "curve": curve, "color": color, "visible": True,
        }
        return color

    def remove_channel(self, name):
        ch = self._channels.pop(name, None)
        if ch is not None:
            try:
                self._plot.removeItem(ch["curve"])
            except Exception:
                pass

    def clear_channels(self):
        for name in list(self._channels):
            self.remove_channel(name)
        self._color_idx = 0
        self._t0 = None

    # ---- 运行控制 ----
    def set_paused(self, paused):
        self._paused = bool(paused)

    def is_paused(self):
        return self._paused

    def set_autoscale(self, on):
        self._autoscale = bool(on)
        if on:
            self._plot.enableAutoRange()
        else:
            self._plot.disableAutoRange()

    def set_time_window(self, seconds):
        """设置时间窗（秒），所有通道即刻生效。"""
        self._time_window = float(seconds)
        for ch in self._channels.values():
            ch["series"].time_window = self._time_window

    def clear_data(self):
        for ch in self._channels.values():
            ch["series"].clear()
            ch["curve"].setData([], [])
        self._t0 = None

    # ---- 数据 ----
    def add_sample(self, name, timestamp, value):
        ch = self._channels.get(name)
        if ch is None or value is None or self._paused:
            return
        if self._t0 is None:
            self._t0 = timestamp
        rel = float(timestamp) - self._t0
        ch["series"].append(rel, float(value))

    def add_samples(self, name, timestamps, values):
        """批量追加（流式帧一次多个样本时使用），仍走环形缓冲。"""
        ch = self._channels.get(name)
        if ch is None or self._paused:
            return
        series = ch["series"]
        for t, v in zip(timestamps, values):
            if v is None:
                continue
            if self._t0 is None:
                self._t0 = t
            series.append(float(t) - self._t0, float(v))

    def sample_count(self, name):
        ch = self._channels.get(name)
        return 0 if ch is None else ch["series"].windowed_count()

    def _redraw(self):
        """30Hz 合帧：只重绘有新样本的通道。"""
        for ch in self._channels.values():
            series = ch["series"]
            if series.dirty:
                t, v = series.windowed()
                ch["curve"].setData(t, v)
                series.dirty = False

    # ---- 主题 ----
    def apply_theme(self, theme_name=None):
        """跟随全局主题：背景/前景 + 曲线按新调色板重新着色。"""
        t = get_theme(theme_name or current_theme())
        self._plot.setBackground(t["bg_alt"])
        for i, (name, ch) in enumerate(self._channels.items()):
            color = chart_color(i, theme_name)
            ch["color"] = color
            ch["curve"].setPen(self._pg.mkPen(color=color, width=2))
            series = ch["series"]
            series.dirty = True

    # ---- 导出 ----
    def export_csv(self, path):
        import csv
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["channel", "t_seconds", "value"])
            for name, ch in self._channels.items():
                t, v = ch["series"].windowed()
                for ti, vi in zip(t, v):
                    w.writerow([name, f"{ti:.6f}", vi])
