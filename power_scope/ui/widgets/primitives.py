"""primitives.py — UI 基础原语：样式重刷工具 + 页面标题栏 + 状态徽章

为「现代化工业风」交互打磨提供各视图复用的轻量组件：
  - repolish / set_object_name：objectName 与动态属性切换的样板封装
  - PageHeader：页头结构（标题/副标题 + 右侧操作区），样式钩子走 objectName
  - StatusBadge：语义状态徽章，tone 写入动态属性供 QSS 选择器消费，
    文字/圆点颜色全部走主题语义令牌，切主题自动适配
"""
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..theme import ui_color


def repolish(widget: QWidget) -> None:
    """objectName/动态属性变化后强制 Qt 重算样式并触发重绘。"""
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def set_object_name(widget: QWidget, name: str) -> None:
    """仅当 objectName 变化时更新并 repolish（幂等，避免重复 polish 抖动）。"""
    if widget.objectName() != name:
        widget.setObjectName(name)
        repolish(widget)


class PageHeader(QWidget):
    """页面标题栏：左侧标题/副标题，右侧操作区（add_widget 追加控件）。

    样式钩子：page_header / page_title / page_subtitle（全局 QSS 按
    objectName 着色，不在此内联样式）。布局零外边距，便于嵌入任意容器。
    """

    def __init__(self, title: str, subtitle: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("page_header")
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)
        texts = QVBoxLayout()
        texts.setContentsMargins(0, 0, 0, 0)
        texts.setSpacing(0)
        self._title = QLabel(title)
        self._title.setObjectName("page_title")
        self._subtitle = QLabel(subtitle)
        self._subtitle.setObjectName("page_subtitle")
        self._subtitle.setVisible(bool(subtitle))
        texts.addWidget(self._title)
        texts.addWidget(self._subtitle)
        root.addLayout(texts)
        root.addStretch(1)
        self._actions = QHBoxLayout()
        self._actions.setContentsMargins(0, 0, 0, 0)
        self._actions.setSpacing(8)
        root.addLayout(self._actions)

    def add_widget(self, widget: QWidget) -> None:
        """向右侧操作区追加控件（按钮/徽章/分隔符等）。"""
        self._actions.addWidget(widget)


_BADGE_TONES = {
    "neutral": "text_dim",
    "info": "primary",
    "ok": "success",
    "warning": "warning",
    "error": "danger",
}


class StatusBadge(QFrame):
    """状态徽章：语义圆点 + 文字，tone 变化写入动态属性并刷新主题色。

    颜色映射走 theme.ui_color 语义令牌（neutral 用 text_dim），
    未识别 tone 按 neutral 处理；text/tone 均未变化时跳过样式刷新。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("status_badge")
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self.setFixedHeight(22)
        self._tone = "neutral"
        self._label = ""
        self.setProperty("tone", "neutral")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 0, 8, 0)
        lay.setSpacing(6)
        self._dot = QLabel()
        self._dot.setFixedSize(8, 8)
        self._text = QLabel()
        lay.addWidget(self._dot)
        lay.addWidget(self._text)
        self.refresh_theme()

    def set_status(self, text: str, tone: str = "neutral") -> None:
        """更新文字与语义色；text/tone 均未变化时不重复刷样式。"""
        tone = tone if tone in _BADGE_TONES else "neutral"
        if text == self._label and tone == self._tone:
            return
        self._label = text
        self._text.setText(text)
        if tone != self._tone:
            self._tone = tone
            self.setProperty("tone", tone)
            repolish(self)
        self.refresh_theme()

    def refresh_theme(self) -> None:
        """按当前主题重刷圆点/文字语义色；徽章底色/边框由全局 QSS 按 tone 渲染。"""
        fg = ui_color(_BADGE_TONES[self._tone])
        self._dot.setStyleSheet(f"background-color:{fg};border-radius:4px;")
        self._text.setStyleSheet(f"color:{fg};")
