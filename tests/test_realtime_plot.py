"""test_realtime_plot.py — 动态多通道实时波形组件 (Problem 3)"""
from __future__ import annotations

import pytest


@pytest.fixture
def plot(qapp):
    from power_scope.ui.widgets.realtime_plot import RealtimePlotWidget
    return RealtimePlotWidget(time_window=5.0, max_points=100)


class TestChannels:
    def test_add_remove(self, plot):
        plot.add_channel("Vdc")
        plot.add_channel("Id")
        assert set(plot.channel_names()) == {"Vdc", "Id"}
        plot.remove_channel("Vdc")
        assert plot.channel_names() == ["Id"]

    def test_add_duplicate_noop(self, plot):
        c1 = plot.add_channel("Vdc")
        plot.add_channel("Vdc")
        assert plot.channel_names() == ["Vdc"]
        assert plot.channel_color("Vdc") == c1

    def test_distinct_colors(self, plot):
        a = plot.add_channel("A")
        b = plot.add_channel("B")
        assert a != b

    def test_clear_channels(self, plot):
        plot.add_channel("A"); plot.add_channel("B")
        plot.clear_channels()
        assert plot.channel_names() == []


class TestData:
    def test_add_sample_uses_relative_mcu_time(self, plot):
        plot.add_channel("Vdc")
        plot.add_sample("Vdc", 1000.0, 1.0)   # t0
        plot.add_sample("Vdc", 1001.0, 2.0)
        assert plot.sample_count("Vdc") == 2

    def test_sample_to_unknown_channel_ignored(self, plot):
        plot.add_sample("ghost", 1.0, 5.0)
        assert plot.sample_count("ghost") == 0

    def test_pause_stops_accumulation(self, plot):
        plot.add_channel("Vdc")
        plot.add_sample("Vdc", 1.0, 1.0)
        plot.set_paused(True)
        plot.add_sample("Vdc", 2.0, 2.0)
        assert plot.sample_count("Vdc") == 1
        plot.set_paused(False)
        plot.add_sample("Vdc", 3.0, 3.0)
        assert plot.sample_count("Vdc") == 2

    def test_sliding_window_drops_old(self, plot):
        plot.add_channel("Vdc")
        for i in range(20):           # time_window=5s, dt=1s → 只保留约最近 6 点
            plot.add_sample("Vdc", float(i), float(i))
        assert plot.sample_count("Vdc") <= 7

    def test_clear_data_keeps_channels(self, plot):
        plot.add_channel("Vdc")
        plot.add_sample("Vdc", 1.0, 1.0)
        plot.clear_data()
        assert plot.channel_names() == ["Vdc"]
        assert plot.sample_count("Vdc") == 0


class TestExport:
    def test_export_csv(self, plot, tmp_path):
        plot.add_channel("Vdc")
        plot.add_sample("Vdc", 10.0, 1.5)
        plot.add_sample("Vdc", 11.0, 2.5)
        out = tmp_path / "scope.csv"
        plot.export_csv(str(out))
        lines = out.read_text(encoding="utf-8").strip().splitlines()
        assert lines[0] == "channel,t_seconds,value"
        assert any("Vdc" in l and "1.5" in l for l in lines[1:])
        assert len(lines) == 3
