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
from PySide6.QtCore import QTimer, Qt, Signal

from ..theme import chart_color, current_theme, get_theme, style_plot_widget
from .ring_series import RingSeries

_REDRAW_MS = 33  # ~30fps 合帧重绘


class RealtimePlotWidget(QWidget):
    """动态多通道实时波形。

    用法::
        w = RealtimePlotWidget()
        w.add_channel("Vdc")
        w.add_sample("Vdc", t_seconds, value)

    光标测量（P0-5）：enable_crosshair() 鼠标十字线读数；
    enable_dual_cursors() 双光标 A/B 拖拽测量，读数经 dual_cursor_moved
    信号输出，指标计算走 core.wave_measure（纯逻辑可单测）。
    """

    #: 鼠标十字线读数（时间, 值）；值取最靠近鼠标的通道
    cursor_readout = Signal(float, float)
    #: 双光标移动（A 时间, B 时间）
    dual_cursor_moved = Signal(float, float)

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
        style_plot_widget(self._plot)      # 网格/坐标轴跟随主题
        self._plot.setLabel("bottom", "时间", "s")
        self._plot.setLabel("left", "值")
        self._plot.addLegend()
        self._plot.setMenuEnabled(False)
        style_plot_widget(self._plot)      # addLegend 之后再统一一次
        lay.addWidget(self._plot)

        # 合帧重绘定时器 — 数据写入只进环形缓冲，这里统一 setData
        self._redraw_timer = QTimer(self)
        self._redraw_timer.timeout.connect(self._redraw)
        self._redraw_timer.start(_REDRAW_MS)

        # 光标状态（P0-5）：十字线 + 双拖拽光标
        self._crosshair_on = False
        self._crosshair_v = None
        self._dual_on = False
        self._cursor_a = None
        self._cursor_b = None
        self._dragging = None

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

    # ---- 数据访问（光标测量用） ----
    def windowed_series(self, name):
        """返回 (times, values) 窗口内数据的拷贝（无该通道返回 ([], [])）。"""
        ch = self._channels.get(name)
        if ch is None:
            return [], []
        t, v = ch["series"].windowed()
        return list(t), list(v)

    def nearest_channel_value(self, t: float):
        """取所有通道中离 t 最近的样本 (name, t, value)；无样本返回 None。"""
        best = None
        for name, ch in self._channels.items():
            times, values = ch["series"].windowed()
            if not times:
                continue
            idx = min(range(len(times)), key=lambda i: abs(times[i] - t))
            dist = abs(times[idx] - t)
            if best is None or dist < best[2]:
                best = (name, times[idx], values[idx], dist)
        if best is None:
            return None
        return best[0], best[1], best[2]

    def data_time_extent(self):
        """全部通道合并的 (t_min, t_max)；无样本返回 None。"""
        lo, hi = None, None
        for ch in self._channels.values():
            times, _v = ch["series"].windowed()
            if not times:
                continue
            c_lo, c_hi = times[0], times[-1]
            lo = c_lo if lo is None else min(lo, c_lo)
            hi = c_hi if hi is None else max(hi, c_hi)
        return None if lo is None else (lo, hi)

    # ---- 光标测量（P0-5） ----
    def enable_crosshair(self, on: bool):
        """鼠标十字线：移动时发 cursor_readout(t, y)，竖线随手移动。"""
        on = bool(on)
        if on and not self._crosshair_on:
            scene = self._plot.scene()
            try:
                scene.sigMouseMoved.connect(self._on_mouse_moved)
            except Exception:
                pass
        self._crosshair_on = on
        if not on and self._crosshair_v is not None:
            try:
                self._plot.removeItem(self._crosshair_v)
            except Exception:
                pass
            self._crosshair_v = None

    def _on_mouse_moved(self, pos):
        if not self._crosshair_on:
            return
        try:
            mouse_point = self._plot.getPlotItem().vb.mapSceneToView(pos)
        except Exception:
            return
        t = float(mouse_point.x())
        if self._crosshair_v is None:
            self._crosshair_v = self._pg.InfiniteLine(
                angle=90, movable=False,
                pen=self._pg.mkPen(get_theme(current_theme())["text_dim"],
                                   width=1, style=Qt.DashLine))
            self._plot.addItem(self._crosshair_v)
        self._crosshair_v.setPos(t)
        near = self.nearest_channel_value(t)
        if near is not None:
            _name, yt, yv = near
            self.cursor_readout.emit(yt, yv)
        else:
            self.cursor_readout.emit(t, 0.0)

    def enable_dual_cursors(self, on: bool):
        """双光标 A/B（可拖拽竖线），移动经 dual_cursor_moved 输出。"""
        self._dual_on = bool(on)
        if on:
            if self._cursor_a is None:
                self._cursor_a = self._pg.InfiniteLine(
                    angle=90, movable=True, label="A",
                    pen=self._pg.mkPen(get_theme(current_theme())["chart3"],
                                       width=1.4))
                self._cursor_b = self._pg.InfiniteLine(
                    angle=90, movable=True, label="B",
                    pen=self._pg.mkPen(get_theme(current_theme())["chart1"],
                                       width=1.4))
                for cursor in (self._cursor_a, self._cursor_b):
                    cursor.setZValue(1000)
                    cursor.sigPositionChanged.connect(self._on_cursor_moved)
                    cursor.sigDragged.connect(self._on_cursor_dragged)
                    self._plot.addItem(cursor)
            extent = self.data_time_extent()
            if extent is not None:
                span = extent[1] - extent[0]
                self._cursor_a.setPos(extent[0] + span * 0.25)
                self._cursor_b.setPos(extent[0] + span * 0.75)
            else:
                self._cursor_a.setPos(0.0)
                self._cursor_b.setPos(10.0)
            self._emit_dual()
        else:
            for cursor in (self._cursor_a, self._cursor_b):
                if cursor is not None:
                    try:
                        self._plot.removeItem(cursor)
                    except Exception:
                        pass
            self._cursor_a = None
            self._cursor_b = None

    def _on_cursor_dragged(self, line):
        self._dragging = line

    def _on_cursor_moved(self, _line=None):
        if self._cursor_a is None or self._cursor_b is None:
            return
        ta, tb = self._cursor_a.value(), self._cursor_b.value()
        if ta > tb:            # 保持 A 在左，避免区间反向
            if self._dragging is self._cursor_a:
                self._cursor_a.setValue(tb)
            else:
                self._cursor_b.setValue(ta)
        self._emit_dual()

    def _emit_dual(self):
        if self._cursor_a is None or self._cursor_b is None:
            return
        self.dual_cursor_moved.emit(float(self._cursor_a.value()),
                                    float(self._cursor_b.value()))

    @property
    def dual_cursors_active(self) -> bool:
        return self._dual_on

    def set_cursor_positions(self, ta: float, tb: float):
        if self._cursor_a is None or self._cursor_b is None:
            return
        self._cursor_a.setValue(min(ta, tb))
        self._cursor_b.setValue(max(ta, tb))
        self._emit_dual()

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
        """跟随全局主题：背景/网格/坐标轴 + 曲线按新调色板重新着色。"""
        t = get_theme(theme_name or current_theme())
        style_plot_widget(self._plot, theme_name)
        for i, (name, ch) in enumerate(self._channels.items()):
            color = chart_color(i, theme_name)
            ch["color"] = color
            ch["curve"].setPen(self._pg.mkPen(color=color, width=2))
            series = ch["series"]
            series.dirty = True
        # 十字线/双光标换成新主题的语义色
        if self._crosshair_v is not None:
            self._crosshair_v.setPen(
                self._pg.mkPen(t["text_dim"], width=1, style=Qt.DashLine))
        if self._cursor_a is not None:
            self._cursor_a.setPen(self._pg.mkPen(chart_color(2, theme_name), width=1.4))
        if self._cursor_b is not None:
            self._cursor_b.setPen(self._pg.mkPen(chart_color(0, theme_name), width=1.4))

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
