"""toast.py — 轻量浮层通知（成功/警告/错误/信息），自动淡出消失。

与状态栏 _log_status 分级打通：✗→error, ⚠→warning, ✓→success, 其它→info。
定位在父窗口右下角，非阻塞、不抢焦点，duration 后自动关闭。
多条同时出现时自下而上堆叠，避免互相覆盖。
"""
from PySide6.QtWidgets import QLabel
from PySide6.QtCore import Qt, QTimer, QPropertyAnimation

from ..theme import ui_color


_ICON = {"success": "✓", "warning": "⚠", "error": "✗", "info": "ℹ"}

# 每个父窗口当前可见的 Toast 列表（用于堆叠定位）: {parent_id: [Toast, ...]}
_active: dict[int, list] = {}


def _level_colors(level: str) -> tuple[str, str]:
    """从主题语义色取 (背景, 前景/边框)。"""
    fg = {
        "success": ui_color("success"),
        "warning": ui_color("warning"),
        "error": ui_color("danger"),
        "info": ui_color("primary"),
    }.get(level, ui_color("primary"))
    # 背景用主表面色，前景色做 1px 边框，风格与 theme「1px 分割线」一致
    return ui_color("surface"), fg


def level_from_message(msg: str) -> str:
    """按状态消息前缀推断级别（与 _log_status 一致）。"""
    m = (msg or "").lstrip()
    if m.startswith("✗"):
        return "error"
    if m.startswith("⚠"):
        return "warning"
    if m.startswith("✓"):
        return "success"
    return "info"


class Toast(QLabel):
    """单条浮层通知。用 Toast.show_message(parent, msg, level) 调用。"""

    MAX_VISIBLE = 5  # 同一父窗口最多堆叠条数，超出时最旧的提前关闭

    def __init__(self, parent, message, level="info", duration_ms=3200):
        icon = _ICON.get(level, "")
        super().__init__((icon + "  " + message).strip(), parent)
        self._level = level
        bg, fg = _level_colors(level)
        self.setStyleSheet(
            f"background:{bg}; color:{fg}; border:1px solid {fg};"
            f"border-radius:6px; padding:8px 14px; font-size:13px;"
        )
        self.setWordWrap(True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setMaximumWidth(380)
        self.adjustSize()

        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.close)
        self._timer.start(duration_ms)

        # 登记到活动列表并重新布局堆叠
        key = id(parent)
        lst = _active.setdefault(key, [])
        lst.append(self)
        while len(lst) > self.MAX_VISIBLE:
            oldest = lst.pop(0)
            oldest._timer.stop()
            oldest.close()
        self._restack(parent)

    def _restack(self, parent):
        """自下而上重新摆放该父窗口的所有 Toast。"""
        margin = 20
        y = parent.height() - margin - 28  # 让开状态栏
        for t in reversed(_active.get(id(parent), [])):
            if not t.isVisible() and t is not self:
                continue
            y -= t.height()
            x = parent.width() - t.width() - margin
            t.move(max(0, x), max(0, y))
            y -= 8  # 条间距

    def closeEvent(self, event):
        p = self.parentWidget()
        lst = _active.get(id(p)) if p is not None else None
        if lst and self in lst:
            lst.remove(self)
            if p is not None:
                self._restack(p)
        super().closeEvent(event)

    @property
    def level(self) -> str:
        return self._level

    @classmethod
    def show_message(cls, parent, message, level="info", duration_ms=3200):
        """创建并显示一条浮层通知；level 省略时按消息前缀推断。"""
        if level is None:
            level = level_from_message(message)
        t = cls(parent, message, level, duration_ms)
        t.show()
        t.raise_()
        return t
