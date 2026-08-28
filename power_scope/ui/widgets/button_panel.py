"""按钮面板组件 — 配置驱动的控制按钮组"""
from PySide6.QtWidgets import QFrame, QVBoxLayout, QGridLayout, QPushButton, QLabel, QMessageBox
from PySide6.QtCore import Signal


class ButtonPanelWidget(QFrame):
    """控制按钮面板 — 从 DeviceProfile 动态生成按钮

    信号:
        button_clicked(id, action, value) — 按钮点击事件
    """
    button_clicked = Signal(str, str, object)

    def __init__(self, title, buttons, profile):
        super().__init__()
        self.setObjectName("card")
        self._profile = profile
        lay = QVBoxLayout(self)
        lbl = QLabel(title)
        lbl.setObjectName("title")
        lay.addWidget(lbl)
        grid = QGridLayout()
        grid.setSpacing(6)
        for i, bid in enumerate(buttons):
            bd = next((b for b in profile.control_buttons if b.id == bid), None)
            if not bd:
                continue
            btn = QPushButton(bd.label)
            btn.setObjectName(f"btn_{bd.color}")
            btn.setMinimumHeight(36)
            btn.clicked.connect(lambda c, b=bd: self._on_click(b))
            grid.addWidget(btn, i // 2, i % 2)
        lay.addLayout(grid)
        lay.addStretch()

    def _on_click(self, btn):
        if btn.confirm:
            r = QMessageBox.question(
                self, "确认", f"确定执行 '{btn.label}' 吗?",
                QMessageBox.Yes | QMessageBox.No
            )
            if r != QMessageBox.Yes:
                return
        self.button_clicked.emit(btn.id, btn.action, btn.value)
