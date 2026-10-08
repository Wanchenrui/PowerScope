"""serial_monitor_view.py — 串口监控视图（三栏 cockpit 布局）

布局（对应 concept-images/01 的设计意图）::

    QSplitter(Horizontal)
    ├─ 左 300px   连接配置（紧凑表单）+ 模拟模式 + 快捷命令
    ├─ 中 stretch 收发日志表格（时间 | 方向 | 长度 | 数据）
    │             + 底部固定发送条（输入框 + 发送 + 定时发送）
    └─ 右 260px   连接状态 + 收发统计 + 系统消息

相比旧的「四段等权竖堆」：旧布局把上半屏让给两张表单，日志区只剩 ~300px；
新布局让日志（这个页面名以上的功能）拿到主面积，配置与统计退到侧栏。

日志用 QTableView + QAbstractTableModel（环形缓冲 5000 行）而不是
QTextEdit.append(HTML)：
  - 有独立的「长度」列 —— 排帧时第一眼要看的；
  - RX/TX 行底色区分，扫一屏就能找到发送帧；
  - QSortFilterProxyModel 提供过滤，长会话可定位；
  - 自动滚动锁：用户上翻看历史时新数据不再把视口顶回底部；
  - 系统消息移到右侧独立小日志，不再和数据混在一起。

委托关系不变：所有串口操作经 session_controller（SessionController）；
无 session_controller 时回退到旧的直接操作串口模式。
"""
from __future__ import annotations

import time
from collections import deque

from PySide6.QtCore import (
    QAbstractTableModel, QModelIndex, Qt, QSortFilterProxyModel, QTimer, Signal,
)
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QGridLayout, QGroupBox, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QPlainTextEdit, QPushButton,
    QScrollBar, QSpinBox, QSplitter, QStackedWidget, QTableView, QVBoxLayout,
    QWidget,
)

from .theme import font_size, ui_color
from .widgets.connect_button import ConnectButton
from .widgets.empty_state import EmptyState
from .widgets.gauge import LedIndicator
from .widgets.hex_highlighter import HexHighlighter, parse_hex_lines
from .widgets.history_line_edit import HistoryLineEdit
from .widgets.icon_button import IconButton

#: 日志环形缓冲容量（行）
LOG_CAPACITY = 5000
#: 系统消息缓冲容量（行）
SYSLOG_CAPACITY = 300


# ═══════════════════════════════════════════════════════════════
# 日志表格模型
# ═══════════════════════════════════════════════════════════════

class SerialLogModel(QAbstractTableModel):
    """收发日志的环形缓冲表模型。列：时间 | 方向 | 长度 | 数据。"""

    HEADERS = ("时间", "方向", "长度", "数据")
    COL_TIME, COL_DIR, COL_LEN, COL_DATA = range(4)

    def __init__(self, capacity: int = LOG_CAPACITY, parent=None):
        super().__init__(parent)
        self._capacity = max(100, int(capacity))
        self._rows: deque = deque(maxlen=self._capacity)

    # ---- Qt 模型接口 ----
    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return self.HEADERS[section] if 0 <= section < len(self.HEADERS) else None
        return str(section + 1)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None
        ts, direction, length, text = self._rows[index.row()]
        col = index.column()

        if role == Qt.DisplayRole:
            if col == self.COL_TIME:
                return ts
            if col == self.COL_DIR:
                return direction
            if col == self.COL_LEN:
                return str(length)
            if col == self.COL_DATA:
                return text
            return None

        if role == Qt.ForegroundRole:
            if col == self.COL_DIR:
                return QColor(ui_color("rx" if direction == "RX" else "tx"))
            return QColor(ui_color("text"))

        if role == Qt.BackgroundRole:
            # RX/TX 行底色：同色 10% 透明度，扫屏即可分区
            base = QColor(ui_color("rx" if direction == "RX" else "tx"))
            base.setAlpha(26)
            return base

        if role == Qt.TextAlignmentRole and col == self.COL_LEN:
            return int(Qt.AlignRight | Qt.AlignVCenter)

        if role == Qt.ToolTipRole and col == self.COL_DATA:
            return text
        return None

    # ---- 数据操作 ----
    def append(self, ts: str, direction: str, length: int, text: str):
        row = len(self._rows)
        self.beginInsertRows(QModelIndex(), row, row)
        self._rows.append((ts, direction, length, text))
        self.endInsertRows()

    def clear(self):
        if not self._rows:
            return
        self.beginResetModel()
        self._rows.clear()
        self.endResetModel()

    def row(self, index):
        """取第 index 行的原始元组（测试与调试用）。"""
        return self._rows[index] if 0 <= index < len(self._rows) else None

    def all_rows(self):
        return list(self._rows)


# ═══════════════════════════════════════════════════════════════
# 视图
# ═══════════════════════════════════════════════════════════════

