"""test_lifecycle.py — MainWindow 定时器/订阅生命周期，杜绝模拟定时器跨测试泄漏"""
from __future__ import annotations

import pytest

from power_scope.config.device_profile import DeviceProfile
from power_scope.core.event_bus import EventBus
from tests.conftest import pump_events


def _mw(qapp):
    from power_scope.ui.main_window import MainWindow
    return MainWindow(DeviceProfile(name="t", device_type="x", version="1"))


class TestCleanup:
    def test_cleanup_stops_both_timers(self, qapp):
        mw = _mw(qapp)
        mw._session.connect_mock()              # 启动模拟定时器（经队列事件）
        pump_events()
        assert mw._sim_timer.isActive()
        mw._cleanup()
        assert not mw._sim_timer.isActive()
        assert not mw._stats_timer.isActive()

    def test_cleanup_unsubscribes_eventbus(self, qapp):
        mw = _mw(qapp)
        bus = EventBus.instance()
        assert mw._on_connection_state in bus._subscribers.get("connection/state", [])
        assert mw._on_elf_loaded in bus._subscribers.get("elf/loaded", [])
        mw._cleanup()
        assert mw._on_connection_state not in bus._subscribers.get("connection/state", [])
        assert mw._on_elf_loaded not in bus._subscribers.get("elf/loaded", [])

    def test_close_stops_timers(self, qapp):
        mw = _mw(qapp)
        mw._session.connect_mock()
        pump_events()
        assert mw._sim_timer.isActive()
        mw.close()
        assert not mw._sim_timer.isActive()
        assert not mw._stats_timer.isActive()

    def test_closed_window_does_not_publish_after_reset(self, qapp):
        """复现并验证修复：关闭后即使复位 EventBus，遗留定时器也不再 publish。"""
        import time
        from PySide6.QtCore import QCoreApplication
        mw = _mw(qapp)
        mw._session.connect_mock()
        pump_events()
        assert mw._sim_timer.isActive()         # 确认定时器确实在跑
        mw.close()                              # closeEvent → _cleanup 停定时器
        # 模拟下一个测试：复位 EventBus 并订阅探针
        EventBus._instance = None
        bus = EventBus.instance()
        bus._reset_for_test()
        received = []
        bus.subscribe("var/updated", received.append)
        # 跨过 200ms 模拟定时器周期
        end = time.time() + 0.35
        while time.time() < end:
            QCoreApplication.processEvents()
            time.sleep(0.01)
        assert received == []                   # 不再有遗留 var/updated
