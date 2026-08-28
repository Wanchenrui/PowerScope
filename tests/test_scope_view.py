"""test_scope_view.py — 示波器视图 (Problem 3/1)"""
from __future__ import annotations

import pytest

from power_scope.core.event_bus import EventBus, VarUpdatedEvent
from tests.conftest import pump_events


@pytest.fixture
def scope(qapp):
    from power_scope.ui.scope_view import ScopeView
    return ScopeView()


class TestScopeView:
    def test_add_channel_emits_and_plots(self, scope):
        scope.set_available_variables(["Vdc", "Id"])
        emitted = []
        scope.channels_added.connect(lambda names: emitted.append(list(names)))
        scope.add_channels_external(["Vdc"])
        assert "Vdc" in scope.plotted_channels()
        assert emitted and "Vdc" in emitted[0]

    def test_var_updated_routes_only_to_added_channels(self, scope):
        scope.add_channels_external(["Vdc"])
        EventBus.instance().publish("var/updated", VarUpdatedEvent(
            name="Vdc", raw_value=2300, phys_value=230.0, unit="V", timestamp=1.0))
        EventBus.instance().publish("var/updated", VarUpdatedEvent(
            name="Id", raw_value=1, phys_value=3.0, unit="A", timestamp=1.0))
        pump_events()
        assert scope._plot.sample_count("Vdc") == 1
        assert scope._plot.sample_count("Id") == 0     # 未添加 → 不绘

    def test_remove_channel_emits(self, scope):
        scope.add_channels_external(["Vdc"])
        removed = []
        scope.channels_removed.connect(lambda names: removed.append(list(names)))
        # 模拟在“当前通道”列表中选中并移除
        scope._chan_list.item(0).setSelected(True)
        scope._on_remove_selected()
        assert "Vdc" not in scope.plotted_channels()
        assert removed and "Vdc" in removed[0]

    def test_filter_available(self, scope):
        from PySide6.QtTest import QTest
        scope.set_available_variables(["g_vdc", "g_id", "g_freq"])
        scope._search.setText("id")
        QTest.qWait(250)  # 搜索为 150ms 防抖，等待合并触发
        names = [scope._avail_list.item(i).text() for i in range(scope._avail_list.count())]
        assert names == ["g_id"]

    def test_pause_blocks_plotting(self, scope):
        scope.add_channels_external(["Vdc"])
        scope._pause_btn.setChecked(True)
        EventBus.instance().publish("var/updated", VarUpdatedEvent(
            name="Vdc", raw_value=1, phys_value=1.0, unit="V", timestamp=1.0))
        pump_events()
        assert scope._plot.sample_count("Vdc") == 0
