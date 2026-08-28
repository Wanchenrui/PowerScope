"""inspector.py — 属性面板：按注册表 schema 为选中组件自动生成编辑表单。"""
from __future__ import annotations
from PySide6.QtWidgets import (
    QWidget, QFormLayout, QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QLabel,
)
from PySide6.QtCore import Signal

from ..widgets.registry import WIDGET_REGISTRY


class InspectorPanel(QWidget):
    """选中组件的属性编辑；任何改动 emit changed(item)。"""
    changed = Signal(object)  # EditorItem

    def __init__(self, profile=None, parent=None):
        super().__init__(parent)
        self._profile = profile
        self._item = None
        self._form = QFormLayout(self)
        self._placeholder = QLabel("选中组件以编辑属性")
        self._placeholder.setObjectName("dim")
        self._form.addRow(self._placeholder)

    def set_profile(self, profile):
        self._profile = profile

    def _clear(self):
        while self._form.count():
            it = self._form.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()

    def set_item(self, item):
        self._item = item
        self._clear()
        if item is None:
            lbl = QLabel("选中组件以编辑属性")
            lbl.setObjectName("dim")
            self._form.addRow(lbl)
            return
        m = item.model
        spec = WIDGET_REGISTRY.get(m.type)
        self._form.addRow(QLabel(f"类型: {spec.label if spec else m.type}"))

        # 通用属性
        ide = QLineEdit(m.id)
        ide.textChanged.connect(lambda v: self._set_attr("id", v))
        self._form.addRow("ID", ide)
        te = QLineEdit(m.title or "")
        te.textChanged.connect(lambda v: self._set_attr("title", v))
        self._form.addRow("标题", te)
        for key in ("x", "y", "w", "h"):
            sp = QSpinBox(); sp.setRange(0, 200); sp.setValue(getattr(m, key))
            sp.valueChanged.connect(lambda v, k=key: self._set_attr(k, v))
            self._form.addRow(key.upper(), sp)

        # 组件专属属性（按 schema）
        for prop in (spec.props if spec else []):
            self._add_prop_row(m, prop)

    def _add_prop_row(self, m, prop):
        key, label, kind = prop["key"], prop["label"], prop["kind"]
        cur = m.config.get(key, prop.get("default"))
        if kind == "float":
            w = QDoubleSpinBox(); w.setRange(0, 1e6); w.setDecimals(3)
            w.setValue(float(cur or 0))
            w.valueChanged.connect(lambda v, k=key: self._set_cfg(k, v))
        elif kind == "int":
            w = QSpinBox(); w.setRange(0, 100000); w.setValue(int(cur or 0))
            w.valueChanged.connect(lambda v, k=key: self._set_cfg(k, v))
        elif kind == "var":
            w = QComboBox(); w.addItem("")
            for v in getattr(self._profile, "variables", []) or []:
                w.addItem(v.name)
            w.setCurrentText(str(cur or ""))
            w.currentTextChanged.connect(lambda v, k=key: self._set_cfg(k, v))
        elif kind == "varlist":
            w = QLineEdit(", ".join(cur) if isinstance(cur, list) else str(cur or ""))
            w.textChanged.connect(
                lambda v, k=key: self._set_cfg(
                    k, [s.strip() for s in v.split(",") if s.strip()]))
        elif kind == "advanced":
            w = QLabel("（复杂结构，请在 YAML 中编辑）")
            w.setObjectName("dim")
        else:  # text
            w = QLineEdit(str(cur or ""))
            w.textChanged.connect(lambda v, k=key: self._set_cfg(k, v))
        self._form.addRow(label, w)

    def _set_attr(self, key, value):
        if self._item is None:
            return
        setattr(self._item.model, key, value)
        self._item.sync_geometry()
        self.changed.emit(self._item)

    def _set_cfg(self, key, value):
        if self._item is None:
            return
        self._item.model.config[key] = value
        self.changed.emit(self._item)
