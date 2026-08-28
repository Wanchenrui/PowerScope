"""关于对话框"""
from PySide6.QtWidgets import QDialog, QVBoxLayout, QPushButton, QLabel

from ... import __version__


class AboutDialog(QDialog):
    """PowerScope 关于对话框"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"关于 PowerScope v{__version__}")
        layout = QVBoxLayout(self)
        title = QLabel(f"PowerScope v{__version__}")
        title.setObjectName("title")
        layout.addWidget(title)
        layout.addWidget(QLabel("光伏微逆与储能串口调试仿真平台"))
        layout.addWidget(QLabel(f"版本: {__version__}"))
        layout.addWidget(QLabel("技术栈: C + Python (PySide6)"))
        layout.addWidget(QLabel("测试: 617 项全部通过"))
        layout.addWidget(QLabel(""))
        layout.addWidget(QLabel("功能: ELF变量监控 / 双模调参 / Modbus / 流式录波"))
        btn = QPushButton("确定")
        btn.clicked.connect(self.accept)
        layout.addWidget(btn)
