"""test_wave_measure.py — 波形光标测量核心（P0-5）"""
from __future__ import annotations

import math

from power_scope.core.wave_measure import (
    cursor_readout, format_summary, interp_at, measure, slice_window,
)


def _first_order(n=1000, dt=0.01, tau=0.05):
    t = [i * dt for i in range(n)]
    y = [1 - math.exp(-ti / tau) for ti in t]
    return t, y


class TestInterp:
    def test_interp_linear(self):
        t = [0.0, 1.0, 2.0]
        v = [0.0, 10.0, 20.0]
        assert interp_at(t, v, 0.5) == 5.0
        assert interp_at(t, v, 0.0) == 0.0
        assert interp_at(t, v, 2.0) == 20.0

    def test_interp_out_of_range(self):
        t = [0.0, 1.0]
        v = [0.0, 1.0]
        assert interp_at(t, v, 2.0) is None
        assert interp_at(t, v, -1.0) is None

    def test_cursor_readout_clamps(self):
        t = [0.0, 1.0]
        v = [0.0, 10.0]
        inside = cursor_readout(t, v, 0.5)
        assert inside.found and inside.value == 5.0
        outside = cursor_readout(t, v, 9.0)
        assert not outside.found
        assert outside.value == 10.0


class TestSliceWindow:
    def test_slice_bounds(self):
        t, _y = _first_order()
        ts, vs = slice_window(t, [1 - math.exp(-x / 0.05) for x in t], 0.1, 0.3)
        assert abs(ts[0] - 0.1) < 1e-9
        assert abs(ts[-1] - 0.3) < 1e-9
        assert all(0.1 <= x <= 0.3 for x in ts)
        assert len(ts) == len(vs)

    def test_slice_empty(self):
        t = [0.0, 1.0]
        assert slice_window(t, [0.0, 1.0], 2.0, 3.0) == ([], [])


class TestMeasure:
    def test_first_order_rise_time(self):
        t, y = _first_order()
        m = measure(t, y, t[50], t[950], channel="resp")
        # 10%→90% 上升时间理论值 tau*ln(9) ≈ 109.86ms
        assert m.valid
        assert abs(m.rise_ms - 109.86) < 1.0
        assert abs(m.steady - 1.0) < 0.01
        assert m.overshoot_pct < 0.5        # 一阶无超调

    def test_overshoot_second_order(self):
        # 二阶欠阻尼：明显超调
        t = [i * 0.001 for i in range(2000)]
        y = [1 - math.exp(-8 * ti) * (math.cos(30 * ti) + 8 / 30 * math.sin(30 * ti))
             for ti in t]
        m = measure(t, y, 0.0, 1.5, channel="resp")
        assert m.valid
        assert m.overshoot_pct > 5.0

    def test_short_window_invalid(self):
        m = measure([0.0, 0.1], [0.0, 1.0], 0.0, 0.1)
        assert not m.valid
        assert "样本不足" in m.info

    def test_flat_window_zero_metrics(self):
        t = [i * 0.01 for i in range(100)]
        y = [5.0] * 100
        m = measure(t, y, 0.0, 1.0)
        assert not m.valid
        assert "无显著变化" in m.info

    def test_summary_contains_metrics(self):
        t, y = _first_order()
        m = measure(t, y, 0.1, 1.0, channel="Vdc")
        text = format_summary(m)
        assert "上升" in text and "调节" in text and "Vdc" in text
