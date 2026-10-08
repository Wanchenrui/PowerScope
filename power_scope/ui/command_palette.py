"""command_palette.py — 全局命令面板（P0-4）

「一次输入，跳任一处」：Ctrl+K 唤出，输入变量名/命令字/页签名/动作名，
回车直达。解决 55 个 profile 变量 + 数千 ELF 符号 + 数百 MSG 命令 +
多页签的「先想我要用哪个页签」心智负担。

结构：
  - 索引与搜索在 core/command_index.py（纯逻辑，可单测）
  - 本类只负责呈现（无边框浮层 + 输入框 + 结果列表）与派发
  - 条目来源由 MainWindow 刷新（页签/变量/符号/MSG/动作），激活回调
    经 item_activated 信号交回 MainWindow 执行

键位：Ctrl+K 全局切换 · ↑↓ 选择 · Enter 执行 · Esc 关闭
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QVBoxLayout, QWidget,
)

from ..core.command_index import CommandItem, kind_label, search
from ..theme import current_theme, font_size, get_theme, radius, spacing, ui_color

MAX_VISIBLE_ROWS = 9


class CommandPalette(QWidget):
    """挂在主窗口上的 Ctrl+K 面板（默认隐藏）。"""

    item_activated = Signal(object)   # CommandItem

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list[CommandItem] = []
        self.setObjectName("command_palette")
        self.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint
                            | Qt.NoDropShadowWindowHint)
        self._build()
        self.hide()

    # ---- UI ----
    def _build(self):
        self.resize(560, 380)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(spacing("sm"))

        self._input = QLineEdit()
        self._input.setPlaceholderText(
            "跳转到：页签 / 变量 / ELF 符号 / MSG 命令 / 动作…")
        self._input.setClearButtonEnabled(True)
        self._input.textChanged.connect(self._refilter)
        self._input.returnPressed.connect(self._activate_current)
        lay.addWidget(self._input)

        self._status = QLabel("")
        self._status.setObjectName("dim")
        lay.addWidget(self._status)

        self._results = QListWidget()
        self._results.setSelectionMode(QListWidget.SingleSelection)
        self._results.itemActivated.connect(
            lambda item: self._emit_item(item))
        self._results.itemClicked.connect(
            lambda item: self._emit_item(item))
        lay.addWidget(self._results, 1)

        hint = QHBoxLayout()
        hint.addWidget(QLabel("↑↓ 选择 · Enter 执行 · Esc 关闭"))
        hint.addStretch()
        lay.addLayout(hint)
        self._apply_style()

    def _apply_style(self):
        t = get_theme(current_theme())
        self.setStyleSheet(
            f"QWidget#command_palette {{ background-color:{t['bg_alt']};"
            f"border:1px solid {t['border']}; border-radius:{radius('panel')}; }}"
            f"QLabel {{ background:transparent; color:{t['text_dim']};"
            f"font-size:{font_size('sm')}; }}"
            f"QListWidget {{ border:1px solid {t['border']};"
            f"border-radius:{radius('input')}; }}"
        )

    def apply_theme(self, _theme_name=None):
        self._apply_style()

    # ---- 索引 ----
    def set_items(self, items: list[CommandItem]):
        self._items = list(items)
        self._refilter(self._input.text())

    def _refilter(self, text: str):
        hits = search(self._items, text or "", limit=200)
        self._results.clear()
        for item, _score in hits:
            label = item.title
            if item.subtitle:
                label = f"{item.title}   {item.subtitle}"
            row = QListWidgetItem(f"[{kind_label(item.kind)}] {label}")
            row.setData(Qt.UserRole, item)
            self._results.addItem(row)
        if self._results.count():
            self._results.setCurrentRow(0)
        self._status.setText(f"{self._results.count()} / {len(self._items)} 条")

    # ---- 派发 ----
    def _activate_current(self):
        row = self._results.currentRow()
        item = (self._results.item(row) if row >= 0 else None)
        if item is not None:
            self._emit_item(item)

    def _emit_item(self, row: QListWidgetItem | None):
        if row is None:
            return
        item = row.data(Qt.UserRole)
        if item is None:
            return
        self.hide()
        self.item_activated.emit(item)

    # ---- 显隐 ----
    def toggle(self):
        if self.isVisible():
            self.hide()
        else:
            self.open()

    def open(self):
        """在主窗口顶部居中唤出。"""
        parent = self.parentWidget()
        if parent is None:
            return
        self._input.clear()
        self._refilter("")
        self.move(parent.geometry().center().x() - self.width() // 2,
                  parent.geometry().top() + 90)
        self.show()
        self.raise_()
        self._input.setFocus(Qt.OtherFocusReason)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.hide()
            event.accept()
            return
        if event.key() in (Qt.Key_Down, Qt.Key_Up):
            row = self._results.currentRow()
            delta = 1 if event.key() == Qt.Key_Down else -1
            self._results.setCurrentRow(
                max(0, min(self._results.count() - 1, row + delta)))
            event.accept()
            return
        super().keyPressEvent(event)
