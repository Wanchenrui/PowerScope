"""quick_command_editor.py — 快捷命令编辑器（P1-8 UI）

SerialMonitorView 的 4 个 NS800RT 黄金帧过去是硬编码；本对话框把它们
变成可增删改的收藏夹（power_scope.core.quick_commands 持久化）：

  - 表格列出全部命令（名称 / 帧 / 备注）
  - 新增/编辑用底部表单；「自动 CRC」按调试帧格式对载荷补 CRC16
  - 校验按钮检查完整帧 CRC；非法 Hex 拒绝保存
  - 保存后经 saved 信号通知串口监控页重建按钮
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..core.quick_commands import (
    QuickCommand, QuickCommandStore, build_frame_from_payload, check_frame_crc,
)


class QuickCommandEditor(QDialog):
    """快捷命令收藏夹编辑对话框。"""

    saved = Signal(list)   # list[QuickCommand]

    def __init__(self, store: QuickCommandStore | None = None, parent=None):
        super().__init__(parent)
        self._store = store or QuickCommandStore()
        self._commands: list[QuickCommand] = []
        self._editing_index = -1
        self.setWindowTitle("快捷命令编辑器")
        self.resize(640, 480)
        self._build()
        self._reload()

    # ---- UI ----
    def _build(self):
        lay = QVBoxLayout(self)

        tip = QLabel(
            "每行一条命令，帧为完整 Hex（含 CRC）。「自动CRC」按调试帧格式包装载荷。")
        tip.setObjectName("dim")
        tip.setWordWrap(True)
        lay.addWidget(tip)

        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(["名称", "帧 (Hex)", "备注"])
        self._table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeToContents)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        lay.addWidget(self._table, 1)

        row = QHBoxLayout()
        edit_btn = QPushButton("编辑选中")
        edit_btn.clicked.connect(self._edit_selected)
        row.addWidget(edit_btn)
        del_btn = QPushButton("删除选中")
        del_btn.clicked.connect(self._delete_selected)
        row.addWidget(del_btn)
        row.addStretch()
        reset_btn = QPushButton("恢复内置")
        reset_btn.setToolTip("恢复内置的 4 个 NS800RT 黄金帧")
        reset_btn.clicked.connect(self._reset_defaults)
        row.addWidget(reset_btn)
        lay.addLayout(row)

        # 编辑表单
        form_box = QWidget()
        form = QFormLayout(form_box)
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("例如：读设备信息")
        form.addRow("名称:", self._name_edit)
        self._frame_edit = QLineEdit()
        self._frame_edit.setPlaceholderText("A5 5A 01 07 01 00 00 00 00 00 00 00 7D 2F")
        form.addRow("帧 (Hex):", self._frame_edit)
        self._note_edit = QLineEdit()
        self._note_edit.setPlaceholderText("备注（可选）")
        form.addRow("备注:", self._note_edit)
        self._form_status = QLabel("")
        self._form_status.setObjectName("dim")
        self._form_status.setWordWrap(True)
        form.addRow("", self._form_status)
        lay.addWidget(form_box)

        btn_row = QHBoxLayout()
        self._crc_btn = QPushButton("自动CRC")
        self._crc_btn.setToolTip("取帧前 4 字节的 cmd/seq 作为头，对后续载荷补 CRC")
        self._crc_btn.clicked.connect(self._auto_crc)
        btn_row.addWidget(self._crc_btn)
        check_btn = QPushButton("校验CRC")
        check_btn.clicked.connect(self._check_crc)
        btn_row.addWidget(check_btn)
        btn_row.addStretch()
        self._save_btn = QPushButton("保存为新命令")
        self._save_btn.setObjectName("btn_primary")
        self._save_btn.clicked.connect(self._save_command)
        btn_row.addWidget(self._save_btn)
        lay.addLayout(btn_row)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.accept)
        lay.addWidget(buttons)

    # ---- 数据 ----
    def _refresh_table(self):
        """用当前内存中的 commands 重建表格。"""
        self._table.setRowCount(len(self._commands))
        for row, cmd in enumerate(self._commands):
            self._table.setItem(row, 0, QTableWidgetItem(cmd.name))
            self._table.setItem(row, 1, QTableWidgetItem(cmd.display_hex()))
            self._table.setItem(row, 2, QTableWidgetItem(cmd.note))

    def _reload(self):
        """从 store 重载（仅在打开/恢复默认时调用）。"""
        self._commands = self._store.load()
        self._refresh_table()

    def _flush(self):
        try:
            self._store.save(self._commands)
            self.saved.emit(list(self._commands))
            self._form_status.setText(f"✓ 已保存 {len(self._commands)} 条命令")
        except OSError as exc:
            self._form_status.setText(f"✗ 保存失败: {exc}")

    def _edit_selected(self):
        row = self._table.currentRow()
        if row < 0 or row >= len(self._commands):
            return
        cmd = self._commands[row]
        self._editing_index = row
        self._name_edit.setText(cmd.name)
        self._frame_edit.setText(cmd.frame_hex)
        self._note_edit.setText(cmd.note)
        self._save_btn.setText("保存修改")
        self._form_status.setText(f"正在编辑: {cmd.name}")

    def _delete_selected(self):
        row = self._table.currentRow()
        if row < 0 or row >= len(self._commands):
            return
        removed = self._commands.pop(row)
        self._refresh_table()
        self._flush()
        self._form_status.setText(f"已删除: {removed.name}")

    def _reset_defaults(self):
        self._commands = self._store.reset_defaults()
        self._refresh_table()
        self._flush()
        self._form_status.setText("已恢复内置命令")

    def _auto_crc(self):
        """按调试帧头（cmd, seq）+ 载荷补 CRC。"""
        text = "".join(self._frame_edit.text().split())
        try:
            data = bytes.fromhex(text)
        except ValueError as exc:
            self._form_status.setText(f"✗ Hex 解析失败: {exc}")
            return
        if len(data) < 4:
            self._form_status.setText(
                "✗ 需要完整帧（A5 5A ver cmd seq len ...）；"
                "请粘贴完整帧或点「校验CRC」")
            return
        # 帧格式: A5 5A ver cmd seq_lo seq_hi len_lo len_hi payload...
        payload_hex = data[8:].hex(" ") if len(data) > 8 else ""
        try:
            frame = build_frame_from_payload(data[3], payload_hex,
                                              seq=data[4] | (data[5] << 8))
        except Exception as exc:  # noqa: BLE001
            self._form_status.setText(f"✗ 组帧失败: {exc}")
            return
        self._frame_edit.setText(frame)
        self._form_status.setText("✓ 已按 cmd/seq + 载荷重新计算 CRC")

    def _check_crc(self):
        ok, message = check_frame_crc(self._frame_edit.text())
        self._form_status.setText(("✓ " if ok else "✗ ") + message)

    def _save_command(self):
        name = self._name_edit.text().strip()
        frame_hex = self._frame_edit.text().strip()
        note = self._note_edit.text().strip()
        if not name:
            self._form_status.setText("✗ 名称不能为空")
            return
        try:
            bytes.fromhex("".join(frame_hex.split()))
        except ValueError as exc:
            self._form_status.setText(f"✗ 帧 Hex 非法: {exc}")
            return
        ok, message = check_frame_crc(frame_hex)
        if not ok:
            self._form_status.setText(f"✗ {message}（可点「自动CRC」修复）")
            return
        if self._editing_index >= 0 and self._editing_index < len(self._commands):
            existing = self._commands[self._editing_index]
            existing.name = name
            existing.frame_hex = frame_hex
            existing.note = note
            self._form_status.setText(f"✓ 已更新: {name}")
            self._editing_index = -1
            self._save_btn.setText("保存为新命令")
        else:
            self._commands.append(
                QuickCommandStore.normalize(name, frame_hex, note))
            self._form_status.setText(f"✓ 已添加: {name}")
        # 只刷新表格（不能再 _reload，否则会冲掉刚加的内存条目）
        self._refresh_table()
        self._flush()
