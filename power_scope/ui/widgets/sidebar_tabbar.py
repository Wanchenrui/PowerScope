"""sidebar_tabbar.py — 侧边导航 TabBar（cockpit 风）

用于 QTabWidget(West)：标签竖排在左侧，文字仍水平显示（Qt 默认会旋转文字，
观感差）。相比旧实现：

  - 图标由 Unicode 字形改为 QPainter 矢量绘制（tab_icons.py），
    不再受字体缺字/字宽不一致影响，颜色跟随主题令牌；
  - 文字与选中态颜色改为显式取自主题，不再依赖 QSS 是否作用于自绘文字；
  - tab 宽度按「图标 + 间距 + 实测文字宽度 + 内边距」计算，不再写死 148px。
"""
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QFontMetrics
from PySide6.QtWidgets import QStyle, QStyleOptionTab, QStylePainter, QTabBar

from . import tab_icons
from ..theme import current_theme, get_theme

ICON_SIDE = 17          # 图标边长（px）
ICON_GAP = 9            # 图标与文字间距
PAD_LEFT = 14           # 左内边距
PAD_RIGHT = 12          # 右内边距
TAB_MIN_H = 46          # 行高（可点区域 ≥44px）


class SideTabBar(QTabBar):
    """左侧竖排、文字水平、带矢量图标的导航栏。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._icons = {}
        self.setExpanding(False)
        self.setDrawBase(False)

    # ---- 图标管理 ----
    def set_icon(self, index: int, name: str) -> None:
        """给指定 tab 设置矢量图标（name 见 tab_icons.available()）。"""
        self._icons[index] = name
        self.update()

    def icon_name(self, index: int):
        return self._icons.get(index)

    # ---- 尺寸 ----
    def tabSizeHint(self, index):
        s = super().tabSizeHint(index)
        s.transpose()  # West 下 Qt 会再转一次，这里先交换让宽高符合水平文字
        text_w = QFontMetrics(self.font()).horizontalAdvance(self.tabText(index))
        icon_w = (ICON_SIDE + ICON_GAP) if index in self._icons else 0
        s.setWidth(max(s.width(), text_w + icon_w + PAD_LEFT + PAD_RIGHT))
        s.setHeight(max(s.height(), TAB_MIN_H))
        return s

    # ---- 绘制 ----
    def _theme_colors(self, selected: bool):
        t = get_theme(current_theme())
        if selected:
            return QColor(t["primary"]), QColor(t["text"])
        return QColor(t["text_dim"]), QColor(t["text_dim"])

    def paintEvent(self, event):
        painter = QStylePainter(self)
        opt = QStyleOptionTab()
        current = self.currentIndex()
        for i in range(self.count()):
            self.initStyleOption(opt, i)
            selected = (i == current)
            icon_color, text_color = self._theme_colors(selected)

            # 1) 背景形状：选中态显式补一条靠内容侧的指示条（QSS 的
            #    QTabBar::tab:selected 只覆盖默认方位，West 下方向不对）
            saved_text = opt.text
            opt.text = ""
            painter.drawControl(QStyle.CE_TabBarTabShape, opt)
            if selected:
                r = self.tabRect(i)
                painter.fillRect(QRect(r.right() - 2, r.top() + 6, 2, r.height() - 12),
                                 QColor(get_theme(current_theme())["primary"]))
            opt.text = saved_text

            # 2) 图标 + 水平文字
            r = self.tabRect(i)
            x = r.left() + PAD_LEFT
            name = self._icons.get(i)
            if name:
                icon_rect = QRect(x, r.top() + (r.height() - ICON_SIDE) // 2,
                                  ICON_SIDE, ICON_SIDE)
                tab_icons.draw_icon(painter, name, icon_rect,
                                    icon_color.name())
                x += ICON_SIDE + ICON_GAP

            painter.setPen(text_color)
            painter.drawText(
                QRect(x, r.top(), max(0, r.right() - PAD_RIGHT - x), r.height()),
                Qt.AlignVCenter | Qt.AlignLeft, self.tabText(i))