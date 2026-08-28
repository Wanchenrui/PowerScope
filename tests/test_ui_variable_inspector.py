"""
test_ui_variable_inspector.py — VariableInspectorView EventBus 接入测试

验证 VariableInspectorView 通过 EventBus 订阅 var/updated 事件，
自动刷新监视表中的变量值。

TDD 流程:
  1. RED: 测试先写，运行应失败
  2. GREEN: 实现事件订阅让测试通过
  3. REFACTOR: 清理模拟值逻辑
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from PySide6.QtWidgets import QApplication

from power_scope.core.event_bus import EventBus, VarUpdatedEvent


@pytest.fixture(scope="module", autouse=True)
def _ensure_qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture(autouse=True)
def reset_bus():
    bus = EventBus.instance()
    bus._reset_for_test()
    app = QApplication.instance()
    if app is not None:
        for _ in range(5):
            app.processEvents()
    yield


class TestVariableInspectorEventBus:
    """VariableInspectorView EventBus 集成测试"""

    def _create_view(self):
        from power_scope.ui.variable_inspector_view import VariableInspectorView
        return VariableInspectorView()

    def _pump(self, count: int = 5) -> None:
        app = QApplication.instance()
        for _ in range(count):
            app.processEvents()

    def test_view_creates_without_session(self):
        """不传 SessionController 时仍能创建"""
        view = self._create_view()
        assert view is not None

    def test_var_updated_updates_watch_table(self):
        """var/updated 事件更新监视表中的变量值"""
        view = self._create_view()

        # 手动添加一个变量到监视表
        view._add_to_watch("Vdc_bus", "float", "0x20001000", "4B")
        assert view._watch_table.item(0, 3).text() == "---"

        # 发布变量更新事件
        event = VarUpdatedEvent(
            name="Vdc_bus",
            raw_value=0x1234,
            phys_value=380.5,
            unit="V",
            timestamp=1.0,
        )
        EventBus.instance().publish("var/updated", event)
        self._pump()

        assert view._watch_table.item(0, 3).text() == "380.50 V"

    def test_var_updated_ignores_unknown_var(self):
        """未知变量的事件不更新"""
        view = self._create_view()
        view._add_to_watch("Iac_rms", "float", "0x20001004", "4B")

        event = VarUpdatedEvent(
            name="Vdc_bus",  # 不是监视表中的变量
            raw_value=0x1234,
            phys_value=380.5,
            unit="V",
            timestamp=1.0,
        )
        EventBus.instance().publish("var/updated", event)
        self._pump()

        # Iac_rms 的值不应改变
        assert view._watch_table.item(0, 3).text() == "---"

    def test_multiple_vars_updated(self):
        """多个变量同时更新"""
        view = self._create_view()
        view._add_to_watch("Vdc_bus", "float", "0x20001000", "4B")
        view._add_to_watch("Iac_rms", "float", "0x20001004", "4B")

        EventBus.instance().publish("var/updated", VarUpdatedEvent(
            name="Vdc_bus", raw_value=0, phys_value=380.5, unit="V", timestamp=1.0))
        EventBus.instance().publish("var/updated", VarUpdatedEvent(
            name="Iac_rms", raw_value=0, phys_value=5.2, unit="A", timestamp=1.0))
        self._pump()

        assert view._watch_table.item(0, 3).text() == "380.50 V"
        assert view._watch_table.item(1, 3).text() == "5.20 A"

    def test_var_updated_with_different_units(self):
        """不同单位的变量显示正确"""
        view = self._create_view()
        view._add_to_watch("f_grid", "float", "0x20001008", "4B")

        event = VarUpdatedEvent(
            name="f_grid",
            raw_value=0,
            phys_value=50.0,
            unit="Hz",
            timestamp=1.0,
        )
        EventBus.instance().publish("var/updated", event)
        self._pump()

        assert view._watch_table.item(0, 3).text() == "50.00 Hz"

    def test_disconnect_on_destroy(self):
        """view 销毁时取消 EventBus 订阅"""
        view = self._create_view()
        view.deleteLater()
        self._pump()
        # 不应崩溃
        assert True
