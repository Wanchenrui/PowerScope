"""toast.py — 轻量浮层通知（成功/警告/错误/信息），淡入淡出后自动关闭。

与状态栏 _log_status 分级打通：✗→error, ⚠→warning, ✓→success, 其它→info。
定位在父窗口右下角，非阻塞、不抢焦点，到时后淡出关闭。
多条同时出现时自下而上堆叠，避免互相覆盖。

分级视觉：语义淡色底（ok_bg/warn_bg/fault_bg）+ 左侧 3px 同色色条 +
同色边框/文字 —— 扫一眼色块就能分级，不必读文字。
时长按文案长度自适应（2.6s ~ 8s），长错误信息也来得及读完。
"""
from PySide6.QtWidgets import QLabel
from PySide6.QtCore import Qt, QTimer, QPropertyAnimation

from ..theme import ui_color


_ICON = {"success": "✓", "warning": "⚠", "error": "✗", "info": "ℹ"}

# 每个父窗口当前可见的 Toast 列表（用于堆叠定位）: {parent_id: [Toast, ...]}
_active: dict[int, list] = {}


#: 级别 → (底色令牌, 前景/边框令牌)
#: 底色用语义淡色（ok_bg/warn_bg/fault_bg），让「扫色块」就能分级，
#: 不必读文字；这与 theme 声明的「状态指示用左侧色条」一致。
_LEVEL_TOKENS = {
    "success": ("ok_bg", "success"),
    "warning": ("warn_bg", "warning"),
    "error": ("fault_bg", "danger"),
    "info": ("accent_bg", "primary"),
}

#: 左右色条宽度（px）— 主题设计语言里的「状态指示用左侧色条」
_BAR_W = 3


def _level_colors(level: str) -> tuple[str, str]:
    """从主题语义色取 (背景, 前景/边框)。"""
    bg_key, fg_key = _LEVEL_TOKENS.get(level, _LEVEL_TOKENS["info"])
    return ui_color(bg_key), ui_color(fg_key)


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

    def __init__(self, parent, message, level="info", duration_ms=None):
        icon = _ICON.get(level, "")
        super().__init__((icon + "  " + message).strip(), parent)
        self._level = level
        bg, fg = _level_colors(level)
        self.setStyleSheet(
            f"background:{bg}; color:{fg};"
            f"border:1px solid {fg}; border-left:{_BAR_W}px solid {fg};"
            f"border-radius:6px; padding:8px 14px; font-size:13px;"
        )
        self.setWordWrap(True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setMaximumWidth(400)
        self.adjustSize()

        # 淡入淡出：动画对象终于被 start() 了（旧代码建了不用）
        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(160)
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._begin_close)
        # 时长按文案长度自适应：至少 2.6s，每个字符 +60ms，封顶 8s
        if duration_ms is None:
            duration_ms = max(2600, min(8000, 900 + 60 * len(message)))
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

    def _begin_close(self):
        """到时间后先淡出再关闭（旧行为是直接 close，没有过渡）。"""
        try:
            self._fade.setDirection(QPropertyAnimation.Backward)
            self._fade.finished.connect(self.close)
            self._fade.start()
        except Exception:
            self.close()

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
    def show_message(cls, parent, message, level="info", duration_ms=None):
        """创建并显示一条浮层通知；level 省略时按消息前缀推断。"""
        if level is None:
            level = level_from_message(message)
        t = cls(parent, message, level, duration_ms)
        t.show()
        t.raise_()
        t._fade.start()   # 淡入
        return t
