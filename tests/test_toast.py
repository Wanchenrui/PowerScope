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


def test_toast_opacity_resize_and_fade_out(qapp):
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QGraphicsOpacityEffect, QWidget
    from power_scope.ui.widgets.toast import _active

    parent = QWidget()
    parent.resize(700, 500)
    parent.show()
    toast = Toast.show_message(parent, "连接已经断开", "warning", duration_ms=5000)
    assert isinstance(toast.graphicsEffect(), QGraphicsOpacityEffect)
    QTest.qWait(200)
    assert toast._opacity.opacity() > 0.99
    original_x = toast.x()
    parent.resize(460, 320)
    qapp.processEvents()
    assert toast.x() < original_x
    assert toast.x() + toast.width() <= parent.width() - 8
    toast._fade_out()
    QTest.qWait(230)
    assert parent not in _active
    parent.close()


def test_toast_stack_is_bounded(qapp):
    from PySide6.QtWidgets import QWidget
    from power_scope.ui.widgets.toast import _active

    parent = QWidget()
    parent.resize(600, 400)
    toasts = [Toast.show_message(parent, f"消息 {index}", duration_ms=5000)
              for index in range(7)]
    assert len(_active[parent]) == Toast.MAX_VISIBLE
    for toast in list(_active[parent]):
        toast.close()
    assert parent not in _active
    parent.deleteLater()


def test_toast_does_not_duplicate_level_prefix(qapp):
    from PySide6.QtWidgets import QWidget

    parent = QWidget()
    toast = Toast.show_message(parent, "⚠ 参数已限幅", level=None, duration_ms=5000)
    assert toast.text().count("⚠") == 1
    assert "参数已限幅" in toast.text()
    toast.close()
    parent.deleteLater()
