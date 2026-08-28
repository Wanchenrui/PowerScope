"""参数编辑器组件 — 变量在线读写"""
from PySide6.QtWidgets import QFrame, QVBoxLayout, QGridLayout, QPushButton, QLabel, QDoubleSpinBox
from PySide6.QtCore import Signal


class ParamEditorWidget(QFrame):
    """参数编辑器 — 变量名 + 数值输入 + 写入按钮

    信号:
        param_written(name, raw_value) — 用户点击写入按钮
    """
    param_written = Signal(str, float)

    def __init__(self, title, variables, profile):
        super().__init__()
        self.setObjectName("card")
        self._profile = profile
        self._editors = {}
        lay = QVBoxLayout(self)
        lbl = QLabel(title)
        lbl.setObjectName("title")
        lay.addWidget(lbl)
        form = QGridLayout()
        form.setSpacing(6)
        for i, vn in enumerate(variables):
            var = profile.find_var(vn)
            if not var:
                continue
            nl = QLabel(var.display_name)
            ed = QDoubleSpinBox()
            ed.setRange(var.min_val, var.max_val)
            ed.setDecimals(var.precision)
            ed.setSingleStep(0.01)
            # monospace font via QSS
            wb = QPushButton("写入")
            wb.setObjectName("btn_primary")
            wb.setFixedWidth(60)
            wb.clicked.connect(lambda c, v=var, e=ed: self._on_write(v, e))
            form.addWidget(nl, i, 0)
            form.addWidget(ed, i, 1)
            form.addWidget(wb, i, 2)
            self._editors[vn] = (ed, var)
        lay.addLayout(form)
        lay.addStretch()

    def _on_write(self, var, ed):
        val = ed.value()
        raw = (val - var.offset) / var.scale
        self.param_written.emit(var.name, raw)

    def update_values(self, values):
        for vn, (ed, var) in self._editors.items():
            if vn in values:
                # 用户正在编辑时不回写，避免流式数据冲掉输入中的值
                if ed.hasFocus():
                    continue
                ed.blockSignals(True)
                ed.setValue(values[vn] * var.scale + var.offset)
                ed.blockSignals(False)
