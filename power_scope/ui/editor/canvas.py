"""canvas.py — 仪表盘可视化编辑画布（WYSIWYG，网格吸附）。

每个组件用 EditorItem 表示：可拖动、可缩放、吸附到网格，内嵌注册表工厂
渲染的真实组件预览。画布状态可导出为 list[DashboardWidget]，配合
DeviceProfile.to_yaml 双向读写。
"""
from __future__ import annotations
from PySide6.QtWidgets import (
    QWidget, QFrame, QLabel, QVBoxLayout, QSizePolicy,
)
from PySide6.QtCore import Qt, Signal, QPoint, QRect

from ...config.device_profile import DashboardWidget
from ..widgets.registry import WIDGET_REGISTRY, create_widget


GRID_UNIT = 44   # 每个网格单元的像素尺寸


def snap(px: int, unit: int = GRID_UNIT) -> int:
    """把像素坐标吸附到最近的网格线，返回网格索引（非像素）。"""
    return max(0, int(round(px / unit)))


class EditorItem(QFrame):
    """画布上的一个可拖动/缩放组件框。"""
    selected = Signal(object)
    changed = Signal(object)

    HEADER_H = 22
    GRIP = 12

    def __init__(self, model: DashboardWidget, profile, live_preview=True, parent=None):
        super().__init__(parent)
        self.model = model
        self._profile = profile
        self.setObjectName("card")
        self.setFrameShape(QFrame.StyledPanel)
        self._drag_origin = None
        self._resize_origin = None
        self._selected = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, self.HEADER_H, 4, self.GRIP)
        spec = WIDGET_REGISTRY.get(model.type)
        label = spec.label if spec else model.type
        self._header = QLabel(f"{label}", self)
        self._header.setStyleSheet("color:#00b4d8;font-weight:600;background:transparent;")
        self._header.setGeometry(6, 2, 400, self.HEADER_H - 2)

        # 内嵌真实预览（复用注册表工厂）；失败则占位标签
        preview = None
        if live_preview:
            try:
                preview = create_widget(model, profile)
            except Exception:
                preview = None
        if preview is not None:
            preview.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            preview.setEnabled(False)
            lay.addWidget(preview)
            self._preview = preview
        else:
            ph = QLabel(model.title or (spec.label if spec else model.type))
            ph.setAlignment(Qt.AlignCenter)
            ph.setStyleSheet("color:#959aa8;")
            lay.addWidget(ph)
            self._preview = ph
        self.sync_geometry()

    # ---- 几何 ----
    def sync_geometry(self):
        self.setGeometry(self.model.x * GRID_UNIT, self.model.y * GRID_UNIT,
                         max(1, self.model.w) * GRID_UNIT, max(1, self.model.h) * GRID_UNIT)

    def set_selected(self, on: bool):
        self._selected = on
        self.setStyleSheet(
            "QFrame#card{border:2px solid #00b4d8;}" if on else "")

    def _in_grip(self, pos) -> bool:
        return (pos.x() >= self.width() - self.GRIP - 4
                and pos.y() >= self.height() - self.GRIP - 4)

    # ---- 鼠标交互 ----
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.selected.emit(self)
            if self._in_grip(e.position().toPoint()):
                self._resize_origin = (e.globalPosition().toPoint(),
                                       self.model.w, self.model.h)
            elif e.position().y() <= self.HEADER_H:
                self._drag_origin = (e.globalPosition().toPoint(),
                                     self.model.x, self.model.y)
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._drag_origin is not None:
            start, x0, y0 = self._drag_origin
            d = e.globalPosition().toPoint() - start
            self.move(max(0, (x0 * GRID_UNIT) + d.x()),
                      max(0, (y0 * GRID_UNIT) + d.y()))
        elif self._resize_origin is not None:
            start, w0, h0 = self._resize_origin
            d = e.globalPosition().toPoint() - start
            self.resize(max(GRID_UNIT, (w0 * GRID_UNIT) + d.x()),
                        max(GRID_UNIT, (h0 * GRID_UNIT) + d.y()))
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self._drag_origin is not None:
            self.model.x = snap(self.x())
            self.model.y = snap(self.y())
            self._drag_origin = None
            self.sync_geometry()
            self.changed.emit(self)
        elif self._resize_origin is not None:
            self.model.w = max(1, snap(self.width()))
            self.model.h = max(1, snap(self.height()))
            self._resize_origin = None
            self.sync_geometry()
            self.changed.emit(self)
        super().mouseReleaseEvent(e)


