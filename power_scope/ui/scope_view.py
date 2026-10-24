"""多通道实时波形与高速录波视图。"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .theme import ui_color
from .widgets.icons import icon
from .widgets.primitives import PageHeader, StatusBadge
from .widgets.realtime_plot import RealtimePlotWidget


class ScopeView(QWidget):
    channels_added = Signal(list)
    channels_removed = Signal(list)
    record_requested = Signal(int, int)
    triggered_record_requested = Signal(int, int, int)
    wave_trigger_requested = Signal()
    live_start_requested = Signal(int)
    live_stop_requested = Signal()
    record_abort_requested = Signal()
    export_completed = Signal(str)

    def __init__(self, profile=None, parent=None):
        super().__init__(parent)
        self._profile = profile
        self._available = []
        self._live_running = False
        self._hint_role = "text_dim"
        from PySide6.QtCore import QTimer
        self._filter_timer = QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(150)
        self._filter_timer.timeout.connect(self._refilter)
        self._build_ui()
        self._subscribe()
        self.destroyed.connect(self._cleanup)

    def _subscribe(self):
        from ..core.event_bus import EventBus
        EventBus.instance().subscribe("var/updated", self._on_var_updated)
        EventBus.instance().subscribe("wave/live_block", self._on_live_block)

    def _cleanup(self):
        self._filter_timer.stop()
        try:
            from ..core.event_bus import EventBus
            EventBus.instance().unsubscribe("var/updated", self._on_var_updated)
            EventBus.instance().unsubscribe("wave/live_block", self._on_live_block)
        except Exception:
            pass

    @staticmethod
    def _empty_label(text):
        label = QLabel(text)
        label.setObjectName("empty_state")
        label.setAlignment(Qt.AlignCenter)
        label.setWordWrap(True)
        return label

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 14, 16, 14)
        outer.setSpacing(10)

        header = PageHeader(
            "波形分析", "多通道实时观测 · 25 μs 高速录波 · 无损 Live")
        self._channel_badge = StatusBadge()
        self._channel_badge.set_status("0 通道")
        header.add_widget(self._channel_badge)
        outer.addWidget(header)

        display_bar = QFrame()
        display_bar.setObjectName("control_bar")
        display = QHBoxLayout(display_bar)
        display.setContentsMargins(10, 7, 10, 7)
        display.setSpacing(9)
        self._pause_btn = QPushButton("暂停")
        self._pause_btn.setCheckable(True)
        self._pause_btn.setToolTip("暂停或恢复波形显示")
        self._pause_btn.toggled.connect(self._on_pause)
        display.addWidget(self._pause_btn)
        self._clear_btn = QPushButton("清空数据")
        self._clear_btn.setToolTip("清空所有通道的显示缓冲，不移除通道")
        self._clear_btn.clicked.connect(lambda: self._plot.clear_data())
        display.addWidget(self._clear_btn)
        display.addSpacing(4)
        self._autoscale = QCheckBox("自动量程")
        self._autoscale.setChecked(True)
        self._autoscale.toggled.connect(lambda checked: self._plot.set_autoscale(checked))
        display.addWidget(self._autoscale)
        window_label = QLabel("时间窗")
        window_label.setObjectName("dim")
        display.addWidget(window_label)
        self._window = QDoubleSpinBox()
        self._window.setRange(1, 120)
        self._window.setValue(10)
        self._window.setSuffix(" s")
        self._window.setFixedWidth(90)
        self._window.setToolTip("波形显示的时间范围")
        self._window.valueChanged.connect(self._on_window)
        display.addWidget(self._window)
        display.addStretch(1)
        self._export_btn = QPushButton("导出 CSV")
        self._export_btn.setToolTip("导出当前时间窗内的全部原始采样值")
        self._export_btn.clicked.connect(self._on_export)
        display.addWidget(self._export_btn)
        outer.addWidget(display_bar)

        record_bar = QFrame()
        record_bar.setObjectName("control_bar")
        record_layout = QVBoxLayout(record_bar)
        record_layout.setContentsMargins(10, 7, 10, 7)
        record_layout.setSpacing(6)
        config_row = QHBoxLayout()
        config_row.setSpacing(8)
        capture_label = QLabel("高速采集")
        capture_label.setObjectName("strong")
        config_row.addWidget(capture_label)
        config_row.addSpacing(4)
        config_row.addWidget(QLabel("点数"))
        self._record_points = QSpinBox()
        self._record_points.setRange(256, 32768)
        self._record_points.setSingleStep(256)
        self._record_points.setValue(2048)
        self._record_points.setFixedWidth(90)
        self._record_points.setToolTip("每个通道的录波点数")
        config_row.addWidget(self._record_points)
        config_row.addWidget(QLabel("采样点"))
        self._record_tap = QComboBox()
        self._record_tap.addItem("控制结束", 1)
        self._record_tap.addItem("ADC 就绪", 0)
        self._record_tap.setMinimumWidth(100)
        config_row.addWidget(self._record_tap)
        config_row.addWidget(QLabel("模式"))
        self._record_mode = QComboBox()
        self._record_mode.addItem("立即", 0)
        self._record_mode.addItem("前触发", 1)
        self._record_mode.setMinimumWidth(82)
        config_row.addWidget(self._record_mode)
        self._pretrigger_percent = QSpinBox()
        self._pretrigger_percent.setRange(0, 95)
        self._pretrigger_percent.setValue(50)
        self._pretrigger_percent.setSuffix(" % 前")
        self._pretrigger_percent.setFixedWidth(88)
        self._pretrigger_percent.setToolTip("前触发模式下，触发点之前保留的比例")
        config_row.addWidget(self._pretrigger_percent)
        config_row.addStretch(1)
        record_layout.addLayout(config_row)

        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        self._record_btn = QPushButton("25 μs 录波")
        self._record_btn.setObjectName("btn_primary")
        self._record_btn.setToolTip("启动一次高速录波，完成后自动下载数据")
        self._record_btn.clicked.connect(self._emit_record_request)
        action_row.addWidget(self._record_btn)
        self._trigger_btn = QPushButton("触发")
        self._trigger_btn.setEnabled(False)
        self._trigger_btn.setToolTip("为等待中的前触发录波提供软件触发")
        self._trigger_btn.clicked.connect(self.wave_trigger_requested.emit)
        action_row.addWidget(self._trigger_btn)
        self._live_btn = QPushButton("无损Live")
        self._live_btn.setCheckable(True)
        self._live_btn.setToolTip("启动或停止无损实时数据块上传")
        self._live_btn.toggled.connect(self._on_live_toggled)
        action_row.addWidget(self._live_btn)
        self._record_abort_btn = QPushButton("取消录波")
        self._record_abort_btn.setEnabled(False)
        self._record_abort_btn.clicked.connect(self.record_abort_requested.emit)
        action_row.addWidget(self._record_abort_btn)
        self._hint = QLabel("高速通道独立采集，不会混入慢速监控列表")
        self._hint.setObjectName("hint")
        self._hint.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self._hint.setToolTip(self._hint.text())
        action_row.addWidget(self._hint, 1)
        record_layout.addLayout(action_row)
        outer.addWidget(record_bar)
        self._record_bar = record_bar
        self._advanced_toggle = QPushButton("高级采集")
        self._advanced_toggle.setCheckable(True)
        self._advanced_toggle.setToolTip("展开或收起 25 μs 录波、触发和无损 Live 设置")
        display.insertWidget(display.count() - 1, self._advanced_toggle)
        record_bar.setVisible(False)
        self._advanced_toggle.toggled.connect(record_bar.setVisible)
        self._advanced_toggle.toggled.connect(lambda _checked: self._refresh_icons())

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        left = QWidget()
        left.setMinimumWidth(230)
        left.setMaximumWidth(320)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(10)

        avail_group = QGroupBox("变量库")
        avail_layout = QVBoxLayout(avail_group)
        self._search = QLineEdit()
        self._search.setProperty("role", "search")
        self._search.setPlaceholderText("搜索变量名或成员路径")
        self._search.setClearButtonEnabled(True)
        self._search_action = self._search.addAction(
            icon("search", ui_color("text_dim"), 16), QLineEdit.LeadingPosition)
        self._search.textChanged.connect(self._schedule_refilter)
        avail_layout.addWidget(self._search)
        self._avail_list = QListWidget()
        self._avail_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._avail_list.itemDoubleClicked.connect(lambda item: self._add_names([item.text()]))
        self._avail_empty = self._empty_label("暂无可选变量\n加载 ELF 或设备配置后即可添加")
        self._avail_stack = QStackedWidget()
        self._avail_stack.addWidget(self._avail_list)
        self._avail_stack.addWidget(self._avail_empty)
        avail_layout.addWidget(self._avail_stack, 1)
        self._add_btn = QPushButton("添加选中通道")
        self._add_btn.setObjectName("btn_primary")
        self._add_btn.clicked.connect(self._on_add_selected)
        avail_layout.addWidget(self._add_btn)
        left_layout.addWidget(avail_group, 1)

        channel_group = QGroupBox("当前通道")
        channel_layout = QVBoxLayout(channel_group)
        self._chan_list = QListWidget()
        self._chan_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._chan_empty = self._empty_label("还没有波形通道\n双击左侧变量即可添加")
        self._chan_stack = QStackedWidget()
        self._chan_stack.addWidget(self._chan_list)
        self._chan_stack.addWidget(self._chan_empty)
        channel_layout.addWidget(self._chan_stack, 1)
        self._remove_btn = QPushButton("移除选中通道")
        self._remove_btn.setObjectName("btn_ghost")
        self._remove_btn.clicked.connect(self._on_remove_selected)
        channel_layout.addWidget(self._remove_btn)
        left_layout.addWidget(channel_group, 1)
        splitter.addWidget(left)

        self._plot = RealtimePlotWidget(time_window=10.0)
        splitter.addWidget(self._plot)
        splitter.setSizes([260, 820])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        outer.addWidget(splitter, 1)
        self._refresh_icons()
        self._refilter()
        self._update_channel_state()

    def _refresh_icons(self):
        muted = ui_color("text_dim")
        primary = ui_color("primary")
        self._pause_btn.setIcon(icon(
            "play" if self._pause_btn.isChecked() else "pause",
            primary if self._pause_btn.isChecked() else muted, 16))
        self._clear_btn.setIcon(icon("clear", muted, 16))
        self._export_btn.setIcon(icon("export", muted, 16))
        self._advanced_toggle.setIcon(icon(
            "tuning", primary if self._advanced_toggle.isChecked() else muted, 16))
        self._record_btn.setIcon(icon("clock", ui_color("on_primary"), 16))
        self._trigger_btn.setIcon(icon("play", muted, 16))
        self._live_btn.setIcon(icon(
            "stop" if self._live_running else "waveform",
            ui_color("danger") if self._live_running else muted, 16))
        self._add_btn.setIcon(icon("plus", ui_color("on_primary"), 16))
        self._remove_btn.setIcon(icon("remove", muted, 16))
        self._search_action.setIcon(icon("search", muted, 16))
        for row in range(self._chan_list.count()):
            item = self._chan_list.item(row)
            name = item.data(Qt.UserRole)
            color = self._plot.channel_color(name) or muted
            item.setIcon(icon("waveform", color, 15))
            item.setForeground(QColor(color))

    def apply_theme(self, theme_name=None):
        self._plot.apply_theme(theme_name)
        self._channel_badge.refresh_theme()
        self._refresh_icons()
        self._hint.setStyleSheet(f"color: {ui_color(self._hint_role, theme_name)};")

    def set_available_variables(self, names):
        self._available = list(dict.fromkeys(name for name in names if name))
        self._refilter()

    def _refilter(self):
        query = self._search.text().strip().lower()
        hits = [name for name in self._available if not query or query in name.lower()]
        self._avail_list.clear()
        self._avail_list.addItems(hits)
        if hits:
            self._avail_stack.setCurrentIndex(0)
        else:
            self._avail_empty.setText(
                f"没有匹配“{self._search.text().strip()}”的变量" if query
                else "暂无可选变量\n加载 ELF 或设备配置后即可添加")
            self._avail_stack.setCurrentIndex(1)

    def _schedule_refilter(self):
        self._filter_timer.start()

    def _on_add_selected(self):
        self._add_names([item.text() for item in self._avail_list.selectedItems()])

    def add_channels_external(self, names):
        self._add_names(names)

    def _add_names(self, names):
        added = []
        for name in names:
            if name and not self._plot.has_channel(name):
                color = self._plot.add_channel(name)
                item = QListWidgetItem(name)
                item.setData(Qt.UserRole, name)
                item.setToolTip(name)
                if color:
                    item.setForeground(QColor(color))
                    item.setIcon(icon("waveform", color, 15))
                self._chan_list.addItem(item)
                added.append(name)
        if added:
            self._update_channel_state()
            self.channels_added.emit(added)

    def _on_remove_selected(self):
        names = [item.data(Qt.UserRole) or item.text()
                 for item in self._chan_list.selectedItems()]
        for name in names:
            self._plot.remove_channel(name)
            for row in range(self._chan_list.count() - 1, -1, -1):
                item = self._chan_list.item(row)
                if (item.data(Qt.UserRole) or item.text()) == name:
                    self._chan_list.takeItem(row)
        if names:
            self._update_channel_state()
            self.channels_removed.emit(names)

    def _update_channel_state(self):
        count = self._chan_list.count()
        self._chan_stack.setCurrentIndex(0 if count else 1)
        self._channel_badge.set_status(
            f"{count} 通道", "info" if count else "neutral")

    def plotted_channels(self):
        return self._plot.channel_names()

    def _on_var_updated(self, event):
        if self._plot.has_channel(event.name):
            self._plot.add_sample(event.name, event.timestamp, event.phys_value)

    def _on_live_block(self, block):
        if not self._live_running:
            return
        if self._plot.has_channel(block.get("name", "")):
            self._plot.add_samples(
                block["name"], block["timestamps"], block["phys_values"])

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

    def _set_hint(self, text, role="text_dim"):
        self._hint_role = role
        if self._hint.text() != text:
            self._hint.setText(text)
        self._hint.setToolTip(text)
        self._hint.setStyleSheet(f"color: {ui_color(role)};")

    def set_record_status(self, text: str, busy: bool = False):
        self._set_hint(text, "warning" if busy else "text_dim")
        self._record_btn.setEnabled(not busy)
        self._record_abort_btn.setEnabled(busy)

    def set_trigger_enabled(self, enabled: bool):
        self._trigger_btn.setEnabled(bool(enabled))

    def set_live_status(self, text: str, running: bool):
        self._live_running = bool(running)
        self._set_hint(text, "primary" if running else "text_dim")
        self._live_btn.blockSignals(True)
        self._live_btn.setChecked(bool(running))
        self._live_btn.setText("停止Live" if running else "无损Live")
        self._live_btn.blockSignals(False)
        self._record_btn.setEnabled(not running)
        self._refresh_icons()

    def show_record_capture(self, decoded: dict):
        self._plot.clear_data()
        for name, values in decoded.items():
            self._plot.add_samples(
                name, values["timestamps"], values["phys_values"])

    def _on_pause(self, checked):
        self._plot.set_paused(checked)
        self._pause_btn.setText("继续" if checked else "暂停")
        self._refresh_icons()

    def _on_window(self, value):
        self._plot.set_time_window(float(value))

    def cleanup(self):
        self._cleanup()
        if hasattr(self._plot, "cleanup"):
            self._plot.cleanup()

    def _on_export(self):
        if not self._plot.channel_names():
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出波形数据", "scope.csv", "CSV (*.csv)")
        if path:
            self._plot.export_csv(path)
            self.export_completed.emit(path)
