"""palette.py — 组件库面板：列出可拖入画布的注册组件。"""
from __future__ import annotations
from PySide6.QtWidgets import QListWidget, QListWidgetItem
from PySide6.QtCore import Qt, QMimeData, QByteArray
from PySide6.QtGui import QDrag

from ..widgets.registry import palette_items

MIME = "application/x-powerscope-widget"


class PaletteWidget(QListWidget):
    """可拖拽的组件库；拖到画布即新增该类型组件。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        for wtype, label, w, h in palette_items():
            it = QListWidgetItem(f"{label}  ({w}×{h})")
            it.setData(Qt.UserRole, wtype)
            self.addItem(it)

    def startDrag(self, actions):
        it = self.currentItem()
        if it is None:
            return
        wtype = it.data(Qt.UserRole)
        mime = QMimeData()
        mime.setData(MIME, QByteArray(wtype.encode("utf-8")))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.CopyAction)
