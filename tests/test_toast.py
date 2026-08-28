"""test_toast.py — 浮层通知组件"""
import pytest
from power_scope.ui.widgets.toast import Toast, level_from_message


def test_level_from_message():
    assert level_from_message("✗ 连接失败") == "error"
    assert level_from_message("⚠ 限幅") == "warning"
    assert level_from_message("✓ 已连接") == "success"
    assert level_from_message("→ 读取中") == "info"
    assert level_from_message("") == "info"


def test_toast_construct_and_close(qapp):
    from PySide6.QtWidgets import QWidget
    parent = QWidget()
    parent.resize(800, 600)
    t = Toast.show_message(parent, "测试消息", "warning", duration_ms=50)
    assert t.level == "warning"
    assert "测试消息" in t.text()
    assert t.isVisibleTo(parent)
    parent.deleteLater()


def test_toast_infers_level(qapp):
    from PySide6.QtWidgets import QWidget
    parent = QWidget(); parent.resize(400, 300)
    t = Toast.show_message(parent, "✗ 出错了", level=None, duration_ms=50)
    assert t.level == "error"
    parent.deleteLater()