class SerialMonitorView(QWidget):
    """串口监控视图: 配置 + 收发数据 + 发送区（三栏布局）"""

    data_sent = Signal(bytes)
    data_received = Signal(bytes)

    def __init__(self, parent=None, session_controller=None):
        super().__init__(parent)
        self._session = session_controller
        self._connected = False
        self._hex_display = True
        self._hex_send = True
        self._rx_count = 0
        self._tx_count = 0
        self._serial = None
        self._auto_scroll = True          # 自动跟随最新一行
        self._filter_text = ""
        # 快捷命令收藏夹（P1-8）：JSON 持久化，可增删改
        from ..core.quick_commands import QuickCommandStore
        self._quick_store = QuickCommandStore()
        self._quick_buttons = []
        # 多行序列发送（P1-9）
        self._sequence_frames = []
        self._sequence_index = 0
        self._sequence_timer = QTimer(self)
        self._sequence_timer.timeout.connect(self._send_next_sequence_frame)
        # 显示合并冲刷: 行进缓冲，下一事件循环回合一次性 insert
        # (避免高频 RX 每包一次 beginInsertRows 打爆表格)
        self._pending: deque = deque()
        self._rx_dirty = False
        self._tx_dirty = False
        self._flush_timer = QTimer(self)
        self._flush_timer.setSingleShot(True)
        self._flush_timer.setInterval(0)
        self._flush_timer.timeout.connect(self._flush_display)
        self._build_ui()
        self._setup_session_signals()

    # ------------------------------------------------------------------
    # 事件订阅
    # ------------------------------------------------------------------

    def _setup_session_signals(self):
        """连接 SessionController 的 data_sent / data_received 信号"""
        if self._session is not None:
            self._session.data_sent.connect(self._on_data_sent)
            self._session.data_received.connect(self._on_data_received)
            from ..core.event_bus import EventBus
            EventBus.instance().subscribe("connection/state", self._on_connection_state_event)
            self.destroyed.connect(self._unsubscribe_events)

    def _unsubscribe_events(self):
        try:
            from ..core.event_bus import EventBus
            EventBus.instance().unsubscribe("connection/state", self._on_connection_state_event)
        except Exception:
            pass

    def _on_connection_state_event(self, event):
        """EventBus connection/state → 同步连接 UI（连接中 → 已连接/失败）"""
        state = getattr(event, "state", "")
        if state == "connected":
            self.set_connected(True)
            info = event.info or (
                "模拟模式" if getattr(event, "transport_type", "") == "mock" else "")
            if info:
                self._set_status(f"已连接 ({info})", "ok")
        elif state == "error":
            self.set_connected(False)
            self._set_status("连接中断", "err")
            self._set_status_tip(getattr(event, "info", "") or "")
        elif state == "disconnected":
            self.set_connected(False)
            self._set_status_tip("")
        # "connecting" → 保持「连接中...」中间态，由后续事件恢复

    # ------------------------------------------------------------------
    # UI 构建
    # ------------------------------------------------------------------

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._build_left_panel())
        splitter.addWidget(self._build_center_panel())
        splitter.addWidget(self._build_right_panel())
        splitter.setSizes([300, 700, 250])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        outer.addWidget(splitter)

        self._repeat_timer = QTimer(self)
        self._repeat_timer.timeout.connect(self._on_send)

    # ---- 左栏：连接配置 + 快捷命令 ----
    def _build_left_panel(self):
        panel = QWidget()
        panel.setMinimumWidth(268)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        # ── 连接配置 ──
        config_group = QGroupBox("串口配置")
        form = QGridLayout(config_group)
        form.setHorizontalSpacing(6)
        form.setVerticalSpacing(6)
        # 两个下拉列平分剩余宽度：不加 stretch 时最后一列会被压到内容宽，
        # 校验项显示成 "Nor"、停止位显示成 "1"
        form.setColumnStretch(1, 1)
        form.setColumnStretch(3, 1)

        form.addWidget(QLabel("端口:"), 0, 0)
        self._port_combo = QComboBox()
        self._port_combo.setEditable(True)
        self._refresh_ports()
        form.addWidget(self._port_combo, 0, 1, 1, 2)

        refresh_btn = QPushButton("刷新")
        refresh_btn.setToolTip("重新枚举系统串口")
        refresh_btn.clicked.connect(self._refresh_ports)
        form.addWidget(refresh_btn, 1, 0, 1, 3)

        form.addWidget(QLabel("波特率:"), 2, 0)
        self._baud_combo = QComboBox()
        self._baud_combo.addItems(
            ["9600", "19200", "38400", "57600", "115200",
             "230400", "460800", "921600"])
        self._baud_combo.setCurrentText("115200")
        form.addWidget(self._baud_combo, 2, 1, 1, 2)

        form.addWidget(QLabel("数据位:"), 3, 0)
        self._data_bits = QComboBox()
        self._data_bits.addItems(["8", "7", "6", "5"])
        form.addWidget(self._data_bits, 3, 1)

        form.addWidget(QLabel("校验:"), 3, 2)
        self._parity = QComboBox()
        self._parity.addItems(["None", "Even", "Odd", "Mark", "Space"])
        form.addWidget(self._parity, 3, 3)

        form.addWidget(QLabel("停止位:"), 4, 0)
        self._stop_bits = QComboBox()
        self._stop_bits.addItems(["1", "1.5", "2"])
        form.addWidget(self._stop_bits, 4, 1, 1, 3)

        self._connect_btn = ConnectButton("连接")
        self._connect_btn.set_state("idle")
        self._connect_btn.setMinimumHeight(30)
        self._connect_btn.clicked.connect(self._on_connect)
        form.addWidget(self._connect_btn, 5, 0, 1, 4)
        lay.addWidget(config_group)

        # ── 模拟模式 ──
        self._sim_check = QCheckBox("模拟模式（无需真实设备）")
        self._sim_check.setChecked(False)   # 真机联调默认连接真实设备
        self._sim_check.setToolTip("使用内置模拟 MCU，可在无硬件时调试界面")
        self._sim_check.stateChanged.connect(self._on_sim_toggle)
        lay.addWidget(self._sim_check)

        # ── 快捷命令（P1-8：可增删改的收藏夹） ──
        quick_group = QGroupBox("快捷命令")
        quick_grid = QGridLayout(quick_group)
        quick_grid.setSpacing(6)
        self._quick_grid = quick_grid
        self._quick_buttons = []
        self._reload_quick_commands()
        # 管理入口常驻网格底部（row 20 与按钮网格不冲突）
        add_btn = IconButton("plus", "添加命令", tooltip="打开快捷命令编辑器")
        add_btn.clicked.connect(self._edit_quick_commands)
        quick_grid.addWidget(add_btn, 20, 0, 1, 2)
        lay.addWidget(quick_group)

        lay.addStretch(1)
        return panel

    # ---- 中栏：日志 + 发送条 ----
    def _build_center_panel(self):
        panel = QWidget()
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        # ── 工具栏：显示选项 + 过滤 + 清空 ──
        bar = QHBoxLayout()
        bar.setSpacing(6)

        # Hex / ASCII 分段控件（两个互斥可勾选按钮，比复选框更贴近示波器习惯）
        self._hex_rx_check = QPushButton("Hex")
        self._hex_rx_check.setCheckable(True)
        self._hex_rx_check.setChecked(True)
        self._hex_rx_check.setObjectName("seg_first")
        self._hex_rx_check.setToolTip("以十六进制显示数据")
        self._hex_rx_check.toggled.connect(self._on_hex_display_change)
        self._ascii_rx_check = QPushButton("ASCII")
        self._ascii_rx_check.setCheckable(True)
        self._ascii_rx_check.setChecked(False)
        self._ascii_rx_check.setObjectName("seg_last")
        self._ascii_rx_check.setToolTip("以 ASCII 文本显示数据")
        self._ascii_rx_check.toggled.connect(self._on_ascii_display_change)
        bar.addWidget(self._hex_rx_check)
        bar.addWidget(self._ascii_rx_check)

        self._timestamp_check = QCheckBox("时间戳")
        self._timestamp_check.setChecked(True)
        bar.addWidget(self._timestamp_check)

        self._direction_check = QCheckBox("方向")
        self._direction_check.setChecked(True)
        bar.addWidget(self._direction_check)

        bar.addStretch(1)

        self._filter_edit = QLineEdit()
        self._filter_edit.setPlaceholderText("过滤数据内容…")
        self._filter_edit.setClearButtonEnabled(True)
        self._filter_edit.setMaximumWidth(220)
        self._filter_edit.textChanged.connect(self._on_filter_changed)
        bar.addWidget(self._filter_edit)

        self._auto_scroll_check = QCheckBox("自动滚动")
        self._auto_scroll_check.setChecked(True)
        self._auto_scroll_check.setToolTip("关闭后上翻看历史时不会被新数据顶回底部")
        self._auto_scroll_check.toggled.connect(self._on_auto_scroll_toggled)
        bar.addWidget(self._auto_scroll_check)

        clear_btn = QPushButton("清空")
        clear_btn.setToolTip("清空收发日志与计数")
        clear_btn.clicked.connect(self._clear_display)
        bar.addWidget(clear_btn)
        lay.addLayout(bar)

        # ── 日志表格（空态 ↔ 表格）──
        self._log_model = SerialLogModel()
        self._proxy = QSortFilterProxyModel(self)
        self._proxy.setSourceModel(self._log_model)
        self._proxy.setFilterKeyColumn(SerialLogModel.COL_DATA)
        self._proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)

        self._log_table = QTableView()
        self._log_table.setModel(self._proxy)
        self._log_table.setObjectName("log_table")
        self._log_table.verticalHeader().setVisible(False)
        self._log_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._log_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._log_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._log_table.setAlternatingRowColors(False)
        self._log_table.setShowGrid(False)
        self._log_table.setWordWrap(False)
        self._log_table.setTextElideMode(Qt.ElideRight)
        self._log_table.verticalHeader().setDefaultSectionSize(20)
        header = self._log_table.horizontalHeader()
        header.setSectionResizeMode(SerialLogModel.COL_TIME, QHeaderView.Fixed)
        header.setSectionResizeMode(SerialLogModel.COL_DIR, QHeaderView.Fixed)
        header.setSectionResizeMode(SerialLogModel.COL_LEN, QHeaderView.Fixed)
        header.setSectionResizeMode(SerialLogModel.COL_DATA, QHeaderView.Stretch)
        self._log_table.setColumnWidth(SerialLogModel.COL_TIME, 92)
        self._log_table.setColumnWidth(SerialLogModel.COL_DIR, 44)
        self._log_table.setColumnWidth(SerialLogModel.COL_LEN, 52)
        # 双击把该行数据填进发送框（排帧时很方便）
        self._log_table.doubleClicked.connect(self._on_row_activated)

        self._log_stack = QStackedWidget()
        self._log_empty = EmptyState(
            "serial", "还没有串口数据",
            "选好端口与波特率后点左侧「连接」，收发数据会实时列在这里",
            action_text="去连接串口", action=self._on_connect)
        self._log_stack.addWidget(self._log_empty)
        self._log_stack.addWidget(self._log_table)
        self._log_stack.setCurrentIndex(0)
        lay.addWidget(self._log_stack, 1)

        # ── 底部固定发送条 ──
        send_bar = QHBoxLayout()
        send_bar.setSpacing(6)
        # ↑↓ 发送历史回溯（P1-9）：排帧时反复手搓同一帧是最高频浪费
        self._send_input = HistoryLineEdit()
        self._send_input.setPlaceholderText("输入要发送的数据（Hex 模式：A5 5A 01 02…，↑↓ 回顾历史）")
        self._send_input.setClearButtonEnabled(True)
        self._send_input.returnPressed.connect(self._on_send)
        send_bar.addWidget(self._send_input, 1)

        send_btn = IconButton("send", "发送")
        send_btn.setObjectName("btn_primary")
        send_btn.setMinimumWidth(76)
        send_btn.clicked.connect(self._on_send)
        send_bar.addWidget(send_btn)

        self._repeat_check = QCheckBox("定时发送")
        self._repeat_check.stateChanged.connect(self._on_repeat_toggle)
        send_bar.addWidget(self._repeat_check)

        self._repeat_interval = QSpinBox()
        self._repeat_interval.setRange(10, 60000)
        self._repeat_interval.setValue(1000)
        self._repeat_interval.setSuffix(" ms")
        self._repeat_interval.setToolTip("定时发送间隔")
        send_bar.addWidget(self._repeat_interval)
        lay.addLayout(send_bar)

        # ── 多行序列发送（P1-9）：每行一帧，按间隔连发；# 为注释 ──
        seq_group = QGroupBox("序列发送（每行一帧，# 注释）")
        seq_lay = QVBoxLayout(seq_group)
        seq_lay.setSpacing(4)
        self._sequence_edit = QPlainTextEdit()
        self._sequence_edit.setMaximumHeight(88)
        self._sequence_edit.setPlaceholderText(
            "A5 5A 01 07 01 00 00 00 00 00 00 00 7D 2F\n# 每行一帧，坏行会标红")
        self._sequence_highlighter = HexHighlighter(self._sequence_edit.document())
        self._sequence_highlighter.apply_theme()
        self._sequence_edit.textChanged.connect(self._refresh_sequence_status)
        seq_lay.addWidget(self._sequence_edit)
        seq_row = QHBoxLayout()
        seq_row.setSpacing(6)
        seq_row.addWidget(QLabel("间隔(ms):"))
        self._sequence_interval = QSpinBox()
        self._sequence_interval.setRange(10, 60000)
        self._sequence_interval.setValue(100)
        self._sequence_interval.setSuffix(" ms")
        seq_row.addWidget(self._sequence_interval)
        self._sequence_send_btn = IconButton("send", "发送全部")
        self._sequence_send_btn.clicked.connect(self._on_send_sequence)
        seq_row.addWidget(self._sequence_send_btn)
        self._sequence_stop_btn = IconButton("clear", "停止")
        self._sequence_stop_btn.setEnabled(False)
        self._sequence_stop_btn.clicked.connect(self._stop_sequence)
        seq_row.addWidget(self._sequence_stop_btn)
        self._sequence_status = QLabel("")
        self._sequence_status.setObjectName("dim")
        seq_row.addWidget(self._sequence_status, 1)
        seq_lay.addLayout(seq_row)
        lay.addWidget(seq_group)

        # ── 发送解析模式（与显示开关分开，避免一行控件语义混杂）──
        tx_row = QHBoxLayout()
        self._hex_tx_check = QCheckBox("以 Hex 解析输入")
        self._hex_tx_check.setChecked(True)
        tx_row.addWidget(self._hex_tx_check)
        tx_row.addStretch(1)
        lay.addLayout(tx_row)

        return panel

    # ---- 右栏：状态 + 统计 + 系统消息 ----
    def _build_right_panel(self):
        panel = QWidget()
        panel.setMinimumWidth(232)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        # ── 连接状态 ──
        status_group = QGroupBox("连接状态")
        sl = QVBoxLayout(status_group)
        row = QHBoxLayout()
        self._status_led = LedIndicator()
        self._status_label = QLabel("未连接")
        self._status_label.setProperty("role", "err")
        row.addWidget(self._status_led)
        row.addWidget(self._status_label, 1)
        sl.addLayout(row)
        lay.addWidget(status_group)

        # ── 收发统计 ──
        stats_group = QGroupBox("收发统计")
        form = QGridLayout(stats_group)
        form.setHorizontalSpacing(6)
        form.setVerticalSpacing(4)

        self._rx_label = QLabel("0 B")
        self._tx_label = QLabel("0 B")
        self._rate_label = QLabel("--")
        for lbl in (self._rx_label, self._tx_label, self._rate_label):
            lbl.setObjectName("value")
            # 字号走令牌，不内联写死（历史债：TYPOGRAPHY['size_md'] 直接拼字符串）
            lbl.setStyleSheet(f"font-size:{font_size('md')};")
        for i, (name, lbl) in enumerate((("RX 字节", self._rx_label),
                                        ("TX 字节", self._tx_label),
                                        ("RX 速率", self._rate_label))):
            key = QLabel(name)
            key.setObjectName("dim")
            form.addWidget(key, i, 0)
            form.addWidget(lbl, i, 1)
        form.setColumnStretch(1, 1)
        lay.addWidget(stats_group)

        # ── 系统消息（与数据分开，不再混进日志表格）──
        sys_group = QGroupBox("系统消息")
        sl2 = QVBoxLayout(sys_group)
        self._syslog = QPlainTextEdit()
        self._syslog.setObjectName("syslog")
        self._syslog.setReadOnly(True)
        self._syslog.setMaximumBlockCount(SYSLOG_CAPACITY)
        sl2.addWidget(self._syslog)
        lay.addWidget(sys_group, 1)
        return panel

    # ------------------------------------------------------------------
    # 快捷命令（P1-8：可增删改的收藏夹）
    # ------------------------------------------------------------------

    def ns800rt_quick_commands(self):
        """内置 NS800RT 调试黄金帧（首次使用/恢复默认时写入收藏夹）。"""
        from ..core.quick_commands import default_commands
        return [(c.name, c.display_hex()) for c in default_commands()]

    def _reload_quick_commands(self):
        """从收藏夹重建按钮（两列网格；常驻的「添加命令」不受影响）。"""
        for btn in list(self._quick_buttons):
            btn.deleteLater()
        self._quick_buttons.clear()
        commands = self._quick_store.load()
        for i, cmd in enumerate(commands):
            btn = QPushButton(cmd.name)
            btn.setMinimumHeight(28)
            btn.setToolTip(f"{cmd.display_hex()}\n{cmd.note}".strip())
            btn.clicked.connect(
                lambda checked=False, c=cmd.display_hex(): self._send_quick(c))
            self._quick_grid.addWidget(btn, i // 2, i % 2)
            self._quick_buttons.append(btn)

    def _edit_quick_commands(self):
        """打开快捷命令编辑器；保存后重建按钮。"""
        from .quick_command_editor import QuickCommandEditor
        editor = QuickCommandEditor(self._quick_store, parent=self)
        editor.saved.connect(lambda _cmds: self._reload_quick_commands())
        editor.exec()

    # ------------------------------------------------------------------
    # 多行序列发送（P1-9）
    # ------------------------------------------------------------------

    def _refresh_sequence_status(self):
        """边输入边报帧数/坏行数（高亮已逐行着色）。"""
        frames, errors = parse_hex_lines(self._sequence_edit.toPlainText())
        self._sequence_status.setText(
            f"{len(frames)} 帧可发" + (f" | {len(errors)} 行格式错误" if errors else ""))

    def _on_send_sequence(self):
        if not self._connected:
            self._log("⚠ 未连接设备，数据未发送（请先点「连接」）")
            return
        frames, errors = parse_hex_lines(self._sequence_edit.toPlainText())
        if errors:
            self._log(f"✗ 序列有 {len(errors)} 行格式错误（已标红），未发送")
            from .feedback import Feedback
            Feedback(self).toast(
                f"序列有 {len(errors)} 行格式错误，请先修正标红的行", "warning")
            return
        if not frames:
            self._log("⚠ 序列为空（每行一帧，# 开头为注释）")
            return
        self._sequence_frames = frames
        self._sequence_index = 0
        self._sequence_timer.start(self._sequence_interval.value())
        self._sequence_send_btn.setEnabled(False)
        self._sequence_stop_btn.setEnabled(True)
        self._log(f"→ 序列发送开始：{len(frames)} 帧，间隔 {self._sequence_interval.value()}ms")
        self._send_next_sequence_frame()

    def _send_next_sequence_frame(self):
        if self._sequence_index >= len(self._sequence_frames):
            self._stop_sequence("✓ 序列发送完成")
            return
        frame_hex = self._sequence_frames[self._sequence_index]
        self._sequence_index += 1
        try:
            data = bytes.fromhex(frame_hex)
        except ValueError:
            self._log(f"✗ 第 {self._sequence_index} 帧解析失败，已跳过")
            return
        if self._session is not None:
            try:
                self._session.write(data)
                self._log(f"→ 已发送 [{self._sequence_index}/{len(self._sequence_frames)}] "
                          f"{len(data)} 字节")
            except Exception as exc:
                self._log(f"✗ 发送失败: {exc}")
                self._stop_sequence("✗ 序列发送中断")
                return
        else:
            self._display_data(data, "TX")
            self._tx_count += len(data)
            self._tx_dirty = True
            self.data_sent.emit(data)

    def _stop_sequence(self, message: str | None = None):
        self._sequence_timer.stop()
        self._sequence_send_btn.setEnabled(True)
        self._sequence_stop_btn.setEnabled(False)
        if message:
            self._log(message)

    # ------------------------------------------------------------------
    # 帧配置持久化（AppSettings 接线）
    # ------------------------------------------------------------------

    def frame_settings(self) -> dict:
        """导出当前串口帧配置（界面文本形式，可直接回灌 apply_frame_settings）。"""
        return {
            "port": self._port_combo.currentText().strip(),
            "baudrate": self._baud_combo.currentText().strip(),
            "bytesize": self._data_bits.currentText().strip(),
            "parity": self._parity.currentText().strip(),
            "stopbits": self._stop_bits.currentText().strip(),
        }

    def apply_frame_settings(self, frame: dict) -> None:
        """按上次记录恢复串口帧配置；缺项/非法值保持原状。"""
        if not frame:
            return
        port = (frame.get("port") or "").strip()
        if port:
            if self._port_combo.findText(port) < 0:
                self._port_combo.setEditText(port)
            else:
                self._port_combo.setCurrentText(port)
        for combo, key in ((self._baud_combo, "baudrate"),
                           (self._data_bits, "bytesize"),
                           (self._parity, "parity"),
                           (self._stop_bits, "stopbits")):
            value = (frame.get(key) or "").strip()
            if value and combo.findText(value) >= 0:
                combo.setCurrentText(value)

    # ------------------------------------------------------------------
    # 连接 / 断开
    # ------------------------------------------------------------------

    def _on_connect(self):
        if self._connected:
            self._disconnect()
        else:
            self._connect()

    def _connect(self):
        if self._session is not None:
            self._connect_with_session()
        else:
            self._connect_legacy()

    def _connect_with_session(self):
        """使用 SessionController 连接"""
        try:
            if self._sim_check.isChecked():
                self._session.connect_mock()
                self._update_ui_connected("模拟模式")
                self._log("✓ 模拟模式已启动 — 无需真实硬件即可调试界面")
                self._log("  模拟设备: STM32G474 @ 170MHz, 固件 v1.0.0")
                self._log("  可使用左侧「快捷命令」按钮发送调试帧")
            else:
                port_text = self._port_combo.currentText()
                port = port_text.split(" - ")[0] if " - " in port_text else port_text
                baudrate = int(self._baud_combo.currentText())
                bytesize = int(self._data_bits.currentText())
                parity = {"None": "N", "Even": "E", "Odd": "O",
                          "Mark": "M", "Space": "S"}.get(
                              self._parity.currentText(), "N")
                stopbits = float(self._stop_bits.currentText())
                # 中间态: 发起连接后先置「连接中...」并禁用，
                # 最终状态由 connection/state 事件(_on_connection_state_event)恢复
                self._connect_btn.set_state("connecting")
                self._session.connect_serial(
                    port, baudrate,
                    bytesize=bytesize, parity=parity, stopbits=stopbits)
                # connect_serial 内部捕获异常并发布 error 事件(不抛出)，
                # 同步结果直接落定；仍为 connecting 则等待事件恢复
                if self._session.is_connected:
                    self._update_ui_connected(f"{port} @ {baudrate}")
                    self._log(f"✓ 串口已连接: {port} @ {baudrate} baud")
                elif self._session.state == "error":
                    self._update_ui_disconnected()
                    self._log(f"✗ 连接失败: {self._session.state_info}")
        except Exception as e:
            self._update_ui_disconnected()
            # 不弹模态：模态会打断流式监控，且历史上正是模态嵌套导致栈溢出
            self._log(f"✗ 连接失败: {e}")
            from .feedback import Feedback
            Feedback(self).toast(f"连接失败: {e}", "error")

    def _connect_legacy(self):
        """向后兼容：直接操作串口"""
        if self._sim_check.isChecked():
            self._update_ui_connected("模拟模式")
            self._log("✓ 模拟模式已启动 — 无需真实硬件即可调试界面")
            self._log("  模拟设备: STM32G474 @ 170MHz, 固件 v1.0.0")
            self._log("  可使用左侧「快捷命令」按钮发送调试帧")
            self.data_received.emit(b"\xA5\x5A\x01\x07\x01\x00")
        else:
            try:
                import serial
                port_text = self._port_combo.currentText()
                port = port_text.split(" - ")[0] if " - " in port_text else port_text
                baudrate = int(self._baud_combo.currentText())
                self._serial = serial.Serial(
                    port, baudrate,
                    bytesize=int(self._data_bits.currentText()),
                    parity={
                        "None": serial.PARITY_NONE, "Even": serial.PARITY_EVEN,
                        "Odd": serial.PARITY_ODD, "Mark": serial.PARITY_MARK,
                        "Space": serial.PARITY_SPACE,
                    }.get(self._parity.currentText(), serial.PARITY_NONE),
                    stopbits=float(self._stop_bits.currentText()),
                    timeout=0.1
                )
                self._update_ui_connected(f"{port} @ {baudrate}")
                self._log(f"✓ 串口已连接: {port} @ {baudrate} baud")
                self._rx_timer = QTimer()
                self._rx_timer.timeout.connect(self._poll_serial)
                self._rx_timer.start(50)
            except Exception as e:
                # 同上：不弹模态，走系统消息 + Toast
                self._log(f"✗ 连接失败: {e}")
                from .feedback import Feedback
                Feedback(self).toast(f"无法打开串口: {e}", "error")

    def _disconnect(self):
        if self._session is not None:
            self._session.disconnect()
        self._update_ui_disconnected()
        if self._serial:
            self._serial.close()
            self._serial = None
        if hasattr(self, '_rx_timer'):
            self._rx_timer.stop()
        self._log("✓ 已断开连接")

    def _update_ui_connected(self, info):
        self.set_connected(True)
        self._set_status(f"已连接 ({info})", "ok")

    def _update_ui_disconnected(self):
        self.set_connected(False)

    def _set_status(self, text: str, role: str = "dim"):
        """更新右栏连接状态（LED + 文字 + 语义角色色）。"""
        self._status_label.setText(text)
        self._status_label.setProperty("role", None if role == "dim" else role)
        self._status_label.style().unpolish(self._status_label)
        self._status_label.style().polish(self._status_label)
        self._status_led.set_on(role == "ok")

    def _set_status_tip(self, tip: str):
        self._status_label.setToolTip(tip)

    def update_rate(self, bytes_per_second: float):
        """刷新 RX 速率显示（由主窗口 500ms 统计定时器调用）。"""
        if bytes_per_second and bytes_per_second > 0:
            self._rate_label.setText(f"{_fmt_bytes(int(bytes_per_second))}/s")
        else:
            self._rate_label.setText("--")

    def set_connected(self, connected: bool):
        """同步连接状态到 UI: 按钮文本/样式 + 状态标签 + 使能"""
        self._connected = connected
        self._connect_btn.setEnabled(True)
        if connected:
            self._connect_btn.set_state("connected", "断开")
            self._set_status("已连接", "ok")
        else:
            self._connect_btn.set_state("idle", "连接")
            self._set_status("未连接", "err")

    # ------------------------------------------------------------------
    # 数据收发
    # ------------------------------------------------------------------

    def _on_send(self):
        text = self._send_input.text().strip()
        if not text:
            self._log("⚠ 请输入要发送的数据")
            return

        if self._hex_tx_check.isChecked():
            try:
                clean = text.replace(" ", "").replace("\n", "")
                data = bytes.fromhex(clean)
            except ValueError:
                self._log("✗ Hex 格式错误（示例：A5 5A 01 02）")
                from .feedback import Feedback
                Feedback(self).toast("Hex 数据格式不正确，请输入如: A5 5A 01 02",
                                     "warning")
                return
        else:
            data = text.encode('ascii', errors='replace')

        if not self._connected:
            self._log("⚠ 未连接设备，数据未发送（请先点「连接」）")
            return

        # 进入发送历史（↑↓ 可回溯，P1-9）
        self._send_input.push_history(text)

        if self._session is not None:
            try:
                self._session.write(data)
                self._log(f"→ 已发送 {len(data)} 字节")
                if self._sim_check.isChecked():
                    QTimer.singleShot(100, lambda: self._simulate_response(data))
            except Exception as e:
                self._log(f"✗ 发送失败: {e}")
        else:
            if self._sim_check.isChecked():
                self._display_data(data, "TX")
                self._tx_count += len(data)
                self._tx_dirty = True
                self.data_sent.emit(data)
                QTimer.singleShot(100, lambda: self._simulate_response(data))
            else:
                if self._serial:
                    try:
                        self._serial.write(data)
                        self._display_data(data, "TX")
                        self._tx_count += len(data)
                        self._tx_dirty = True
                        self.data_sent.emit(data)
                    except Exception as e:
                        self._log(f"✗ 发送失败: {e}")

    def _on_data_sent(self, data: bytes):
        """SessionController 发送数据后触发 — 更新 TX 显示"""
        self._tx_count += len(data)
        self._tx_dirty = True   # 标签随合并冲刷统一刷新，不每包 setText
        self._display_data(data, "TX")
        self.data_sent.emit(data)

    def _on_data_received(self, data: bytes):
        """SessionController 收到数据后触发 — 更新 RX 显示"""
        self._rx_count += len(data)
        self._rx_dirty = True
        self._display_data(data, "RX")
        self.data_received.emit(data)

    def _format_payload(self, data: bytes) -> str:
        """按当前显示模式格式化一帧的载荷（Hex / ASCII）。"""
        if self._hex_display:
            return " ".join(f"{b:02X}" for b in data)
        return data.decode('ascii', errors='replace')

    def _display_data(self, data: bytes, direction: str):
        """把一帧数据入缓冲（保留 Hex/时间戳/方向 格式逻辑）。"""
        # 首次有收发数据才离开空态；_log() 之类的系统消息不触发
        if self._log_stack.currentIndex() == 0:
            self._log_stack.setCurrentIndex(1)
        ts = time.strftime("%H:%M:%S.") + f"{int(time.time() * 1000) % 1000:03d}"
        self._pending.append((ts, direction, len(data), self._format_payload(data)))
        if not self._flush_timer.isActive():
            self._flush_timer.start()

    def _flush_display(self):
        """合并冲刷: 缓冲的行一次性 insert，RX/TX 计数统一刷新。"""
        if self._pending:
            for row in self._pending:
                self._log_model.append(*row)
            self._pending.clear()
            self._maybe_scroll_to_bottom()
        if self._rx_dirty:
            self._rx_label.setText(_fmt_bytes(self._rx_count))
            self._rx_dirty = False
        if self._tx_dirty:
            self._tx_label.setText(_fmt_bytes(self._tx_count))
            self._tx_dirty = False

    def _maybe_scroll_to_bottom(self):
        """仅在开启自动滚动、且用户本就停在底部时才跟随。"""
        if not self._auto_scroll:
            return
        bar = self._log_table.verticalScrollBar()
        if bar is not None and bar.value() < bar.maximum() - 4:
            return    # 用户正在看历史，不抢视口
        self._log_table.scrollToBottom()

    def _on_row_activated(self, index):
        """双击某行 → 把该行数据填进发送框（排帧时很方便）。"""
        if not index.isValid():
            return
        src = self._proxy.mapToSource(index)
        row = self._log_model.row(src.row())
        if row and self._hex_display:
            self._send_input.setText(row[3])

    def _on_hex_display_change(self, checked):
        self._hex_display = bool(checked)
        if checked:
            self._ascii_rx_check.blockSignals(True)
            self._ascii_rx_check.setChecked(False)
            self._ascii_rx_check.blockSignals(False)

    def _on_ascii_display_change(self, checked):
        if checked:
            self._hex_rx_check.blockSignals(True)
            self._hex_rx_check.setChecked(False)
            self._hex_rx_check.blockSignals(False)
            self._hex_display = False
        else:
            self._hex_display = True

    def _on_filter_changed(self, text):
        self._filter_text = text.strip()
        self._proxy.setFilterFixedString(self._filter_text)

    def _on_auto_scroll_toggled(self, checked):
        self._auto_scroll = bool(checked)
        if self._auto_scroll:
            self._log_table.scrollToBottom()

    # ------------------------------------------------------------------
    # 模拟响应
    # ------------------------------------------------------------------

    def _simulate_response(self, request: bytes):
        if len(request) < 4:
            return
        if request[0] == 0xA5 and request[1] == 0x5A:
            cmd = request[3] if len(request) > 3 else 0
            if cmd == 0x07:
                resp = bytes([0xA5, 0x5A, 0x01, 0x07, request[4], request[5], 0x00, 0x3C, 0x00])
                resp += b"STM32G474" + b"\x00" * 23
                resp += (170000000).to_bytes(4, 'little')
                resp += (0x12345678).to_bytes(4, 'little')
                resp += (0x0001).to_bytes(2, 'little')
                resp += b"1.0.0" + b"\x00" * 11
                from ..core.cffi_loader import CRC16
                crc = CRC16.calc(resp)
                resp += crc.to_bytes(2, 'little')
                self._on_data_received(resp)
                self._log("← 收到设备信息响应 (STM32G474, 170MHz, v1.0.0)")
            elif cmd == 0x08:
                resp = bytes([0xA5, 0x5A, 0x01, 0x08, request[4], request[5], 0x00, 0x00, 0x00])
                from ..core.cffi_loader import CRC16
                crc = CRC16.calc(resp)
                resp += crc.to_bytes(2, 'little')
                self._on_data_received(resp)
                self._log("← 参数写入成功 (模拟)")

    # ------------------------------------------------------------------
    # 轮询（仅旧模式使用）
    # ------------------------------------------------------------------

    def _poll_serial(self):
        if not self._serial or not self._connected:
            return
        try:
            n = self._serial.in_waiting
            if n > 0:
                data = self._serial.read(n)
                if data:
                    self._on_data_received(data)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------

    def _refresh_ports(self):
        self._port_combo.clear()
        try:
            import serial.tools.list_ports
            ports = serial.tools.list_ports.comports()
            if ports:
                for p in ports:
                    self._port_combo.addItem(f"{p.device} - {p.description}")
            else:
                self._port_combo.addItem("COM1")
                self._log("未检测到串口设备，已填入默认 COM1")
        except Exception:
            self._port_combo.addItem("COM1")
            self._log("无法枚举串口（pyserial 未安装？），已填入默认 COM1")

    @staticmethod
    def ns800rt_quick_commands():
        """生成带正确 CRC 的 NS800RT 调试黄金帧（供快捷按钮）。

        命令码与固件 debug_monitor 对齐：GET_INFO=0x07、STOP_STREAM=0x06、
        DEVICE_CONTROL=0x0C(payload 01=开机/00=关机)。每帧均含正确 CRC16-Modbus。
        """
        from ..core.cffi_loader import DebugProtocol as _DP

        def hx(b):
            return _DP.build_frame(*b).hex(" ").upper()

        return [
            ("读设备信息", hx((0x07, 1, 0, b""))),
            ("停止采样", hx((0x06, 1, 0, b"\x00"))),
            ("关机", hx((0x0C, 1, 0, b"\x00"))),
            ("开机", hx((0x0C, 1, 0, b"\x01"))),
        ]

    def _send_quick(self, hex_cmd: str):
        self._send_input.setText(hex_cmd)
        self._on_send()

    def _on_sim_toggle(self):
        if self._sim_check.isChecked():
            self._log("已切换到模拟模式 — 无需真实设备")
        else:
            self._log("已切换到真实串口模式 — 需要连接硬件设备")

    def _on_repeat_toggle(self):
        if self._repeat_check.isChecked():
            self._repeat_timer.start(self._repeat_interval.value())
            self._log(f"定时发送已启动，间隔 {self._repeat_interval.value()}ms")
        else:
            self._repeat_timer.stop()
            self._log("定时发送已停止")

    def _clear_display(self):
        self._pending.clear()      # 丢弃未冲刷的行，避免清空后又被刷回
        self._rx_dirty = False
        self._tx_dirty = False
        self._log_model.clear()
        self._log_stack.setCurrentIndex(0)
        self._rx_count = 0
        self._tx_count = 0
        self._rx_label.setText("0 B")
        self._tx_label.setText("0 B")
        self._syslog.clear()
        self._log("显示已清空")

    def _log(self, msg: str):
        """系统消息 → 右栏独立小日志（不再和数据混进同一块区域）。"""
        if not hasattr(self, '_syslog') or self._syslog is None:
            return
        ts = time.strftime("%H:%M:%S")
        self._syslog.appendHtml(
            f'<span style="color:{ui_color("user")};">[{ts}]</span> '
            f'<span style="color:{ui_color("text_dim")};">{_escape(msg)}</span>')

    # ------------------------------------------------------------------
    # 测试 / 调试辅助
    # ------------------------------------------------------------------

    def log_rows(self):
        """当前日志全部行 [(时间, 方向, 长度, 数据), ...]（测试与调试用）。"""
        return self._log_model.all_rows()

    def log_text(self) -> str:
        """日志的纯文本形式（兼容旧的 _display.toPlainText() 读法）。"""
        return "\n".join(
            f"{ts} {d} {n} {t}" for ts, d, n, t in self._log_model.all_rows())

    # ------------------------------------------------------------------
    # 主题 / 工作区快照
    # ------------------------------------------------------------------

    def apply_theme(self, theme_name=None):
        """主题切换：序列编辑器 highlighter 重新解析语义色。"""
        if hasattr(self, "_sequence_highlighter"):
            self._sequence_highlighter.apply_theme(theme_name)

    def serial_splitter(self):
        return self.findChild(QSplitter)

    def collect_workspace(self) -> dict:
        """导出本页可恢复状态：发送框文本 + 序列脚本 + 帧配置。"""
        return {
            "send_input": self._send_input.text(),
            "sequence_text": (self._sequence_edit.toPlainText()
                              if hasattr(self, "_sequence_edit") else ""),
            "serial_frame": self.frame_settings(),
        }

    def restore_workspace(self, data: dict) -> None:
        send_input = data.get("send_input", "")
        if send_input:
            self._send_input.setText(send_input)
        sequence = data.get("sequence_text", "")
        if sequence and hasattr(self, "_sequence_edit"):
            self._sequence_edit.setPlainText(sequence)
        frame = data.get("serial_frame") or {}
        if frame:
            self.apply_frame_settings(frame)


# ═══════════════════════════════════════════════════════════════
# 模块级助手
# ═══════════════════════════════════════════════════════════════

def _fmt_bytes(n: int) -> str:
    """字节数人类可读化（2048 → 2.0 KB）。"""
    if n >= 1024 * 1024:
        return f"{n / 1024 / 1024:.1f} MB"
    if n >= 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n} B"


def _escape(text) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))
