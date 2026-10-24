"""变量查看视图 — ELF 变量树 + 在线读写"""
import struct
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QGroupBox,
    QTreeWidget, QTreeWidgetItem, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QLineEdit, QFileDialog, QMessageBox,
    QHeaderView, QDoubleSpinBox, QDialog, QFormLayout, QComboBox,
    QDialogButtonBox, QAbstractItemView
)
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QColor
from .theme import ui_color


class VariableInspectorView(QWidget):
    """变量查看器: 加载ELF → 变量树 → 在线读写"""

    elf_loading = Signal()
    plot_requested = Signal(list)   # list[dict]: {name,address,size,type_name}

    def __init__(self, profile=None, parent=None):
        super().__init__(parent)
        self._profile = profile
        self._elf_parser = None
        self._elf_load_token = object()
        self._connected = False
        self._all_variables = []
        self._debug = None
        self._watch_rows = {}
        self._pending_watch_values = {}
        self._updated_this_frame = set()
        self._filter_timer = QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(200)
        self._filter_timer.timeout.connect(
            lambda: self._apply_filter(self._search_input.text()))
        self._watch_flush_timer = QTimer(self)
        self._watch_flush_timer.setSingleShot(True)
        self._watch_flush_timer.setInterval(33)
        self._watch_flush_timer.timeout.connect(self._flush_watch_values)
        self._build_ui()
        self._subscribe_events()
        self.destroyed.connect(self._cleanup)

    def set_profile(self, profile):
        self._elf_load_token = object()
        self._profile = profile
        if self._elf_parser is not None:
            self._elf_parser.close()
        self._elf_parser = None
        self._on_clear_watch()
        self._populate_tree([])

    def set_control_check(self, check):
        self._control_check = check

    def _subscribe_events(self):
        from ..core.event_bus import EventBus
        EventBus.instance().subscribe("var/updated", self._on_var_updated)

    def _on_var_updated(self, event):
        if event.name not in self._watch_rows:
            return
        text = f"{event.phys_value:.2f} {event.unit}"
        if event.name in self._updated_this_frame:
            self._pending_watch_values[event.name] = text
        else:
            self._updated_this_frame.add(event.name)
            self._set_watch_value(event.name, text)
        if not self._watch_flush_timer.isActive():
            self._watch_flush_timer.start()
        if getattr(event, "source", "") != "stream":
            self._log(f"← {event.name} = {event.phys_value:.2f} {event.unit}")

    def _set_watch_value(self, name, text):
        row = self._watch_rows.get(name)
        if row is None:
            return
        item = self._watch_table.item(row, 3)
        if item is not None and item.text() != text:
            item.setText(text)
            item.setForeground(QColor(ui_color("success")))

    def _flush_watch_values(self):
        pending = self._pending_watch_values
        self._pending_watch_values = {}
        self._updated_this_frame.clear()
        for name, text in pending.items():
            self._set_watch_value(name, text)

    def _cleanup(self):
        try:
            self._filter_timer.stop()
            self._watch_flush_timer.stop()
            from ..core.event_bus import EventBus
            EventBus.instance().unsubscribe("var/updated", self._on_var_updated)
        except Exception:
            pass
        if self._elf_parser is not None:
            self._elf_parser.close()
            self._elf_parser = None

    def _build_ui(self):
        from PySide6.QtWidgets import QFrame, QSizePolicy, QStackedWidget
        from .widgets.icons import icon
        from .widgets.primitives import PageHeader, StatusBadge

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)
        header = PageHeader("变量监视", "ELF / DWARF 符号浏览 · 在线读取与受控写入")
        self._watch_badge = StatusBadge()
        header.add_widget(self._watch_badge)
        layout.addWidget(header)

        elf_bar = QFrame()
        elf_bar.setObjectName("control_bar")
        elf_layout = QHBoxLayout(elf_bar)
        elf_layout.setContentsMargins(10, 7, 10, 7)
        file_label = QLabel("固件")
        file_label.setObjectName("strong")
        elf_layout.addWidget(file_label)
        self._elf_path_label = QLabel("未加载")
        self._elf_path_label.setObjectName("dim")
        self._elf_path_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        elf_layout.addWidget(self._elf_path_label, 1)
        self._var_count_label = QLabel("变量 0")
        self._var_count_label.setObjectName("stat_value")
        elf_layout.addWidget(self._var_count_label)
        self._load_btn = QPushButton("加载 ELF")
        self._load_btn.setObjectName("btn_primary")
        self._load_btn.clicked.connect(self._on_load_elf)
        elf_layout.addWidget(self._load_btn)
        layout.addWidget(elf_bar)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        tree_group = QGroupBox("变量树 · 按源文件分组")
        tree_layout = QVBoxLayout(tree_group)
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("搜索变量名或结构体成员")
        self._search_input.setClearButtonEnabled(True)
        self._search_action = self._search_input.addAction(
            icon("search", ui_color("text_dim"), 16), QLineEdit.LeadingPosition)
        self._search_input.textChanged.connect(self._schedule_filter)
        tree_layout.addWidget(self._search_input)

        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["变量名", "类型", "地址", "大小"])
        self._tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        for column in (1, 2, 3):
            self._tree.header().setSectionResizeMode(column, QHeaderView.ResizeToContents)
        self._tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._tree.setUniformRowHeights(True)
        self._tree.itemDoubleClicked.connect(self._on_var_double_click)
        self._tree_empty = QLabel("尚未加载变量\n请先选择目标固件的 ELF 文件")
        self._tree_empty.setObjectName("empty_state")
        self._tree_empty.setAlignment(Qt.AlignCenter)
        self._tree_empty.setWordWrap(True)
        self._tree_stack = QStackedWidget()
        self._tree_stack.addWidget(self._tree)
        self._tree_stack.addWidget(self._tree_empty)
        tree_layout.addWidget(self._tree_stack, 1)

        button_row = QHBoxLayout()
        self._add_watch_btn = QPushButton("添加监视")
        self._add_watch_btn.setObjectName("btn_primary")
        self._add_watch_btn.clicked.connect(self._on_add_watch)
        button_row.addWidget(self._add_watch_btn)
        self._address_btn = QPushButton("按地址添加")
        self._address_btn.clicked.connect(self._on_add_address)
        button_row.addWidget(self._address_btn)
        self._refresh_vars_btn = QPushButton("刷新")
        self._refresh_vars_btn.clicked.connect(self._on_refresh_vars)
        button_row.addWidget(self._refresh_vars_btn)
        tree_layout.addLayout(button_row)
        splitter.addWidget(tree_group)

        watch_group = QGroupBox("在线监视表")
        watch_layout = QVBoxLayout(watch_group)
        action_row = QHBoxLayout()
        self._read_btn = QPushButton("读取选中")
        self._read_btn.clicked.connect(self._on_read_var)
        action_row.addWidget(self._read_btn)
        self._read_all_btn = QPushButton("全部读取")
        self._read_all_btn.clicked.connect(self._on_read_all)
        action_row.addWidget(self._read_all_btn)
        self._plot_btn = QPushButton("加入波形")
        self._plot_btn.setObjectName("btn_primary")
        self._plot_btn.clicked.connect(self._on_plot_selected)
        action_row.addWidget(self._plot_btn)
        self._clear_watch_btn = QPushButton("清空")
        self._clear_watch_btn.setObjectName("btn_ghost")
        self._clear_watch_btn.clicked.connect(self._on_clear_watch)
        action_row.addWidget(self._clear_watch_btn)
        action_row.addStretch(1)
        self._watch_count_label = QLabel("0 项")
        self._watch_count_label.setObjectName("stat_value")
        action_row.addWidget(self._watch_count_label)
        watch_layout.addLayout(action_row)

        self._watch_table = QTableWidget(0, 5)
        self._watch_table.setHorizontalHeaderLabels(["变量名", "类型", "地址", "当前值", "操作"])
        self._watch_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._watch_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self._watch_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self._watch_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self._watch_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self._watch_table.verticalHeader().setVisible(False)
        self._watch_table.setAlternatingRowColors(True)
        self._watch_table.setShowGrid(False)
        self._watch_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._watch_empty = QLabel("监视表为空\n双击左侧变量，或选中后点击“添加监视”")
        self._watch_empty.setObjectName("empty_state")
        self._watch_empty.setAlignment(Qt.AlignCenter)
        self._watch_empty.setWordWrap(True)
        self._watch_stack = QStackedWidget()
        self._watch_stack.addWidget(self._watch_table)
        self._watch_stack.addWidget(self._watch_empty)
        watch_layout.addWidget(self._watch_stack, 1)

        write_row = QHBoxLayout()
        write_row.addWidget(QLabel("写入值"))
        self._write_input = QLineEdit()
        self._write_input.setPlaceholderText("输入选中变量的新值")
        self._write_input.setClearButtonEnabled(True)
        write_row.addWidget(self._write_input, 1)
        self._write_btn = QPushButton("写入")
        self._write_btn.setObjectName("btn_warning")
        self._write_btn.clicked.connect(self._on_write_var)
        write_row.addWidget(self._write_btn)
        self._verify_btn = QPushButton("写入并校验")
        self._verify_btn.clicked.connect(self._on_write_verify)
        write_row.addWidget(self._verify_btn)
        watch_layout.addLayout(write_row)

        splitter.addWidget(watch_group)
        splitter.setSizes([490, 570])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, 1)

        self._log_label = QLabel("提示：加载 ELF 后，双击左侧变量即可添加到监视表")
        self._log_label.setObjectName("hint")
        self._log_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        layout.addWidget(self._log_label)
        self._populate_tree_hits([])
        self._refresh_icons()
        self._sync_watch_state()

    def _refresh_icons(self):
        from .widgets.icons import icon
        muted = ui_color("text_dim")
        self._load_btn.setIcon(icon("folder", ui_color("on_primary"), 16))
        self._add_watch_btn.setIcon(icon("plus", ui_color("on_primary"), 16))
        self._address_btn.setIcon(icon("variable", muted, 16))
        self._refresh_vars_btn.setIcon(icon("refresh", muted, 16))
        self._read_btn.setIcon(icon("refresh", muted, 16))
        self._read_all_btn.setIcon(icon("refresh", muted, 16))
        self._plot_btn.setIcon(icon("waveform", ui_color("on_primary"), 16))
        self._clear_watch_btn.setIcon(icon("clear", muted, 16))
        self._write_btn.setIcon(icon("send", ui_color("warning"), 16))
        self._verify_btn.setIcon(icon("success", muted, 16))
        self._search_action.setIcon(icon("search", muted, 16))

    def apply_theme(self, theme_name=None):
        self._refresh_icons()
        self._watch_badge.refresh_theme()
        if self._all_variables:
            from ..debug.elf_parser import filter_variables
            self._populate_tree_hits(filter_variables(
                self._all_variables, self._search_input.text()))

    def _on_load_elf(self):
        """交互选择并加载 ELF 文件。"""
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 ELF 固件文件", "",
            "ELF 文件 (*.elf *.axf *.out);;所有文件 (*)")
        if path:
            self.load_elf(path)

    def load_elf(self, path: str, show_error: bool = True) -> bool:
        """加载指定 ELF；供 profile 自动加载与手动选择共用。"""
        self._elf_load_token = object()
        if self._elf_parser is not None:
            self._elf_parser.close()
            self._elf_parser = None
        self._on_clear_watch()
        self._populate_tree([])
        self.elf_loading.emit()
        parser = None
        try:
            from ..debug.elf_parser import ELFParser
            parser = ELFParser(path)
            variables = parser.parse_variables()
            old_parser = self._elf_parser
            self._elf_parser = parser
            if old_parser is not None:
                old_parser.close()
            self._elf_path_label.setText(path)
            self._elf_path_label.setProperty("role", "ok")
            self._elf_path_label.style().unpolish(self._elf_path_label)
            self._elf_path_label.style().polish(self._elf_path_label)
            self._var_count_label.setText(f"变量: {len(variables)}")
            self._log(f"✓ 已加载 ELF: {path}；解析到 {len(variables)} 个全局变量")
            self._populate_tree(variables)
            from ..core.event_bus import EventBus, ElfLoadedEvent
            EventBus.instance().publish(
                "elf/loaded", ElfLoadedEvent(path=path, variables=variables, load_token=self._elf_load_token))
            return True
        except Exception as exc:
            if parser is not None:
                parser.close()
            if show_error:
                QMessageBox.critical(
                    self, "ELF 加载失败", f"无法解析 ELF 文件:\n{exc}")
            self._log(f"✗ ELF 加载失败: {exc}")
            return False
    def _populate_tree(self, variables):
        """记录全量变量并按当前搜索词刷新树"""
        self._all_variables = list(variables)
        self._apply_filter(self._search_input.text())

    def _schedule_filter(self, _text):
        """搜索防抖入口：重启 200ms 定时器，合并连续击键。"""
        self._filter_timer.start()

    def _apply_filter(self, text):
        """按搜索词实时过滤变量树（变量名 / 结构体.成员，子串不区分大小写）"""
        from ..debug.elf_parser import filter_variables
        hits = filter_variables(self._all_variables, text)
        self._populate_tree_hits(hits)
        q = (text or "").strip()
        if q:
            self._log(f"🔍 搜索 '{q}': 命中 {len(hits)} 个变量")

    def _populate_tree_hits(self, hits):
        """Populate variables and addressable composite leaves."""
        self._tree.clear()
        file_groups = {}
        for var, members in hits:
            file_groups.setdefault(var.file or "未分组", []).append((var, members))
        if file_groups:
            self._tree_stack.setCurrentIndex(0)
        else:
            query = self._search_input.text().strip()
            self._tree_empty.setText(
                f"没有匹配“{query}”的变量或成员" if query
                else "尚未加载变量\n请先选择目标固件的 ELF 文件")
            self._tree_stack.setCurrentIndex(1)
        for fname, items in file_groups.items():
            file_item = QTreeWidgetItem([fname, "", "", ""])
            file_item.setForeground(0, QColor(ui_color("primary")))
            for var, members in items:
                var_item = QTreeWidgetItem([
                    var.name, var.type_name,
                    f"0x{var.address:08X}", f"{var.size}B"
                ])
                if var.is_struct:
                    var_item.setForeground(0, QColor(ui_color("accent")))
                    show = var.members if members is None else members
                    hidden_count = 0
                    if members is None and len(show) > 256:
                        hidden_count = len(show) - 256
                        show = show[:256]
                    for member in show:
                        full_name = (f"{var.name}{member.name}"
                                     if member.name.startswith("[")
                                     else f"{var.name}.{member.name}")
                        address = int(var.address) + int(member.offset)
                        member_item = QTreeWidgetItem([
                            f"  .{member.name}", member.type_name,
                            f"0x{address:08X}", f"{member.size}B"
                        ])
                        member_item.setData(
                            0, Qt.UserRole,
                            (full_name, member.type_name,
                             f"0x{address:08X}", f"{member.size}B"))
                        var_item.addChild(member_item)
                    if hidden_count:
                        more_item = QTreeWidgetItem([
                            f"  ... 另有 {hidden_count} 个叶子，请搜索成员名/索引",
                            "", "", "",
                        ])
                        more_item.setForeground(0, Qt.gray)
                        var_item.addChild(more_item)
                else:
                    var_item.setData(
                        0, Qt.UserRole,
                        (var.name, var.type_name,
                         f"0x{var.address:08X}", f"{var.size}B"))
                file_item.addChild(var_item)
            self._tree.addTopLevelItem(file_item)
            file_item.setExpanded(True)

    def _add_tree_item_to_watch(self, item):
        descriptor = item.data(0, Qt.UserRole)
        if not descriptor:
            self._log("⚠ 请选择标量变量或结构体/数组叶子成员")
            return False
        return self._add_to_watch(*descriptor)

    def _on_var_double_click(self, item, column):
        """Double-click a scalar or composite leaf to add it to the watch table."""
        if item.parent() is None:
            return
        self._add_tree_item_to_watch(item)

    def _on_add_watch(self):
        """Add selected scalar variables or composite leaves."""
        items = self._tree.selectedItems()
        if not items:
            self._log("⚠ 请先在变量树中选择一个变量或成员")
            return
        for item in items:
            if item.parent() is not None:
                self._add_tree_item_to_watch(item)

    def _on_add_address(self):
        """Open a compact dialog for map/debugger-derived absolute addresses."""
        dialog = QDialog(self)
        dialog.setWindowTitle("按绝对地址添加监视项")
        form = QFormLayout(dialog)
        name_edit = QLineEdit("manual")
        type_combo = QComboBox()
        type_combo.setEditable(True)
        type_combo.addItems([
            "float", "uint32_t", "int32_t", "uint16_t", "int16_t",
            "uint8_t", "int8_t", "double", "pointer",
        ])
        address_edit = QLineEdit("0x20000000")
        form.addRow("名称:", name_edit)
        form.addRow("类型:", type_combo)
        form.addRow("地址:", address_edit)
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec() == QDialog.Accepted:
            self.add_watch_address(
                name_edit.text(), type_combo.currentText(), address_edit.text())

    def add_watch_address(self, name, type_name, address):
        """Validate and add an absolute-address scalar watch item."""
        from ..debug.elf_parser import type_size
        name = str(name).strip()
        type_name = str(type_name).strip()
        try:
            value = int(address, 0) if isinstance(address, str) else int(address)
        except (TypeError, ValueError):
            self._log(f"✗ 非法地址: {address}")
            return False
        size = type_size(type_name)
        if not name:
            self._log("✗ 名称不能为空")
            return False
        if value < 0 or value > 0xFFFFFFFF:
            self._log(f"✗ 地址超出32位范围: {address}")
            return False
        if size not in (1, 2, 4, 8):
            self._log(f"✗ 不支持的标量类型: {type_name}")
            return False
        return self._add_to_watch(
            name, type_name, f"0x{value:08X}", f"{size}B")

    def _add_to_watch(self, name, type_name, addr_str, size_str):
        """添加变量到监视表"""
        if name in self._watch_rows:
            self._log(f"⚠ 变量 '{name}' 已在监视表中")
            return False

        row = self._watch_table.rowCount()
        self._watch_table.insertRow(row)
        name_item = QTableWidgetItem(name)
        name_item.setToolTip(name)
        self._watch_table.setItem(row, 0, name_item)
        self._watch_table.setItem(row, 1, QTableWidgetItem(type_name))
        self._watch_table.setItem(row, 2, QTableWidgetItem(addr_str))
        self._watch_table.setItem(row, 3, QTableWidgetItem("---"))
        self._watch_table.setItem(row, 4, QTableWidgetItem("读取/写入"))

        del_btn = QPushButton("删除")
        del_btn.setObjectName("btn_ghost")
        del_btn.setFixedWidth(64)
        del_btn.setToolTip(f"从监视表移除 {name}")
        del_btn.clicked.connect(lambda checked=False, b=del_btn: self._remove_watch_row(b))
        self._watch_table.setCellWidget(row, 4, del_btn)
        self._watch_rows[name] = row
        self._sync_watch_state()

        self._log(f"→ 已添加监视变量: {name} ({type_name} @ {addr_str})")
        return True

    def _remove_watch_row(self, btn=None):
        row = None
        if btn is not None:
            for r in range(self._watch_table.rowCount()):
                if self._watch_table.cellWidget(r, 4) is btn:
                    row = r
                    break
        if row is None or not (0 <= row < self._watch_table.rowCount()):
            return
        self._watch_table.removeRow(row)
        self._watch_rows = {
            self._watch_table.item(r, 0).text(): r
            for r in range(self._watch_table.rowCount())
        }
        self._pending_watch_values = {
            name: text for name, text in self._pending_watch_values.items()
            if name in self._watch_rows
        }
        self._updated_this_frame.intersection_update(self._watch_rows)
        self._sync_watch_state()
        self._log(f"已删除监视表第 {row + 1} 行")

    def _on_read_var(self):
        """读取当前选中行（连接时走 DebugService 真读，否则模拟）"""
        row = self._watch_table.currentRow()
        if row < 0:
            self._log("⚠ 请先在监视表中选择一个变量行")
            return
        self._read_row(row)

    def _read_row(self, row):
        if row < 0 or row >= self._watch_table.rowCount():
            return
        name = self._watch_table.item(row, 0).text()
        if self._connected and self._debug is not None:
            from ..debug.elf_parser import type_size, decode_value
            type_name = self._watch_table.item(row, 1).text()
            addr = self._parse_addr(row)
            size = type_size(type_name) or 4

            def on_resp(resp, tn=type_name, nm=name):
                if not self._watch_table:
                    return
                if resp.get("status", 0) != 0:
                    self._log(f"✗ 读取 {nm} 失败: status={resp.get('status')}")
                    return
                val = decode_value(resp.get("payload", b""), tn)
                item = self._value_item(nm)
                if item is not None:
                    item.setText(str(val))
                    item.setForeground(Qt.green)
                self._log(f"← {nm} = {val}")

            getattr(self._debug, "read_memory_block", self._debug.read_memory)(addr, size, callback=on_resp)
            self._log(f"→ 读取 {name} @ 0x{addr:08X} ...")
        else:
            import random
            val = random.uniform(0, 100)
            self._watch_table.item(row, 3).setText(f"{val:.3f}")
            self._watch_table.item(row, 3).setForeground(Qt.green)
            self._log(f"← 读取 {name} = {val:.3f} (模拟值)")

    def _value_item(self, name):
        row = self._watch_rows.get(name)
        return None if row is None else self._watch_table.item(row, 3)

    def _on_read_all(self):
        """Read all watch rows, using READ_BATCH when the service supports it."""
        from ..debug.elf_parser import type_size, decode_value

        count = self._watch_table.rowCount()
        if count == 0:
            self._log("⚠ 监视表为空")
            return
        if (not self._connected or self._debug is None
                or not hasattr(self._debug, "read_batch")):
            for row in range(count):
                self._read_row(row)
            self._log(f"→ 已请求读取 {count} 个监视变量")
            return

        rows = []
        for row in range(count):
            name = self._watch_table.item(row, 0).text()
            type_name = self._watch_table.item(row, 1).text()
            size = type_size(type_name) or 4
            rows.append((name, type_name, self._parse_addr(row), size))
        chunks = [rows[index:index + 32] for index in range(0, len(rows), 32)]
        self._log(f"→ 已请求批量读取 {count} 个监视变量（{len(chunks)} 帧）")

        for chunk in chunks:
            expected_length = sum(item[3] for item in chunk)

            def on_response(response, snapshot=tuple(chunk), expected=expected_length):
                status = response.get("status", 0)
                if status != 0:
                    self._log(f"✗ 批量读取失败: status={status}")
                    return
                payload = bytes(response.get("payload", b""))
                if len(payload) != expected:
                    self._log(
                        f"✗ 批量读取响应长度错误: expected={expected}, actual={len(payload)}")
                    return
                cursor = 0
                for name, type_name, _address, size in snapshot:
                    value = decode_value(payload[cursor:cursor + size], type_name)
                    cursor += size
                    item = self._value_item(name)
                    if item is not None:
                        item.setText(str(value))
                        item.setForeground(Qt.green)
                self._log(f"← 批量读取完成 {len(snapshot)} 个监视变量")

            getattr(self._debug, "read_batch_blocks", self._debug.read_batch)(
                [(address, size) for _name, _type, address, size in chunk],
                callback=on_response)

    def _on_plot_selected(self):
        """把选中（或全部）监视行加入波形：发出通道规格供主窗口纳入采样并绘图"""
        from ..debug.elf_parser import type_size
        rows = sorted({i.row() for i in self._watch_table.selectedItems()})
        if not rows:
            rows = list(range(self._watch_table.rowCount()))
        specs = []
        for row in rows:
            name = self._watch_table.item(row, 0).text()
            type_name = self._watch_table.item(row, 1).text()
            addr = self._parse_addr(row)
            size = type_size(type_name) or 4
            specs.append({"name": name, "address": addr, "size": size, "type_name": type_name})
        if specs:
            self.plot_requested.emit(specs)
            self._log(f"→ 已请求在波形中绘制 {len(specs)} 个通道")

    def _on_write_var(self):
        """写入变量值"""
        from ..core.guardrails import control_restriction
        reason = control_restriction(getattr(self, "_control_check", None))
        if reason:
            self._log(reason)
            return
        row = self._watch_table.currentRow()
        if row < 0:
            self._log("⚠ 请先在监视表中选择一个变量行")
            return

        text = self._write_input.text().strip()
        if not text:
            self._log("⚠ 请输入要写入的值")
            return

        name = self._watch_table.item(row, 0).text()
        reply = QMessageBox.question(self, "确认写入",
            f"确定将变量 '{name}' 写入值 '{text}' 吗?\n\n此操作会直接修改 MCU 内存中的变量值。",
            QMessageBox.Yes | QMessageBox.No)
        if reply != QMessageBox.Yes:
            self._log("写入已取消")
            return

        if self._connected and self._debug is not None:
            from ..debug.elf_parser import encode_value
            type_name = self._watch_table.item(row, 1).text()
            addr = self._parse_addr(row)
            try:
                data = encode_value(text, type_name)
            except ValueError as e:
                self._log(f"✗ 编码失败: {e}")
                return
            self._debug.write_memory(addr, data)
            self._watch_table.item(row, 3).setText(text)
            self._watch_table.item(row, 3).setForeground(Qt.yellow)
            self._log(f"→ 写入 {name} = {text} @ 0x{addr:08X} ({len(data)}B)")
        else:
            self._watch_table.item(row, 3).setText(text)
            self._watch_table.item(row, 3).setForeground(Qt.yellow)
            self._log(f"→ 写入 {name} = {text} (模拟)")
        self._write_input.clear()

    def _on_write_verify(self):
        """写入后读回校验（连接时走 DebugService.write_and_verify，否则模拟）。"""
        from ..core.guardrails import control_restriction
        reason = control_restriction(getattr(self, "_control_check", None))
        if reason:
            self._log(reason)
            return
        row = self._watch_table.currentRow()
        if row < 0:
            self._log("⚠ 请先在监视表中选择一个变量行")
            return
        text = self._write_input.text().strip()
        if not text:
            self._log("⚠ 请输入要写入的值")
            return
        name = self._watch_table.item(row, 0).text()
        type_name = self._watch_table.item(row, 1).text()
        from ..debug.elf_parser import encode_value, type_size, decode_value
        try:
            data = encode_value(text, type_name)
        except ValueError as e:
            self._log(f"✗ 编码失败: {e}")
            return
        if not (self._connected and self._debug is not None
                and hasattr(self._debug, "write_and_verify")):
            self._log(f"→ 写入并校验 {name} = {text} (模拟)")
            return
        reply = QMessageBox.question(
            self, "确认写入并校验",
            f"将 '{name}' 写入 '{text}' 并读回校验?\n\n会直接修改 MCU 内存。",
            QMessageBox.Yes | QMessageBox.No)
        if reply != QMessageBox.Yes:
            self._log("已取消")
            return
        addr = self._parse_addr(row)
        size = type_size(type_name) or len(data)

        def on_done(ok, readback, nm=name, tn=type_name, sz=size):
            item = self._value_item(nm)
            if ok:
                got = decode_value(readback[:sz], tn)
                if item is not None:
                    item.setText(str(got))
                    item.setForeground(Qt.green)
                self._log(f"✓ {nm} 写入并校验通过 = {got}")
            else:
                if item is not None:
                    item.setForeground(Qt.red)
                self._log(f"✗ {nm} 写入校验失败（读回与写入不一致或被拒）")

        self._debug.write_and_verify(addr, data, size, callback=on_done)
        self._log(f"→ 写入并校验 {name} = {text} @ 0x{addr:08X} ...")
        self._write_input.clear()

    def _on_refresh_vars(self):
        """刷新变量列表"""
        if self._elf_parser:
            variables = self._elf_parser.parse_variables()
            self._populate_tree(variables)
            self._log(f"已刷新变量列表 ({len(variables)} 个变量)")
        else:
            self._log("⚠ 请先加载 ELF 文件")

    def _on_clear_watch(self):
        self._watch_flush_timer.stop()
        self._watch_table.setRowCount(0)
        self._watch_rows.clear()
        self._pending_watch_values.clear()
        self._updated_this_frame.clear()
        self._sync_watch_state()
        self._log("监视表已清空")

    def _sync_watch_state(self):
        count = self._watch_table.rowCount()
        self._watch_stack.setCurrentIndex(0 if count else 1)
        self._watch_count_label.setText(f"{count} 项")
        self._watch_badge.set_status(
            f"{count} 监视项", "info" if count else "neutral")

    def set_connected(self, connected: bool):
        self._connected = connected

    def set_debug_service(self, debug):
        """注入 DebugService，用于真实读写 MCU 内存"""
        self._debug = debug

    def _parse_addr(self, row):
        txt = self._watch_table.item(row, 2).text().strip()
        return int(txt, 16) if txt.lower().startswith("0x") else int(txt, 0)

    def _log(self, msg: str):
        if self._log_label.text() != msg:
            self._log_label.setText(msg)
        self._log_label.setToolTip(msg)
        role = ("danger" if msg.startswith("✗") else
                "warning" if msg.startswith("⚠") else
                "success" if msg.startswith("✓") else "text_dim")
        if getattr(self, "_log_role", None) != role:
            self._log_role = role
            self._log_label.setStyleSheet(f"color: {ui_color(role)};")