class EditorCanvas(QWidget):
    """承载 EditorItem 的画布：网格背景 + 拖放新增 + 选择。"""
    selection_changed = Signal(object)   # EditorItem | None
    model_changed = Signal()

    def __init__(self, profile=None, live_preview=True, parent=None):
        super().__init__(parent)
        self._profile = profile
        self._live = live_preview
        self._items: list[EditorItem] = []
        self._selected: EditorItem | None = None
        self.setAcceptDrops(True)
        self.setMinimumSize(GRID_UNIT * 16, GRID_UNIT * 12)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_profile(self, profile):
        self._profile = profile

    # ---- 载入/导出 ----
    def load_from_profile(self, profile):
        self._profile = profile
        self.clear()
        for wd in getattr(profile, "dashboard", []) or []:
            self._add_item(wd)
        self.model_changed.emit()

    def clear(self):
        for it in self._items:
            it.deleteLater()
        self._items.clear()
        self._selected = None
        self.selection_changed.emit(None)

    def export_widgets(self) -> list:
        """按当前画布导出 list[DashboardWidget]（供 to_yaml）。"""
        return [it.model for it in self._items]

    # ---- 增删 ----
    def add_widget_type(self, wtype: str, x=0, y=0):
        spec = WIDGET_REGISTRY.get(wtype)
        if spec is None:
            return None
        n = sum(1 for it in self._items if it.model.type == wtype)
        wd = DashboardWidget(
            id=f"{wtype}_{n+1}", type=wtype, title=spec.label,
            x=x, y=y, w=spec.default_w, h=spec.default_h, config={})
        return self._add_item(wd)

    def _add_item(self, wd):
        item = EditorItem(wd, self._profile, live_preview=self._live, parent=self)
        item.selected.connect(self._on_item_selected)
        item.changed.connect(lambda _i: self.model_changed.emit())
        item.show()
        self._items.append(item)
        return item

    def remove_selected(self):
        if self._selected is None:
            return
        self._items.remove(self._selected)
        self._selected.deleteLater()
        self._selected = None
        self.selection_changed.emit(None)
        self.model_changed.emit()

    def refresh_item(self, item):
        """属性面板改动后重建该 item 的几何/预览。"""
        item.sync_geometry()

    def _on_item_selected(self, item):
        for it in self._items:
            it.set_selected(it is item)
        self._selected = item
        self.selection_changed.emit(item)

    # ---- 拖放新增 ----
    def dragEnterEvent(self, e):
        if e.mimeData().hasFormat("application/x-powerscope-widget"):
            e.acceptProposedAction()

    def dropEvent(self, e):
        data = e.mimeData().data("application/x-powerscope-widget")
        wtype = bytes(data).decode("utf-8")
        pos = e.position().toPoint()
        self.add_widget_type(wtype, x=snap(pos.x()), y=snap(pos.y()))
        self.model_changed.emit()
        e.acceptProposedAction()

    # ---- 网格背景 ----
    def paintEvent(self, e):
        from PySide6.QtGui import QPainter, QPen, QColor
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#0c0e14"))
        pen = QPen(QColor("#1e2130"))
        p.setPen(pen)
        w, h = self.width(), self.height()
        x = 0
        while x < w:
            p.drawLine(x, 0, x, h); x += GRID_UNIT
        y = 0
        while y < h:
            p.drawLine(0, y, w, y); y += GRID_UNIT
        p.end()
