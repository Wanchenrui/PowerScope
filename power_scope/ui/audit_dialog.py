"""audit_dialog.py — 写入审计查看器（P1-12）

列出 power_scope.core.write_audit 记录的最近写入（时间/变量/旧值/新值/
来源），「一键回滚」取选中记录的前值回填调参页编辑框经确认条写回。
"""
from __future__ import annotations

import time as _time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QHeaderView, QLabel,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)


class AuditDialog(QDialog):
    """写入审计对话框。"""

    def __init__(self, records: list[dict], parent=None):
        super().__init__(parent)
        self._records = list(records)
        self.setWindowTitle("写入审计")
        self.resize(680, 420)
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        tip = QLabel(
            "按时间倒序显示最近的参数写入（来源：手动 / tuning / 调参 / rollback）。")
        tip.setObjectName("dim")
        lay.addWidget(tip)

        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(
            ["时间", "变量", "旧值", "新值", "来源"])
        self._table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        lay.addWidget(self._table, 1)

        row = QHBoxLayout()
        self._status = QLabel("")
        self._status.setObjectName("dim")
        row.addWidget(self._status, 1)
        self._rollback_btn = QPushButton("回滚选中项")
        self._rollback_btn.setEnabled(False)
        self._rollback_btn.setToolTip("把选中记录的旧值填回调参页（确认后写入）")
        row.addWidget(self._rollback_btn)
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        row.addWidget(close_btn)
        lay.addLayout(row)

        self._table.itemSelectionChanged.connect(self._on_selection)
        self._populate()

    def _populate(self):
        self._table.setRowCount(len(self._records))
        for row, rec in enumerate(reversed(self._records)):
            stamp = _time.strftime("%m-%d %H:%M:%S",
                                   _time.localtime(rec.get("timestamp", 0)))
            values = (stamp, str(rec.get("var", "")),
                      "—" if rec.get("old_value") is None
                      else f"{rec['old_value']:.6g}",
                      f"{rec.get('new_value', 0):.6g}",
                      str(rec.get("source", "")))
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column in (0, 2, 3):
                    item.setTextAlignment(Qt.AlignCenter)
                self._table.setItem(row, column, item)
        if not self._records:
            self._status.setText("暂无写入记录")

    def _on_selection(self):
        self._rollback_btn.setEnabled(
            self._table.currentRow() >= 0 and bool(self._records))

    def selected_record(self) -> dict | None:
        row = self._table.currentRow()
        if row < 0 or not self._records:
            return None
        return list(reversed(self._records))[row]
