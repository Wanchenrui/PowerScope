"""history_line_edit.py — 带 ↑↓ 历史的单行输入（P1-9 发送增强）

排帧时要反复手搓同一帧。HistoryLineEdit 用 ↑/↓ 在已发送历史里回溯
（最新在上），Home/End 或编辑后退出回溯态，行为与终端/IDE 控制台一致。

纯 Qt 交互，无业务依赖；历史由调用方经 push_history() 追加。
"""
from __future__ import annotations

from collections import deque

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLineEdit


class HistoryLineEdit(QLineEdit):
    """支持 ↑↓ 历史回溯的输入框。"""

    def __init__(self, parent=None, capacity: int = 100):
        super().__init__(parent)
        self._history: deque[str] = deque(maxlen=capacity)
        self._cursor = -1        # -1 = 不在历史回溯态

    def push_history(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        if not self._history or self._history[0] != text:
            self._history.appendleft(text)
        self._cursor = -1

    def history(self) -> list[str]:
        return list(self._history)

    def clear_history(self) -> None:
        self._history.clear()
        self._cursor = -1

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key_Up:
            if self._history:
                self._cursor = min(self._cursor + 1, len(self._history) - 1)
                self.setText(self._history[self._cursor])
            event.accept()
            return
        if key == Qt.Key_Down:
            if self._history:
                if self._cursor <= 0:
                    self._cursor = -1
                    self.clear()
                else:
                    self._cursor -= 1
                    self.setText(self._history[self._cursor])
            event.accept()
            return
        super().keyPressEvent(event)
        # 任何产生文本的按键退出回溯态（与终端一致：改字后 ↑ 从最新开始）
        if event.text():
            self._cursor = -1
