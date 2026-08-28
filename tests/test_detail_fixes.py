"""test_detail_fixes.py — 细节修复：仪表盘波形数据路径 + DebugService 挂起清理"""
from __future__ import annotations

import pytest

from power_scope.core.event_bus import VarUpdatedEvent


class TestWaveformDataPath:
    def test_on_var_event_uses_phys_and_mcu_time(self, qapp):
        from power_scope.ui.widgets.waveform import WaveformWidget
        w = WaveformWidget("t", ["Vdc"])
        w.on_var_event(VarUpdatedEvent(name="Vdc", raw_value=2300, phys_value=230.0,
                                       unit="V", timestamp=5.0))
        w.on_var_event(VarUpdatedEvent(name="Vdc", raw_value=2301, phys_value=230.1,
                                       unit="V", timestamp=6.0))
        assert w.sample_count("Vdc") == 2
        _, vals = w._series["Vdc"].windowed()
        assert vals[0] == 230.0                     # 物理量，非 raw

    def test_update_values_is_noop(self, qapp):
        from power_scope.ui.widgets.waveform import WaveformWidget
        w = WaveformWidget("t", ["Vdc"])
        w.update_values({"Vdc": 999})
        assert w.sample_count("Vdc") == 0           # 不再经 update_values 重复加点

    def test_unrelated_var_ignored(self, qapp):
        from power_scope.ui.widgets.waveform import WaveformWidget
        w = WaveformWidget("t", ["Vdc"])
        w.on_var_event(VarUpdatedEvent(name="Id", raw_value=1, phys_value=1.0,
                                       unit="A", timestamp=1.0))
        assert w.sample_count("Vdc") == 0


class TestClearPending:
    def test_clear_pending(self, qapp):
        from power_scope.core.debug_service import DebugService
        svc = DebugService(writer=lambda b: None)
        svc.read_memory(0x20000000, 4, callback=lambda r: None)
        svc.feed(b"\xA5")             # 残留半帧
        assert svc._pending and svc._buf
        svc.clear_pending()
        assert not svc._pending
        assert not svc._buf
