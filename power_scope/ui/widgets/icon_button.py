"""icon_button.py — 带矢量图标的按钮（P0-6 工具栏图标化）

13px 字号下中文按钮文字宽，「文字墙」是首屏拥挤的主因。
IconButton 在文字左侧画 tab_icons 矢量图标（随主题换色、任意 DPI 清晰），
配合 tooltip 承载完整说明 —— 图标 + tooltip 是性价比最高的减噪手段。

用法::

    btn = IconButton("swap", "切换设备...")
    btn.clicked.connect(self._on_load_profile)
    IconButton("palette")            # 纯图标（文字省略）

绘制策略：自绘。QSS 画按钮底/框/圆角（CE_PushButton, text 置空），
图标与文字由本类按「图标 + 间距 + 文字」手工排版 —— QPushButton 默认把
文字居中，若只改 padding 预留图标位，不同字号/按钮高度下图标与文字
基线对不齐，索性整块自绘。
"""
from __future__ import annotations

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QPainter, QPalette
from PySide6.QtWidgets import QPushButton, QStyle, QStyleOptionButton

from ..theme import current_theme, get_theme, ui_color
from . import tab_icons

ICON_SIDE = 15        # 图标边长（px）
ICON_GAP = 6          # 图标与文字间距


class IconButton(QPushButton):
    """左侧带矢量图标的按钮；文字可省略（此时为纯图标按钮）。"""

    def __init__(self, icon: str, text: str = "", parent=None,
                 icon_side: int = ICON_SIDE, tooltip: str | None = None):
        super().__init__(text, parent)
        self._icon_name = icon
        self._icon_side = icon_side
        if tooltip:
            self.setToolTip(tooltip)
        self.setMinimumHeight(24)

    # ---- 尺寸 ----
    def sizeHint(self):
        s = super().sizeHint()
        if self._icon_name:
            extra = self._icon_side + (ICON_GAP if self.text() else 0)
            s.setWidth(max(s.width() + extra - 2, self._icon_side + 14))
            s.setHeight(max(s.height(), self._icon_side + 10))
        return s

    # ---- 绘制 ----
    def _icon_color(self) -> str:
        """图标色跟随按钮状态：禁用→muted；按下/选中→底色反色；语义实心底→底色。"""
        if not self.isEnabled():
            return ui_color("text_dim")
        if self.isDown() or self.isChecked():
            return get_theme(current_theme())["bg"]
        if self.property("state") in ("idle", "connected", "retry"):
            return get_theme(current_theme())["bg"]
        return ui_color("text")

    def _text_color(self, opt: QStyleOptionButton) -> QColor:
        group = (QPalette.Disabled if not self.isEnabled()
                 else QPalette.Current if self.isDown() or self.isChecked()
                 else QPalette.Current)
        color = opt.palette.color(group, QPalette.ButtonText)
        if not self.isEnabled():
            color = QColor(ui_color("text_dim"))
        return color

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        opt = QStyleOptionButton()
        self.initStyleOption(opt)
        text = opt.text
        opt.text = ""
        opt.icon = self.style().standardIcon(QStyle.SP_CustomBase)
        self.style().drawControl(QStyle.CE_PushButton, opt, painter, self)

        if self._icon_name:
            text_w = (self.fontMetrics().horizontalAdvance(text)
                      if text else 0)
            content_w = self._icon_side + (ICON_GAP if text_w else 0) + text_w
            x = max(2, (self.width() - content_w) // 2)
            y = (self.height() - self._icon_side) // 2
            icon_rect = QRect(x, y, self._icon_side, self._icon_side)
            tab_icons.draw_icon(painter, self._icon_name, icon_rect,
                                self._icon_color())
            if text:
                painter.setPen(self._text_color(opt))
                text_rect = QRect(x + self._icon_side + ICON_GAP, 0,
                                  max(0, self.width() - x - self._icon_side
                                      - ICON_GAP - 2),
                                  self.height())
                painter.drawText(text_rect,
                                 Qt.AlignVCenter | Qt.AlignLeft, text)
        painter.end()
