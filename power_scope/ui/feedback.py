"""feedback.py — 统一的状态反馈门面

旧问题：同类错误在不同视图有 3~4 种呈现，用户学不到规律：
  - 连接失败 → 状态栏文字 + Toast
  - 串口打开异常 → QMessageBox.critical（模态，会打断流式监控）
  - Hex 格式错误 → 系统日志 + QMessageBox.warning（又是模态）
  - 调参失败 → 结果文本框 append

本模块按「是否阻塞用户当前任务」选呈现方式，四个等级：
  status  状态栏一行（默认，瞬时信息）
  toast   右下角浮层（需要注意到、但不打断）
  inline  视图内的固定区域（长文本/结果列表）
  dialog  模态对话框（仅用于必须阻断的确认，如破坏性操作前）

用法::

    fb = Feedback(parent_window)
    fb.status("✓ 已连接 (COM4 @ 115200)")
    fb.toast("✗ 连接失败: 拒绝访问")
    fb.confirm("确认写入", "将 Kp 写入 1.20？", on_yes=...)
"""
from __future__ import annotations

from PySide6.QtWidgets import QMessageBox, QWidget

from .widgets.toast import Toast


class Feedback:
    """挂在某个父窗口上的反馈门面。"""

    def __init__(self, parent: QWidget | None = None):
        self._parent = parent

    # ---- 瞬时信息 → 状态栏 ----
    def status(self, message: str, timeout_ms: int = 5000) -> None:
        if self._parent is None:
            return
        bar = self._parent.statusBar()
        if bar is not None:
            bar.showMessage(message, timeout_ms)

    # ---- 需要注意到、但不打断 → Toast ----
    def toast(self, message: str, level: str | None = None,
              duration_ms: int | None = None) -> None:
        if self._parent is None:
            return
        Toast.show_message(self._parent, message, level, duration_ms)

    # ---- 分级推送：按前缀自动选 status / toast ----
    def report(self, message: str) -> None:
        """状态消息统一入口：✓→success toast，✗→error toast，⚠→warning toast，
        其它→状态栏。替代散落在各视图的 if/else。"""
        from .widgets.toast import level_from_message
        level = level_from_message(message)
        if level in ("error", "warning", "success"):
            self.toast(message, level)
        self.status(message)

    # ---- 必须阻断的确认 → 模态对话框（仅破坏性操作）----
    def confirm(self, title: str, text: str, on_yes=None,
                yes_text: str = "确定", no_text: str = "取消") -> bool:
        if self._parent is None:
            return False
        box = QMessageBox(self._parent)
        box.setWindowTitle(title)
        box.setText(text)
        box.setIcon(QMessageBox.Question)
        yes = box.addButton(yes_text, QMessageBox.YesRole)
        box.addButton(no_text, QMessageBox.NoRole)
        box.setDefaultButton(yes)
        box.exec()
        accepted = box.clickedButton() is yes
        if accepted and on_yes is not None:
            on_yes()
        return accepted

    def alert(self, title: str, text: str, level: str = "warning") -> None:
        """错误提示 —— 同时进状态栏与 Toast，不弹模态（模态会打断流式监控）。"""
        icon = {"warning": QMessageBox.Warning,
                "error": QMessageBox.Critical,
                "info": QMessageBox.Information}.get(level, QMessageBox.Warning)
        if self._parent is not None:
            box = QMessageBox(self._parent)
            box.setWindowTitle(title)
            box.setText(text)
            box.setIcon(icon)
            box.addButton("确定", QMessageBox.AcceptRole)
            box.exec()
        self.toast(f"{title}: {text}",
                   "error" if level == "error" else "warning")
