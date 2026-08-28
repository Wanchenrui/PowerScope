"""sidebar_tabbar.py — 侧边导航 TabBar（cockpit 风）

用于 QTabWidget(West)：标签竖排在左侧，但文字仍水平显示（Qt 默认会旋转文字，
观感差）。同时支持每个标签一个前置字形图标，且不污染 tabText（保持可测/可查）。
"""
from PySide6.QtWidgets import QTabBar, QStylePainter, QStyleOptionTab, QStyle
from PySide6.QtCore import Qt


class SideTabBar(QTabBar):
    """左侧竖排、文字水平、带字形图标的导航栏。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._glyphs = {}
        self.setExpanding(False)
        self.setDrawBase(False)

    def set_glyph(self, index: int, glyph: str):
        self._glyphs[index] = glyph
        self.update()

    def tabSizeHint(self, index):
        s = super().tabSizeHint(index)
        s.transpose()  # West 下 Qt 会再转一次，这里先交换让宽高符合水平文字
        s.setHeight(max(s.height(), 44))
        s.setWidth(max(s.width(), 148))
        return s

    def paintEvent(self, event):
        painter = QStylePainter(self)
        opt = QStyleOptionTab()
        for i in range(self.count()):
            self.initStyleOption(opt, i)
            # 只画背景形状（清空 text，避免 Qt 画出旋转文字）
            saved = opt.text
            opt.text = ""
            painter.drawControl(QStyle.CE_TabBarTabShape, opt)
            opt.text = saved
            # 水平绘制：字形 + 标签
            r = self.tabRect(i)
            glyph = self._glyphs.get(i, "")
            label = (glyph + "   " + self.tabText(i)) if glyph else self.tabText(i)
            painter.drawText(r.adjusted(16, 0, -6, 0),
                             Qt.AlignVCenter | Qt.AlignLeft, label)
