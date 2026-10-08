"""scope_view.py — 波形示波器视图

运行时选择任意变量（profile 变量 / ELF 符号 / 成员路径）进行多通道实时绘图。
- 订阅 EventBus `var/updated`，按通道名把物理量画到 RealtimePlotWidget（X 轴用 MCU 时间戳）。
- 通过 `channels_added/removed` 信号请求 MainWindow 把通道纳入/移出 MCU 采样列表（解决“地址变量不流式绘图”）。
- 支持批量添加、暂停/继续、清空、自动量程、时间窗、CSV 导出。
- 光标测量（P0-5）：双光标 A/B 拖拽 → 自动算出 rise/settle/overshoot → 一键回填调参页。
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QListWidget,
    QLineEdit, QLabel, QCheckBox, QDoubleSpinBox,
    QSplitter, QFileDialog, QAbstractItemView, QSizePolicy,
    QListWidgetItem, QSpinBox, QComboBox, QStackedWidget,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor

from .theme import spacing
from .widgets.empty_state import EmptyState
from .widgets.icon_button import IconButton
from ..core.wave_measure import (
    cursor_readout, format_summary, measure, readouts_summary,
)
from .widgets.realtime_plot import RealtimePlotWidget


class ScopeView(QWidget):
    """示波器视图 — 动态通道实时波形。"""

    channels_added = Signal(list)     # list[str]：请求开始流式采集的通道名
    channels_removed = Signal(list)   # list[str]：请求停止采集的通道名
    record_requested = Signal(int, int)  # points, tap_id
    triggered_record_requested = Signal(int, int, int)  # points, tap_id, pre_points
    wave_trigger_requested = Signal()
    live_start_requested = Signal(int)  # tap_id
    live_stop_requested = Signal()
    record_abort_requested = Signal()
    export_completed = Signal(str)  # CSV path; MainWindow writes exact raw sidecars
    metrics_to_tuning = Signal(dict)  # 光标区间测量指标 → 调参页回填（P0-5）

    def __init__(self, profile=None, parent=None):
        super().__init__(parent)
        self._profile = profile
        self._available = []
        self._live_running = False
        self._measure_mode = False
        self._last_measurement = None
        self._measure_channel = ""     # 测量取哪个通道（空=首个）
        # 搜索防抖定时器（textChanged → 150ms 合并）
        from PySide6.QtCore import QTimer
        self._filter_timer = QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(150)
        self._filter_timer.timeout.connect(self._refilter)
        self._build_ui()
        self._subscribe()
        self.destroyed.connect(self._cleanup)

    # ---- EventBus ----
    def _subscribe(self):
        from ..core.event_bus import EventBus
        EventBus.instance().subscribe("var/updated", self._on_var_updated)
        EventBus.instance().subscribe("wave/live_block", self._on_live_block)

    def _cleanup(self):
        try:
            from ..core.event_bus import EventBus
            EventBus.instance().unsubscribe("var/updated", self._on_var_updated)
            EventBus.instance().unsubscribe("wave/live_block", self._on_live_block)
        except Exception:
            pass

    # ---- UI ----
    def _build_ui(self):
        outer = QVBoxLayout(self)

        ctrl = QHBoxLayout()
        ctrl.setSpacing(spacing("sm"))
        # 工具栏图标化（P0-6）：高频操作用矢量图标 + tooltip，去「文字墙」
        self._pause_btn = IconButton("pause", "暂停", tooltip="暂停/继续波形刷新")
        self._pause_btn.setCheckable(True)
        self._pause_btn.toggled.connect(self._on_pause)
        ctrl.addWidget(self._pause_btn)
        clear_btn = IconButton("clear", "清空数据", tooltip="清空全部通道数据")
        clear_btn.clicked.connect(lambda: self._plot.clear_data())
        ctrl.addWidget(clear_btn)
        self._autoscale = QCheckBox("自动量程")
        self._autoscale.setChecked(True)
        self._autoscale.toggled.connect(lambda c: self._plot.set_autoscale(c))
        ctrl.addWidget(self._autoscale)
        ctrl.addWidget(QLabel("时间窗(s):"))
        self._window = QDoubleSpinBox()
        self._window.setRange(1, 120)
        self._window.setValue(10)
        self._window.valueChanged.connect(self._on_window)
        ctrl.addWidget(self._window)
        export_btn = IconButton("export", "导出CSV", tooltip="导出当前波形数据为 CSV")
        export_btn.clicked.connect(self._on_export)
        ctrl.addWidget(export_btn)
        # 光标测量（P0-5）：checkable，开启后出现双光标与指标条
        self._measure_btn = IconButton("record", "测量", tooltip="双光标测量 rise/settle/overshoot 并回填调参页")
        self._measure_btn.setCheckable(True)
        self._measure_btn.toggled.connect(self._on_measure_toggled)
        ctrl.addWidget(self._measure_btn)
        ctrl.addWidget(QLabel("录波点数:"))
        self._record_points = QSpinBox()
        self._record_points.setRange(256, 32768)
        self._record_points.setSingleStep(256)
        self._record_points.setValue(2048)
        ctrl.addWidget(self._record_points)
        self._record_tap = QComboBox()
        self._record_tap.addItem("控制结束", 1)
        self._record_tap.addItem("ADC就绪", 0)
        ctrl.addWidget(self._record_tap)
        self._record_mode = QComboBox()
        self._record_mode.addItem("立即", 0)
        self._record_mode.addItem("前触发", 1)
        ctrl.addWidget(self._record_mode)
        self._pretrigger_percent = QSpinBox()
        self._pretrigger_percent.setRange(0, 95)
        self._pretrigger_percent.setValue(50)
        self._pretrigger_percent.setSuffix("%前")
        ctrl.addWidget(self._pretrigger_percent)
        self._record_btn = IconButton("record", "25us录波")
        self._record_btn.setObjectName("btn_primary")
        self._record_btn.clicked.connect(self._emit_record_request)
        ctrl.addWidget(self._record_btn)
        self._trigger_btn = IconButton("trigger", "触发",
                                       tooltip="前触发模式布防后手动触发")
        self._trigger_btn.setEnabled(False)
        self._trigger_btn.clicked.connect(self.wave_trigger_requested.emit)
        ctrl.addWidget(self._trigger_btn)
        self._live_btn = IconButton("play", "无损Live")
        self._live_btn.setCheckable(True)
        self._live_btn.toggled.connect(self._on_live_toggled)
        ctrl.addWidget(self._live_btn)
        self._record_abort_btn = IconButton("clear", "取消录波")
        self._record_abort_btn.setEnabled(False)
        self._record_abort_btn.clicked.connect(self.record_abort_requested.emit)
        ctrl.addWidget(self._record_abort_btn)
        ctrl.addStretch()
        self._hint = QLabel(
            "提示: 波形通道仅进入显式 25us Recorder/Live；不会混入慢速监控列表")
        self._hint.setObjectName("dim")
        # 长提示不参与最小宽度计算，避免撑大窗口最小尺寸（空间不足时自动省略）
        self._hint.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        ctrl.addWidget(self._hint)
        outer.addLayout(ctrl)

        # ── 测量读数条（双光标 A/B + 自动指标 + 回填调参，P0-5）──
        self._measure_bar = QHBoxLayout()
        self._measure_bar.setSpacing(spacing("md"))
        self._readout_label = QLabel("光标: --")
        self._readout_label.setObjectName("dim")
        self._measure_bar.addWidget(self._readout_label)
        self._measure_result = QLabel("指标: 未测量")
        self._measure_result.setObjectName("dim")
        self._measure_bar.addWidget(self._measure_result, 1)
        self._send_to_tuning_btn = IconButton(
            "tuning", "发往调参页",
            tooltip="把光标区间测得的超调/上升/调节时间回填到调参页")
        self._send_to_tuning_btn.setEnabled(False)
        self._send_to_tuning_btn.clicked.connect(self._send_metrics_to_tuning)
        self._measure_bar.addWidget(self._send_to_tuning_btn)
        self._measure_widget = QWidget()
        self._measure_widget.setLayout(self._measure_bar)
        self._measure_widget.setVisible(False)
        outer.addWidget(self._measure_widget)

        splitter = QSplitter(Qt.Horizontal)

        left = QWidget()
        ll = QVBoxLayout(left)
        avail_group = QGroupBox("可选变量")
        ag = QVBoxLayout(avail_group)
        self._search = QLineEdit()
        self._search.setPlaceholderText("🔍 过滤变量")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._schedule_refilter)
        ag.addWidget(self._search)
        self._avail_list = QListWidget()
        self._avail_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._avail_list.itemDoubleClicked.connect(lambda it: self._add_names([it.text()]))
        ag.addWidget(self._avail_list)
        # 唯一 primary 留给「25us录波」（页面签名操作），添加通道降为描边
        add_btn = IconButton("plus", "添加选中到波形",
                             tooltip="把左侧选中的变量加入示波器")
        add_btn.clicked.connect(self._on_add_selected)
        ag.addWidget(add_btn)
        ll.addWidget(avail_group)

        chan_group = QGroupBox("当前通道")
        cg = QVBoxLayout(chan_group)
        self._chan_list = QListWidget()
        self._chan_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        cg.addWidget(self._chan_list)
        rm_btn = IconButton("minus", "移除选中通道",
                            tooltip="把选中通道移出示波器并停止采集")
        rm_btn.clicked.connect(self._on_remove_selected)
        cg.addWidget(rm_btn)
        ll.addWidget(chan_group)
        splitter.addWidget(left)

        self._plot = RealtimePlotWidget(time_window=10.0)
        # 光标读数 → 读数条；双光标 → 自动测量
        self._plot.cursor_readout.connect(self._on_cursor_readout)
        self._plot.dual_cursor_moved.connect(self._on_dual_cursor_moved)
        # 空态 ↔ 波形：无通道时给引导，加入第一个通道后切走
        self._plot_stack = QStackedWidget()
        self._plot_empty = EmptyState(
            "wave", "还没有波形通道",
            "从左侧「可选变量」里搜索并添加变量，这里会按 MCU 时间戳实时绘图",
            action_text="添加选中到波形", action=self._on_add_selected)
        self._plot_stack.addWidget(self._plot_empty)
        self._plot_stack.addWidget(self._plot)
        self._plot_stack.setCurrentIndex(0)
        splitter.addWidget(self._plot_stack)
        splitter.setSizes([260, 820])
        outer.addWidget(splitter, 1)  # 拉伸填满剩余高度，消除工具栏与图区之间的空档

    # ---- 可选变量来源 ----
    def set_available_variables(self, names):
        self._available = list(dict.fromkeys(n for n in names if n))
        self._refilter()

    def _refilter(self):
        q = self._search.text().strip().lower()
        self._avail_list.clear()
        for n in self._available:
            if not q or q in n.lower():
                self._avail_list.addItem(n)

    def _schedule_refilter(self):
        """搜索防抖：击键后 150ms 合并重建列表，避免逐键全量刷新卡顿。"""
        self._filter_timer.start()

    # ---- 增删通道 ----
    def _on_add_selected(self):
        self._add_names([it.text() for it in self._avail_list.selectedItems()])

    def add_channels_external(self, names):
        """供「变量查看」批量「加入波形」调用。"""
        self._add_names(names)

    def _add_names(self, names):
        added = []
        for n in names:
            if n and not self._plot.has_channel(n):
                if hasattr(self, "_plot_stack"):
                    self._plot_stack.setCurrentIndex(1)
                color = self._plot.add_channel(n)
                # 通道项带曲线同色圆点，列表与波形颜色一目了然
                item = QListWidgetItem(f"● {n}")
                item.setData(Qt.UserRole, n)
                if color:
                    item.setForeground(QColor(color))
                self._chan_list.addItem(item)
                added.append(n)
        if added:
            self.channels_added.emit(added)

    def _on_remove_selected(self):
        names = [it.data(Qt.UserRole) or it.text()
                 for it in self._chan_list.selectedItems()]
        for n in names:
            self._plot.remove_channel(n)
            for i in range(self._chan_list.count() - 1, -1, -1):
                it = self._chan_list.item(i)
                if (it.data(Qt.UserRole) or it.text()) == n:
                    self._chan_list.takeItem(i)
        if names:
            self.channels_removed.emit(names)

    def plotted_channels(self):
        return self._plot.channel_names()

    # ---- 数据 ----
    def _on_var_updated(self, event):
        if self._plot.has_channel(event.name):
            self._plot.add_sample(event.name, event.timestamp, event.phys_value)

    def _on_live_block(self, block):
        if not self._live_running:
            return
        if self._plot.has_channel(block.get("name", "")):
            self._plot.add_samples(
                block["name"], block["timestamps"], block["phys_values"])

    # ---- 控制 ----
    def _emit_record_request(self):
        points = self._record_points.value()
        tap = self._record_tap.currentData()
        if self._record_mode.currentData() == 1:
            pre = points * self._pretrigger_percent.value() // 100
            self.triggered_record_requested.emit(points, tap, pre)
        else:
            self.record_requested.emit(points, tap)

    def _on_live_toggled(self, checked):
        if checked:
            self.live_start_requested.emit(self._record_tap.currentData())
        else:
            self.live_stop_requested.emit()

    def set_record_status(self, text: str, busy: bool = False):
        """更新 Recorder 状态；数据下载完成前禁止重复启动。"""
        self._hint.setText(text)
        self._record_btn.setEnabled(not busy)
        self._record_abort_btn.setEnabled(busy)

    def set_trigger_enabled(self, enabled: bool):
        self._trigger_btn.setEnabled(bool(enabled))

    def set_live_status(self, text: str, running: bool):
        self._live_running = bool(running)
        self._hint.setText(text)
        self._live_btn.blockSignals(True)
        self._live_btn.setChecked(bool(running))
        self._live_btn.setText("停止Live" if running else "无损Live")
        self._live_btn.blockSignals(False)
        self._record_btn.setEnabled(not running)

    # ---- 光标测量（P0-5） ----
    def _on_measure_toggled(self, checked: bool):
        """测量模式：开启 → 双光标 + 读数条；关闭 → 清理。"""
        self._measure_mode = bool(checked)
        self._measure_widget.setVisible(self._measure_mode)
        if checked:
            self._measure_btn.setText("停止测量")
            self._plot.enable_dual_cursors(True)
            self._plot.enable_crosshair(True)
        else:
            self._measure_btn.setText("测量")
            self._plot.enable_dual_cursors(False)
            self._plot.enable_crosshair(False)
            self._readout_label.setText("光标: --")
            self._measure_result.setText("指标: 未测量")
            self._send_to_tuning_btn.setEnabled(False)

    def _measure_target(self) -> str:
        """测量取哪个通道：显式选择 > 当前列表第一个。"""
        if self._measure_channel and self._plot.has_channel(self._measure_channel):
            return self._measure_channel
        names = self._plot.channel_names()
        return names[0] if names else ""

    def _on_cursor_readout(self, t: float, y: float):
        if not self._measure_mode:
            return
        self._readout_label.setText(
            f"光标: t={t:.4f}s  y={y:.4g}")

    def _on_dual_cursor_moved(self, ta: float, tb: float):
        if not self._measure_mode:
            return
        channel = self._measure_target()
        if not channel:
            return
        times, values = self._plot.windowed_series(channel)
        ra = cursor_readout(times, values, ta)
        rb = cursor_readout(times, values, tb)
        self._readout_label.setText(readouts_summary(ra, rb))
        m = measure(times, values, min(ta, tb), max(ta, tb),
                    channel=channel)
        self._last_measurement = m
        if m.valid:
            self._measure_result.setText("指标: " + format_summary(m))
            self._send_to_tuning_btn.setEnabled(True)
        else:
            self._measure_result.setText(f"指标: {m.info or '无效区间'}")
            self._send_to_tuning_btn.setEnabled(False)

    def _send_metrics_to_tuning(self):
        """把光标区间测得的指标发往调参页回填（P0-5 闭环）。"""
        m = self._last_measurement
        if m is None or not m.valid:
            self._measure_result.setText("指标: 无有效测量，先拖好 A/B 光标")
            return
        self.metrics_to_tuning.emit({
            "channel": m.channel,
            "overshoot_pct": m.overshoot_pct,
            "rise_ms": m.rise_ms,
            "settle_ms": m.settle_ms,
            "steady": m.steady,
        })

    def show_record_capture(self, decoded: dict):
        """一次批量加入完整录波，避免逐点 Qt 事件。"""
        self._plot.clear_data()
        for name, values in decoded.items():
            self._plot.add_samples(
                name, values["timestamps"], values["phys_values"])

    def _on_pause(self, checked):
        self._plot.set_paused(checked)
        self._pause_btn.setText("继续" if checked else "暂停")

    def _on_window(self, value):
        self._plot.set_time_window(float(value))

    def cleanup(self):
        try:
            from ..core.event_bus import EventBus
            bus = EventBus.instance()
            bus.unsubscribe("var/updated", self._on_var_updated)
            bus.unsubscribe("wave/live_block", self._on_live_block)
        except Exception:
            pass

    def _on_export(self):
        if not self._plot.channel_names():
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出波形数据", "scope.csv", "CSV (*.csv)")
        if path:
            self._plot.export_csv(path)
            self.export_completed.emit(path)

    # ---- 工作区快照（P1-7） ----
    def scope_splitter(self):
        """波形页的 splitter（供工作区快照记录/恢复尺寸）。"""
        return self.findChild(QSplitter)

    def collect_workspace(self) -> dict:
        """导出本页可恢复状态：通道集合 + 时间窗 + 自动量程。"""
        return {
            "scope_channels": list(self._plot.channel_names()),
            "scope_time_window": self._window.value(),
            "scope_autoscale": self._autoscale.isChecked(),
        }

    def restore_workspace(self, data: dict) -> None:
        """从快照恢复（通道的实际地址解析由 MainWindow 收到信号后补全）。"""
        channels = list(data.get("scope_channels", []))
        self._window.setValue(float(data.get("scope_time_window", 10)))
        self._autoscale.setChecked(bool(data.get("scope_autoscale", True)))
        if channels:
            self._add_names(channels)
