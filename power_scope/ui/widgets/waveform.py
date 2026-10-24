"""配置驱动的实时波形卡片。"""

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

from ..theme import chart_color, font_size
from .plot_style import optimize_curve, style_plot
from .ring_series import RingSeries

_MAX_POINTS = 2000
_REDRAW_MS = 33


class WaveformWidget(QFrame):
    def __init__(self, title, variables, time_window=5.0):
        super().__init__()
        self.setObjectName("card")
        import pyqtgraph as pg

        self._pg = pg
        self._vars = variables
        self._time_window = time_window
        self._series = {
            variable: RingSeries(_MAX_POINTS, time_window) for variable in variables
        }
        self._curves = {}
        self._start_time = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)
        header = QHBoxLayout()
        title_label = QLabel(title)
        title_label.setObjectName("section_title")
        header.addWidget(title_label)
        header.addStretch()
        self._var_leds = {}
        for index, variable in enumerate(variables):
            led = QLabel(f"● {variable}")
            led.setStyleSheet(
                f"color:{chart_color(index)};font-size:{font_size('xs')};")
            header.addWidget(led)
            self._var_leds[variable] = (index, led)
        layout.addLayout(header)

        self._plot = pg.PlotWidget()
        self._plot.setMinimumHeight(150)
        self._plot.setLabel("bottom", "时间", "s")
        self._plot.setLabel("left", "值")
        self._plot.setMenuEnabled(False)
        self._plot.setMouseEnabled(x=True, y=True)
        style_plot(self._plot)
        for index, variable in enumerate(variables):
            color = chart_color(index)
            curve = self._plot.plot(
                [], [], pen=pg.mkPen(color=color, width=2), name=variable)
            optimize_curve(curve)
            self._curves[variable] = curve
        layout.addWidget(self._plot)

        self._redraw_timer = QTimer(self)
        self._redraw_timer.timeout.connect(self._redraw)
        self._redraw_timer.start(_REDRAW_MS)

    def add_data(self, var, timestamp, value):
        series = self._series.get(var)
        if series is None:
            return
        if self._start_time is None:
            self._start_time = timestamp
        series.append(timestamp - self._start_time, value)

    def _redraw(self):
        if not self.isVisible():
            return
        for variable, series in self._series.items():
            if series.dirty:
                timestamps, values = series.windowed()
                self._curves[variable].setData(timestamps, values)
                series.dirty = False

    def apply_theme(self, theme_name=None):
        style_plot(self._plot, theme_name)
        for index, variable in enumerate(self._vars):
            color = chart_color(index, theme_name)
            self._curves[variable].setPen(self._pg.mkPen(color=color, width=2))
            if variable in self._var_leds:
                _, led = self._var_leds[variable]
                led.setStyleSheet(f"color:{color};font-size:{font_size('xs')};")
            self._series[variable].dirty = True

    def update_values(self, values):
        return

    def sample_count(self, var):
        series = self._series.get(var)
        return 0 if series is None else series.windowed_count()

    def on_var_event(self, event):
        if event.name in self._series and event.phys_value is not None:
            self.add_data(event.name, event.timestamp, event.phys_value)

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
