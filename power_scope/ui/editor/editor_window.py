"""editor_window.py — 仪表盘可视化编辑器主窗口（组件库 | 画布 | 属性面板）。"""
from __future__ import annotations
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QScrollArea,
    QToolBar, QLabel, QFileDialog, QMessageBox,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction

from .canvas import EditorCanvas
from .palette import PaletteWidget
from .inspector import InspectorPanel


class DashboardEditor(QMainWindow):
    """所见即所得仪表盘编辑器。保存后 emit saved(profile)。"""
    saved = Signal(object)

    def __init__(self, profile, live_preview=True, parent=None):
        super().__init__(parent)
        self._profile = profile
        self.setWindowTitle(f"仪表盘编辑器 — {getattr(profile, 'name', '')}")
        self.resize(1100, 720)

        self._canvas = EditorCanvas(profile, live_preview=live_preview)
        self._palette = PaletteWidget()
        self._inspector = InspectorPanel(profile)

        self._canvas.selection_changed.connect(self._inspector.set_item)
        self._inspector.changed.connect(self._canvas.refresh_item)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._canvas)

        left = QWidget(); lv = QVBoxLayout(left)
        lv.setContentsMargins(6, 6, 6, 6)
        lv.addWidget(QLabel("组件库（拖入画布）"))
        lv.addWidget(self._palette)

        right = QWidget(); rv = QVBoxLayout(right)
        rv.setContentsMargins(6, 6, 6, 6)
        rv.addWidget(QLabel("属性"))
        rv.addWidget(self._inspector)

        split = QSplitter(Qt.Horizontal)
        split.addWidget(left); split.addWidget(scroll); split.addWidget(right)
        split.setStretchFactor(0, 0); split.setStretchFactor(1, 1); split.setStretchFactor(2, 0)
        split.setSizes([200, 640, 260])
        self.setCentralWidget(split)

        self._build_toolbar()
        self._canvas.load_from_profile(profile)

    def _build_toolbar(self):
        tb = QToolBar("编辑"); tb.setMovable(False)
        self.addToolBar(tb)
        tb.addAction(QAction("删除选中", self, triggered=self._canvas.remove_selected))
        tb.addSeparator()
        tb.addAction(QAction("应用到当前设备", self, triggered=self._apply))
        tb.addAction(QAction("另存为 YAML...", self, triggered=self._save_yaml))
        tb.addSeparator()
        hint = QLabel("  拖动标题移动 · 右下角缩放 · 自动吸附网格  ")
        hint.setObjectName("dim")
        tb.addWidget(hint)

    def _apply(self):
        """把画布导出的组件写回 profile 并通知主窗口重建仪表盘。"""
        self._profile.dashboard = self._canvas.export_widgets()
        self.saved.emit(self._profile)
        # 非模态反馈：模态弹窗在无头/自动化环境会永久阻塞
        self.statusBar().showMessage("✓ 仪表盘布局已应用到当前设备", 5000)

    def _save_yaml(self):
        self._profile.dashboard = self._canvas.export_widgets()
        path, _ = QFileDialog.getSaveFileName(
            self, "保存设备配置", "", "YAML 配置 (*.yaml *.yml)")
        if not path:
            return
        try:
            self._profile.to_yaml(path)
            self.saved.emit(self._profile)
            QMessageBox.information(self, "已保存", f"已写入:\n{path}")
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "保存失败", str(e))
