"""Searchable MSG command catalog and manual request console."""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QGridLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..core.msg_service import KNOWN_MSG_COMMANDS
from ..debug.msg_elf import ElfMsgCommand, parse_msg_commands


class MsgCommandView(QWidget):
    """ELF-backed MSG browser; unknown payload lengths remain user-editable."""

    def __init__(self, service=None, parent=None):
        super().__init__(parent)
        self._service = service
        self._connected = False
        self._commands: list[ElfMsgCommand] = []
        self._build_ui()
        self._load_known_fallback()

    def _build_ui(self):
        root = QVBoxLayout(self)

        catalog = QFrame()
        catalog.setObjectName("card")
        catalog_layout = QVBoxLayout(catalog)
        title = QLabel("MSG 命令字（从 ELF 的 g_msgCmdCfgTbl 读取）")
        title.setObjectName("title")
        catalog_layout.addWidget(title)
        self._search = QLineEdit()
        self._search.setPlaceholderText("搜索命令字、中文名称、解析函数或处理函数，例如 2108 / GridVolt")
        self._search.textChanged.connect(self._apply_filter)
        catalog_layout.addWidget(self._search)
        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels(
            ["命令字", "方向", "名称", "数据长度", "解析函数", "处理函数"])
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.Stretch)
        header.setSectionResizeMode(5, QHeaderView.Stretch)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        catalog_layout.addWidget(self._table, 1)
        self._catalog_status = QLabel("尚未加载 ELF；当前仅显示已知命令")
        self._catalog_status.setObjectName("dim")
        catalog_layout.addWidget(self._catalog_status)
        root.addWidget(catalog, 3)

        request = QFrame()
        request.setObjectName("card")
        grid = QGridLayout(request)
        request_title = QLabel("MSG 收发")
        request_title.setObjectName("title")
        grid.addWidget(request_title, 0, 0, 1, 6)
        grid.addWidget(QLabel("命令字"), 1, 0)
        self._command = QLineEdit("0x2108")
        self._command.setPlaceholderText("0x0000..0xFFFF")
        grid.addWidget(self._command, 1, 1)
        grid.addWidget(QLabel("数据字数"), 1, 2)
        self._word_count = QSpinBox()
        self._word_count.setRange(0, 32)
        grid.addWidget(self._word_count, 1, 3)
        self._length_source = QLabel("手动")
        self._length_source.setObjectName("dim")
        grid.addWidget(self._length_source, 1, 4)

        grid.addWidget(QLabel("写入数据"), 2, 0)
        self._payload = QLineEdit()
        self._payload.setPlaceholderText("16 位十六进制字，空格或逗号分隔，例如 0001 00FF")
        grid.addWidget(self._payload, 2, 1, 1, 4)
        self._read_button = QPushButton("读取 / 查询")
        self._read_button.setObjectName("btn_primary")
        self._read_button.clicked.connect(self._send_read)
        grid.addWidget(self._read_button, 1, 5)
        self._write_button = QPushButton("写入 / 下发")
        self._write_button.setObjectName("btn_warning")
        self._write_button.clicked.connect(self._send_write)
        grid.addWidget(self._write_button, 2, 5)
        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumBlockCount(500)
        grid.addWidget(self._log, 3, 0, 1, 6)
        root.addWidget(request, 2)
        self._update_enabled()

    def set_service(self, service):
        self._service = service
        self._update_enabled()

    def set_connected(self, connected: bool):
        self._connected = bool(connected)
        self._update_enabled()

    def _update_enabled(self):
        enabled = self._connected and self._service is not None
        if hasattr(self, "_read_button"):
            self._read_button.setEnabled(enabled)
            self._write_button.setEnabled(enabled)

    def _load_known_fallback(self):
        self._commands = [
            ElfMsgCommand(spec.command, spec.direction, "", "")
            for spec in KNOWN_MSG_COMMANDS.values()
        ]
        self._populate_table()

    def load_elf(self, path: str) -> bool:
        try:
            commands = parse_msg_commands(path)
        except Exception as exc:
            self._catalog_status.setText(f"MSG 命令表解析失败：{exc}")
            self._append_log(f"ELF 命令表解析失败：{exc}")
            return False
        self._commands = commands
        self._populate_table()
        self._catalog_status.setText(
            f"已从 ELF 读取 {len(commands)} 个命令；已知长度自动填充，其余长度手动输入")
        self._append_log(f"已加载 {len(commands)} 个 MSG 命令：{path}")
        return True

    def _populate_table(self):
        query = self._search.text().strip().lower()
        selected_command = self._parse_command(silent=True)
        rows = []
        for entry in self._commands:
            spec = KNOWN_MSG_COMMANDS.get(entry.command)
            label = spec.label if spec else ""
            direction = spec.direction if spec else entry.direction
            search_text = " ".join((
                f"{entry.command:04x}", f"0x{entry.command:04x}", label,
                direction, entry.parser_name, entry.handler_name,
            )).lower()
            if not query or query in search_text:
                rows.append((entry, spec, label, direction))

        self._table.setRowCount(len(rows))
        selected_row = -1
        for row, (entry, spec, label, direction) in enumerate(rows):
            count_text = (
                f"{spec.data_words} 字 / {spec.data_words * 2} 字节"
                if spec and spec.data_words is not None else "手动")
            values = (
                f"0x{entry.command:04X}",
                "读取" if direction == "read" else "写入",
                label,
                count_text,
                entry.parser_name,
                entry.handler_name,
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column in (0, 1, 3):
                    item.setTextAlignment(Qt.AlignCenter)
                item.setData(Qt.UserRole, entry.command)
                self._table.setItem(row, column, item)
            if entry.command == selected_command:
                selected_row = row
        if selected_row >= 0:
            self._table.selectRow(selected_row)

    def _apply_filter(self):
        self._populate_table()

    def _on_selection_changed(self):
        row = self._table.currentRow()
        if row < 0:
            return
        item = self._table.item(row, 0)
        if item is None:
            return
        command = int(item.data(Qt.UserRole))
        self._command.setText(f"0x{command:04X}")
        spec = KNOWN_MSG_COMMANDS.get(command)
        if spec and spec.data_words is not None:
            self._word_count.setValue(spec.data_words)
            self._length_source.setText("已知命令：自动填充")
        else:
            self._word_count.setValue(0)
            self._length_source.setText("ELF 无长度信息：手动")

    @staticmethod
    def _hex_value(text: str, field: str) -> int:
        value_text = text.strip().lower()
        if not value_text:
            raise ValueError(f"{field}不能为空")
        value = int(value_text, 16)
        if not 0 <= value <= 0xFFFF:
            raise ValueError(f"{field}必须在 0x0000..0xFFFF")
        return value

    def _parse_command(self, silent: bool = False):
        try:
            return self._hex_value(self._command.text(), "命令字")
        except Exception:
            if silent:
                return None
            raise ValueError("命令字格式错误") from None

    def _parse_payload(self) -> tuple[int, ...]:
        text = self._payload.text().replace(",", " ").replace(";", " ")
        return tuple(self._hex_value(token, "数据字") for token in text.split())

    def _send_read(self):
        try:
            command = self._parse_command()
            count = self._word_count.value()
            self._service.request_read(command, count, self._response_callback)
            self._append_log(f"TX 查询 0x{command:04X}，期望 {count} 字")
        except Exception as exc:
            QMessageBox.warning(self, "MSG 发送失败", str(exc))

    def _send_write(self):
        try:
            command = self._parse_command()
            words = self._parse_payload()
            if len(words) != self._word_count.value():
                raise ValueError(
                    f"输入了 {len(words)} 个数据字，但数据字数为 {self._word_count.value()}")
            self._service.request_write(command, words, self._response_callback)
            payload = " ".join(f"{word:04X}" for word in words) or "<空>"
            self._append_log(f"TX 写入 0x{command:04X}：{payload}")
        except Exception as exc:
            QMessageBox.warning(self, "MSG 发送失败", str(exc))

    def _response_callback(self, response: dict):
        command = response.get("cmd", 0)
        kind = response.get("kind", "unknown")
        words = response.get("words", ())
        payload = " ".join(f"{word:04X}" for word in words)
        self._append_log(
            f"RX 0x{command:04X} {kind.upper()}"
            + (f"：{payload}" if payload else ""))

    def _append_log(self, text: str):
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self._log.appendPlainText(f"[{timestamp}] {text}")
