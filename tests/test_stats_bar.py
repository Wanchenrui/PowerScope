"""test_stats_bar.py — 状态条组件 (问题4二期)"""
from __future__ import annotations

import pytest


class TestStatsBar:
    def test_update_stats_sets_text(self, qapp):
        from power_scope.ui.widgets.stats_bar import StatsBarWidget
        w = StatsBarWidget()
        w.update_stats(
            {"frames_ok": 5, "crc_errors": 2, "var_updates": 9},
            connected=True, rate_bps=2048)
        assert "已连接" in w._conn.text()
        assert "5" in w._frames.text()
        assert "2" in w._crc.text()
        assert "9" in w._vars.text()
        assert "KB/s" in w._rate.text()

    def test_disconnected_default(self, qapp):
        from power_scope.ui.widgets.stats_bar import StatsBarWidget
        w = StatsBarWidget()
        w.update_stats({}, connected=False)
        assert "未连接" in w._conn.text()
        assert "0" in w._frames.text()

    def test_rate_formatting_bytes(self, qapp):
        from power_scope.ui.widgets.stats_bar import StatsBarWidget
        w = StatsBarWidget()
        w.update_stats({}, connected=True, rate_bps=512)
        assert "B/s" in w._rate.text() and "KB" not in w._rate.text()
