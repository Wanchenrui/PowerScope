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
from .theme import get_theme, ui_color


class VariableInspectorView(QWidget):
    """变量查看器: 加载ELF → 变量树 → 在线读写"""

    plot_requested = Signal(list)   # list[dict]: {name,address,size,type_name}

    def __init__(self, profile=None, parent=None):
        super().__init__(parent)
        self._profile = profile
        self._elf_parser = None
        self._connected = False
        self._all_variables = []
        self._debug = None
        # 搜索防抖：击键后 200ms 合并重建变量树（大 ELF 数千变量时避免逐键卡顿）
        self._filter_timer = QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(200)
        self._filter_timer.timeout.connect(
            lambda: self._apply_filter(self._search_input.text()))
        self._build_ui()
        self._subscribe_events()
        # 使用 Qt destroyed 信号保证在 QObject 销毁时可靠清理
        self.destroyed.connect(self._cleanup)

    def _subscribe_events(self):
        """订阅 EventBus 事件"""
        from ..core.event_bus import EventBus
        EventBus.instance().subscribe("var/updated", self._on_var_updated)

    def _on_var_updated(self, event):
        """收到变量更新事件 → 刷新监视表"""
        # 防御性检查：widget 已销毁时跳过
        if not self._watch_table:
            return
        for row in range(self._watch_table.rowCount()):
            name_item = self._watch_table.item(row, 0)
            if name_item and name_item.text() == event.name:
                val_item = self._watch_table.item(row, 3)
                if val_item:
                    val_item.setText(f"{event.phys_value:.2f} {event.unit}")
                    val_item.setForeground(QColor(ui_color("success")))
                # 高频流式事件不写提示条（否则标签持续闪烁），仅交互类事件提示
                if getattr(event, "source", "") != "stream":
                    self._log(f"← {event.name} = {event.phys_value:.2f} {event.unit}")
                break

    def _cleanup(self):
        """Qt destroyed 信号槽 — 保证在 QObject 销毁时被调用，取消 EventBus 订阅"""
        try:
            from ..core.event_bus import EventBus
            EventBus.instance().unsubscribe("var/updated", self._on_var_updated)
        except Exception:
            pass
        if self._elf_parser is not None:
            self._elf_parser.close()
            self._elf_parser = None

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # ===== ELF 加载区 =====
        elf_group = QGroupBox("ELF 固件文件")
        elf_layout = QHBoxLayout(elf_group)
        self._elf_path_label = QLabel("未加载")
        self._elf_path_label.setObjectName("dim")
        elf_layout.addWidget(self._elf_path_label, 1)

        load_btn = QPushButton("加载 ELF...")
        load_btn.setObjectName("btn_primary")
        load_btn.clicked.connect(self._on_load_elf)
        elf_layout.addWidget(load_btn)

        self._var_count_label = QLabel("变量: 0")
        elf_layout.addWidget(self._var_count_label)

        layout.addWidget(elf_group)

        # ===== 变量树 + 变量表 =====
        splitter = QSplitter(Qt.Horizontal)

        # 左侧: 变量树
        tree_group = QGroupBox("变量树 (按源文件分组)")
        tree_layout = QVBoxLayout(tree_group)
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("🔍 搜索变量名 / 结构体.成员（实时过滤）")
        self._search_input.setClearButtonEnabled(True)
        self._search_input.textChanged.connect(self._schedule_filter)
        tree_layout.addWidget(self._search_input)

        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["变量名", "类型", "地址", "大小"])
        self._tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self._tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._tree.itemDoubleClicked.connect(self._on_var_double_click)
        tree_layout.addWidget(self._tree)

        # 操作按钮
        btn_row = QHBoxLayout()
        add_watch_btn = QPushButton("→ 添加到监视表")
        add_watch_btn.clicked.connect(self._on_add_watch)
        btn_row.addWidget(add_watch_btn)
        address_btn = QPushButton("按地址添加...")
        address_btn.clicked.connect(self._on_add_address)
        btn_row.addWidget(address_btn)
        refresh_btn = QPushButton("刷新变量列表")
        refresh_btn.clicked.connect(self._on_refresh_vars)
        btn_row.addWidget(refresh_btn)
        tree_layout.addLayout(btn_row)

        splitter.addWidget(tree_group)

        # 右侧: 监视表
        watch_group = QGroupBox("在线监视表")
        watch_layout = QVBoxLayout(watch_group)

        self._watch_table = QTableWidget(0, 5)
        self._watch_table.setHorizontalHeaderLabels(["变量名", "类型", "地址", "当前值", "操作"])
        self._watch_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._watch_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self._watch_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        watch_layout.addWidget(self._watch_table)

        # 写入区
        write_row = QHBoxLayout()
        write_row.addWidget(QLabel("写入值:"))
        self._write_input = QLineEdit()
        self._write_input.setPlaceholderText("输入新值后点击「写入」")
        write_row.addWidget(self._write_input)

        write_btn = QPushButton("写入")
        write_btn.setObjectName("btn_warning")
        write_btn.clicked.connect(self._on_write_var)
        write_row.addWidget(write_btn)

        read_btn = QPushButton("读取")
        read_btn.setObjectName("btn_primary")
        read_btn.clicked.connect(self._on_read_var)
        write_row.addWidget(read_btn)

        verify_btn = QPushButton("写入并校验")
        verify_btn.clicked.connect(self._on_write_verify)
        write_row.addWidget(verify_btn)

        watch_layout.addLayout(write_row)

        batch_row = QHBoxLayout()
        read_all_btn = QPushButton("全部读取")
        read_all_btn.clicked.connect(self._on_read_all)
        batch_row.addWidget(read_all_btn)
        plot_btn = QPushButton("选中→波形")
        plot_btn.setObjectName("btn_primary")
        plot_btn.clicked.connect(self._on_plot_selected)
        batch_row.addWidget(plot_btn)
        clear_btn = QPushButton("清空监视表")
        clear_btn.clicked.connect(self._on_clear_watch)
        batch_row.addWidget(clear_btn)
        watch_layout.addLayout(batch_row)

        splitter.addWidget(watch_group)
        splitter.setSizes([500, 500])
        layout.addWidget(splitter)

        # 日志
        self._log_label = QLabel("提示: 加载 ELF 文件后，双击左侧变量添加到监视表")
        self._log_label.setObjectName("hint")
        layout.addWidget(self._log_label)

    def _on_load_elf(self):
        """交互选择并加载 ELF 文件。"""
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 ELF 固件文件", "",
            "ELF 文件 (*.elf *.axf *.out);;所有文件 (*)")
        if path:
            self.load_elf(path)

    def load_elf(self, path: str, show_error: bool = True) -> bool:
        """加载指定 ELF；供 profile 自动加载与手动选择共用。"""
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
                "elf/loaded", ElfLoadedEvent(path=path, variables=variables))
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
        for fname, items in file_groups.items():
            file_item = QTreeWidgetItem([fname, "", "", ""])
            file_item.setForeground(0, Qt.cyan)
            for var, members in items:
                var_item = QTreeWidgetItem([
                    var.name, var.type_name,
                    f"0x{var.address:08X}", f"{var.size}B"
                ])
                if var.is_struct:
                    var_item.setForeground(0, Qt.magenta)
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
        # 检查是否已存在
        for row in range(self._watch_table.rowCount()):
            if self._watch_table.item(row, 0).text() == name:
                self._log(f"⚠ 变量 '{name}' 已在监视表中")
                return False

        row = self._watch_table.rowCount()
        self._watch_table.insertRow(row)
        self._watch_table.setItem(row, 0, QTableWidgetItem(name))
        self._watch_table.setItem(row, 1, QTableWidgetItem(type_name))
        self._watch_table.setItem(row, 2, QTableWidgetItem(addr_str))
        self._watch_table.setItem(row, 3, QTableWidgetItem("---"))
        self._watch_table.setItem(row, 4, QTableWidgetItem("读取/写入"))

        del_btn = QPushButton("删除")
        del_btn.setFixedWidth(50)
        del_btn.clicked.connect(lambda checked=False, b=del_btn: self._remove_watch_row(b))
        self._watch_table.setCellWidget(row, 4, del_btn)

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

            self._debug.read_memory(addr, size, callback=on_resp)
            self._log(f"→ 读取 {name} @ 0x{addr:08X} ...")
        else:
            import random
            val = random.uniform(0, 100)
            self._watch_table.item(row, 3).setText(f"{val:.3f}")
            self._watch_table.item(row, 3).setForeground(Qt.green)
            self._log(f"← 读取 {name} = {val:.3f} (模拟值)")

    def _value_item(self, name):
        for r in range(self._watch_table.rowCount()):
            it = self._watch_table.item(r, 0)
            if it is not None and it.text() == name:
                return self._watch_table.item(r, 3)
        return None

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

            self._debug.read_batch(
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
        self._watch_table.setRowCount(0)
        self._log("监视表已清空")

    def set_connected(self, connected: bool):
        self._connected = connected

    def set_debug_service(self, debug):
        """注入 DebugService，用于真实读写 MCU 内存"""
        self._debug = debug

    def _parse_addr(self, row):
        txt = self._watch_table.item(row, 2).text().strip()
        return int(txt, 16) if txt.lower().startswith("0x") else int(txt, 0)

    def _log(self, msg: str):
        self._log_label.setText(msg)








