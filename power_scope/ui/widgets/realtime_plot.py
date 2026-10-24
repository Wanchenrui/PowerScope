"""基于 RingSeries 与 30 Hz 合帧的动态多通道波形。"""

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QVBoxLayout, QWidget

from ..theme import chart_color
from .plot_style import optimize_curve, style_plot
from .ring_series import RingSeries

_REDRAW_MS = 33


class RealtimePlotWidget(QWidget):
    def __init__(self, time_window=10.0, max_points=4000, parent=None):
        super().__init__(parent)
        import pyqtgraph as pg

        self._pg = pg
        self._time_window = float(time_window)
        self._max_points = int(max_points)
        self._paused = False
        self._autoscale = True
        self._channels = {}
        self._color_idx = 0
        self._t0 = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._plot = pg.PlotWidget()
        self._plot.setObjectName("card")
        self._plot.setLabel("bottom", "时间", "s")
        self._plot.setLabel("left", "值")
        self._plot.addLegend()
        self._plot.setMenuEnabled(False)
        style_plot(self._plot)
        layout.addWidget(self._plot)

        self._redraw_timer = QTimer(self)
        self._redraw_timer.timeout.connect(self._redraw)
        self._redraw_timer.start(_REDRAW_MS)

    def channel_names(self):
        return list(self._channels)

    def has_channel(self, name):
        return name in self._channels

    def channel_color(self, name):
        channel = self._channels.get(name)
        return channel["color"] if channel else None

    def add_channel(self, name, color=None):
        if not name or name in self._channels:
            return self._channels.get(name, {}).get("color")
        color = color or chart_color(self._color_idx)
        self._color_idx += 1
        pen = self._pg.mkPen(color=color, width=2)
        curve = self._plot.plot([], [], pen=pen, name=name)
        optimize_curve(curve)
        self._channels[name] = {
            "series": RingSeries(self._max_points, self._time_window),
            "curve": curve, "color": color, "visible": True,
        }
        return color

    def remove_channel(self, name):
        channel = self._channels.pop(name, None)
        if channel is not None:
            try:
                self._plot.removeItem(channel["curve"])
            except Exception:
                pass

    def clear_channels(self):
        for name in list(self._channels):
            self.remove_channel(name)
        self._color_idx = 0
        self._t0 = None

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
        self._time_window = float(seconds)
        for channel in self._channels.values():
            channel["series"].time_window = self._time_window

    def clear_data(self):
        for channel in self._channels.values():
            channel["series"].clear()
            channel["curve"].setData([], [])
        self._t0 = None

    def add_sample(self, name, timestamp, value):
        channel = self._channels.get(name)
        if channel is None or value is None or self._paused:
            return
        if self._t0 is None:
            self._t0 = timestamp
        relative = float(timestamp) - self._t0
        channel["series"].append(relative, float(value))

    def add_samples(self, name, timestamps, values):
        channel = self._channels.get(name)
        if channel is None or self._paused:
            return
        series = channel["series"]
        for timestamp, value in zip(timestamps, values):
            if value is None:
                continue
            if self._t0 is None:
                self._t0 = timestamp
            series.append(float(timestamp) - self._t0, float(value))

    def sample_count(self, name):
        channel = self._channels.get(name)
        return 0 if channel is None else channel["series"].windowed_count()

    def _redraw(self):
        if not self.isVisible():
            return
        for channel in self._channels.values():
            series = channel["series"]
            if series.dirty:
                timestamps, values = series.windowed()
                channel["curve"].setData(timestamps, values)
                series.dirty = False

    def apply_theme(self, theme_name=None):
        style_plot(self._plot, theme_name)
        for index, channel in enumerate(self._channels.values()):
            color = chart_color(index, theme_name)
            channel["color"] = color
            channel["curve"].setPen(self._pg.mkPen(color=color, width=2))
            channel["series"].dirty = True

    def showEvent(self, event):
        super().showEvent(event)
        if not self._redraw_timer.isActive():
            self._redraw_timer.start(_REDRAW_MS)
        self._redraw()

    def hideEvent(self, event):
        self._redraw_timer.stop()
        super().hideEvent(event)

    def cleanup(self):
        self._redraw_timer.stop()

    def export_csv(self, path):
        import csv
        with open(path, "w", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream)
            writer.writerow(["channel", "t_seconds", "value"])
            for name, channel in self._channels.items():
                timestamps, values = channel["series"].windowed()
                for timestamp, value in zip(timestamps, values):
                    writer.writerow([name, f"{timestamp:.6f}", value])
