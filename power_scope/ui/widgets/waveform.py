"""波形图组件 — 基于 pyqtgraph 的实时多通道波形显示"""
from PySide6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QLabel
from PySide6.QtCore import QTimer

from ..theme import chart_color, get_theme, current_theme
from .ring_series import RingSeries

_MAX_POINTS = 2000   # 与旧实现的最大点数一致
_REDRAW_MS = 33      # ~30fps 合帧重绘


class WaveformWidget(QFrame):
    """实时波形组件 — 基于 pyqtgraph

    每个变量对应一条曲线，自动维护时间窗口滑动。
    支持 add_data(var, timestamp, value) 直接添加，
    也支持 update_values({var: value}) 批量更新。

    数据写入 RingSeries 环形缓冲（O(1)），30Hz 定时器合帧重绘。
    """

    def __init__(self, title, variables, time_window=5.0):
        super().__init__()
        self.setObjectName("card")
        import pyqtgraph as pg

        self._pg = pg
        self._vars = variables
        self._time_window = time_window
        self._series = {
            v: RingSeries(_MAX_POINTS, time_window) for v in variables
        }
        self._curves = {}
        self._start_time = None  # 首次数据时间，用于相对时间

        lay = QVBoxLayout(self)
        hdr = QHBoxLayout()
        tl = QLabel(title)
        tl.setObjectName("title")
        hdr.addWidget(tl)
        hdr.addStretch()
        self._var_leds = {}
        for i, v in enumerate(variables):
            led = QLabel(f"● {v}")
            led.setStyleSheet(f"color:{chart_color(i)};font-size:11px;")
            hdr.addWidget(led)
            self._var_leds[v] = (i, led)
        lay.addLayout(hdr)

        self._plot = pg.PlotWidget()
        self._plot.setMinimumHeight(150)
        self._plot.setLabel("bottom", "时间", "s")
        self._plot.setLabel("left", "值")
        self._plot.showGrid(x=True, y=True, alpha=0.3)
        self._plot.setMenuEnabled(False)
        self._plot.setMouseEnabled(x=True, y=True)
        for i, v in enumerate(variables):
            color = chart_color(i)
            pen = pg.mkPen(color=color, width=2)
            curve = self._plot.plot([], [], pen=pen, name=v)
            self._curves[v] = curve
        lay.addWidget(self._plot)

        self._redraw_timer = QTimer(self)
        self._redraw_timer.timeout.connect(self._redraw)
        self._redraw_timer.start(_REDRAW_MS)

    def add_data(self, var, timestamp, value):
        """直接添加数据点（timestamp 为绝对时间或相对时间）"""
        series = self._series.get(var)
        if series is None:
            return
        if self._start_time is None:
            self._start_time = timestamp
        series.append(timestamp - self._start_time, value)

    def _redraw(self):
        for v, series in self._series.items():
            if series.dirty:
                t, d = series.windowed()
                self._curves[v].setData(t, d)
                series.dirty = False

    def apply_theme(self, theme_name=None):
        """跟随全局主题重着色（背景 + 曲线 + 图例 LED）。"""
        name = theme_name or current_theme()
        t = get_theme(name)
        self._plot.setBackground(t["bg_alt"])
        for i, v in enumerate(self._vars):
            color = chart_color(i, name)
            self._curves[v].setPen(self._pg.mkPen(color=color, width=2))
            if v in self._var_leds:
                _, led = self._var_leds[v]
                led.setStyleSheet(f"color:{color};font-size:11px;")
            self._series[v].dirty = True

    def update_values(self, values):
        """兼容旧接口；实际数据走 on_var_event（带 MCU 时间戳与物理量）。"""
        return

    def sample_count(self, var):
        """变量当前时间窗内的样本数（测试与状态显示用）。"""
        s = self._series.get(var)
        return 0 if s is None else s.windowed_count()

    def on_var_event(self, event):
        """DashboardView 调用 — 用 MCU 时间戳绘制物理量（避免 PC 时钟抖动/重复点）。"""
        if event.name in self._series and event.phys_value is not None:
            self.add_data(event.name, event.timestamp, event.phys_value)
