"""信息面板组件 — 变量关键数值显示"""
from PySide6.QtWidgets import QFrame, QVBoxLayout, QGridLayout, QLabel


class InfoPanelWidget(QFrame):
    """信息面板 — 多变量名值对显示"""

    def __init__(self, title, variables, profile):
        super().__init__()
        self.setObjectName("card")
        self._profile = profile
        self._labels = {}
        lay = QVBoxLayout(self)
        lbl = QLabel(title)
        lbl.setObjectName("title")
        lay.addWidget(lbl)
        form = QGridLayout()
        form.setSpacing(4)
        for i, vn in enumerate(variables):
            var = profile.find_var(vn)
            if not var:
                continue
            nl = QLabel(var.display_name)
            nl.setObjectName("dim")
            vl = QLabel("---")
            vl.setObjectName("value")
            vl.setStyleSheet(f"color:{var.color};font-size:16px;")
            ul = QLabel(var.unit)
            ul.setObjectName("unit")
            form.addWidget(nl, i, 0)
            form.addWidget(vl, i, 1)
            form.addWidget(ul, i, 2)
            self._labels[vn] = (vl, var)
        lay.addLayout(form)
        lay.addStretch()

    def update_values(self, values):
        for vn, (lbl, var) in self._labels.items():
            v = values.get(vn)
            if v is not None:
                phys = v * var.scale + var.offset
                lbl.setText(f"{phys:.{var.precision}f}")
