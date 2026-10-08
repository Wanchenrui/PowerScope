"""connect_button.py — 连接按钮（状态驱动配色）

旧实现用「改 objectName + unpolish/polish」切换配色：
  - 每次状态变化触发全量样式重算，视觉上可能闪烁；
  - 漏一处 unpolish/polish 就出现"文字变了颜色没变"；
  - connected/disconnected/error 三个分支各写一遍，共 6 处重复。

改为动态属性 state + QSS 属性选择器：一次 polish 全局生效，状态与配色
的对应关系集中在一处 QSS 里，新增状态不用改 Python。
"""
from __future__ import annotations

from PySide6.QtWidgets import QPushButton

#: 状态 → (按钮文字, 是否可用)
STATES = {
    "idle": ("连接", True),
    "connecting": ("连接中...", False),
    "connected": ("断开", True),
    "retry": ("取消重连", True),
}


class ConnectButton(QPushButton):
    """连接/断开按钮，配色由 state 动态属性驱动。"""

    def __init__(self, text: str = "连接", parent=None):
        super().__init__(text, parent)
        self._state = "idle"
        self.set_state("idle")

    @property
    def state(self) -> str:
        return self._state

    def set_state(self, state: str, text: str | None = None) -> None:
        """切换状态；text 省略时用该状态的默认文字。"""
        if state not in STATES:
            state = "idle"
        self._state = state
        default_text, enabled = STATES[state]
        self.setText(text if text is not None else default_text)
        self.setEnabled(enabled)
        self.setProperty("state", state)
        # 动态属性需要一次 unpolish/polish 才能让 QSS 属性选择器生效
        self.style().unpolish(self)
        self.style().polish(self)
