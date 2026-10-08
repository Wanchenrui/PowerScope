"""empty_state.py — 空态占位组件。

专业调试工具与半成品的分水岭往往在空态：满屏 `---` 加一行灰字，用户不知道
下一步该做什么。本组件统一提供「图标 + 标题 + 一句说明 + 主操作按钮」，
由各视图在「无数据 / 未加载 / 无通道」时显示。

用法::

    box = QStackedWidget()
    box.addWidget(EmptyState("wave", "还没有波形通道",
                             "从左侧「可选变量」里挑一个变量加进来",
                             action_text="添加通道", action=self._on_add))
    box.addWidget(real_content)
    ...
    box.setCurrentIndex(1)   # 有数据后切到真实内容
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from ..theme import ui_color
from . import tab_icons

TITLE_STYLE = "font-size:14px;font-weight:600;"
DESC_STYLE = "font-size:12px;"
ACTION_MIN_W = 132


class EmptyState(QWidget):
    """居中空态：矢量图标 + 标题 + 说明 + 可选主操作按钮。"""

    def __init__(self, icon: str, title: str, description: str = "",
                 action_text: str = "", action=None, parent=None):
        super().__init__(parent)
        self._icon_name = icon

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 24, 24, 24)
        lay.setSpacing(6)
        lay.addStretch(1)

        self._icon_label = QLabel()
        self._icon_label.setFixedSize(46, 46)
        self._icon_label.setAlignment(Qt.AlignCenter)
        lay.addWidget(self._icon_label, 0, Qt.AlignCenter)

        self._title = QLabel(title)
        self._title.setStyleSheet(TITLE_STYLE + f"color:{ui_color('text')};")
        self._title.setAlignment(Qt.AlignCenter)
        self._title.setWordWrap(True)
        lay.addWidget(self._title, 0, Qt.AlignCenter)

        self._desc = QLabel(description)
        self._desc.setStyleSheet(DESC_STYLE + f"color:{ui_color('text_dim')};")
        self._desc.setAlignment(Qt.AlignCenter)
        self._desc.setWordWrap(True)
        lay.addWidget(self._desc, 0, Qt.AlignCenter)

        self._button = None
        if action_text:
            self._button = QPushButton(action_text)
            self._button.setObjectName("btn_primary")
            self._button.setMinimumWidth(ACTION_MIN_W)
            if action is not None:
                self._button.clicked.connect(action)
            lay.addWidget(self._button, 0, Qt.AlignCenter)

        lay.addStretch(1)
        self._paint_icon()

    # ---- 主题 ----
    def _paint_icon(self):
        """把矢量图标画到 QLabel 的 pixmap 上（颜色取当前主题的 dim 档）。"""
        from PySide6.QtGui import QColor, QPainter, QPixmap

        side = self._icon_label.width()
        px = QPixmap(side, side)
        px.fill(Qt.transparent)
        p = QPainter(px)
        from PySide6.QtCore import QRect
        tab_icons.draw_icon(p, self._icon_name, QRect(0, 0, side, side),
                            ui_color("text_dim"))
        p.end()
        self._icon_label.setPixmap(px)

    def apply_theme(self, theme_name=None):
        """主题切换后重绘图标（颜色跟随令牌）。"""
        self._paint_icon()

    # ---- 内容 ----
    def set_title(self, text: str):
        self._title.setText(text)

    def set_description(self, text: str):
        self._desc.setText(text)
