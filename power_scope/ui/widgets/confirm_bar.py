"""confirm_bar.py — 视图内 inline 确认条（P0-3）

Feedback 门面规定「模态仅用于破坏性确认」，但调参写入 / 变量写入是高频
操作，每次弹 QMessageBox.question 会打断流式监控，且模态嵌套事件循环
历史上正是 USB 拔出崩溃的根因。

确认条把确认放进发生操作的视图内：警告图标 + 待写入内容预览 +
[确认] [取消]，不阻断轮询与日志滚动。用法::

    bar = ConfirmBar(host_layout)          # 插入到布局
    bar.confirmed.connect(self._do_write)
    bar.cancelled.connect(lambda: self._log("已取消"))
    bar.ask("确认写入", f"Kp = 0.85？")
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QWidget,
)

from ..theme import radius, ui_color


class ConfirmBar(QFrame):
    """inline 确认条：默认隐藏，ask() 时显示并排到宿主布局顶部。"""

    confirmed = Signal()
    cancelled = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("confirm_bar")
        self.setFrameShape(QFrame.StyledPanel)
        self._build()
        self.hide()

    # ---- UI ----
    def _build(self):
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(8)

        self._icon = QLabel("⚠")
        self._icon.setStyleSheet(
            f"color:{ui_color('warning')};font-size:14px;font-weight:bold;")
        lay.addWidget(self._icon)

        self._text = QLabel("")
        self._text.setWordWrap(True)
        self._text.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        lay.addWidget(self._text, 1)

        self._yes = QPushButton("确认")
        self._yes.setObjectName("btn_warning")
        self._yes.setMinimumWidth(72)
        self._yes.clicked.connect(self._on_yes)
        lay.addWidget(self._yes)

        self._no = QPushButton("取消")
        self._no.setMinimumWidth(72)
        self._no.clicked.connect(self._on_no)
        lay.addWidget(self._no)

        self._apply_style()

    def _apply_style(self):
        warn = ui_color("warning")
        self.setStyleSheet(
            f"QFrame#confirm_bar {{ background-color:{ui_color('warn_bg')};"
            f"border:1px solid {warn}; border-left:4px solid {warn};"
            f"border-radius:{radius('card')}; }}"
            f"QLabel {{ background:transparent; color:{ui_color('text')}; }}"
        )

    def apply_theme(self, _theme_name=None):
        """主题切换后重新解析语义色。"""
        self._apply_style()

    # ---- 交互 ----
    def ask(self, title: str, detail: str = "", yes_text: str = "确认",
            no_text: str = "取消") -> None:
        """展示确认请求（detail 可多行）。"""
        text = title if not detail else f"{title}\n{detail}"
        self._text.setText(text)
        self._yes.setText(yes_text)
        self._no.setText(no_text)
        self.show()
        self._yes.setFocus(Qt.OtherFocusReason)

    def ask_with_warnings(self, title: str, lines: list[str],
                          warnings: list[str] | None = None,
                          yes_text: str = "确认写入",
                          no_text: str = "取消") -> None:
        """带护栏修正提示的确认（warnings 会在下方以 ⚠ 列出）。"""
        body = "\n".join(lines)
        if warnings:
            body += "\n\n⚠ 安全护栏修正:\n" + "\n".join(warnings)
        self.ask(title, body, yes_text, no_text)

    def _on_yes(self):
        self.hide()
        self.confirmed.emit()

    def _on_no(self):
        self.hide()
        self.cancelled.emit()

    def is_pending(self) -> bool:
        return self.isVisible()
