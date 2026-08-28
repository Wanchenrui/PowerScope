"""test_streaming_manager.py — 阶段5 采样通道管理纯逻辑"""
import pytest
from power_scope.core.streaming_manager import StreamingManager


class Ch:
    def __init__(self, name): self.name = name

class Var:
    def __init__(self, rate): self.update_rate = rate


def test_slow_and_scope_channel_sets_are_separate():
    m = StreamingManager()
    m.set_profile_channels([Ch("a"), Ch("b")])
    assert set(m.stream_set()) == {"a", "b"}
    assert m.add_extra("c", Ch("c")) is True
    assert m.add_extra("c", Ch("c")) is False   # 重复加入返回 False
    assert set(m.stream_set()) == {"a", "b"}
    assert set(m.scope_set()) == {"c"}
    assert m.add_monitor("d", Ch("d")) is True
    assert set(m.stream_set()) == {"a", "b", "d"}
    assert m.remove_monitor("d") is True
    assert m.remove_extra("c") is True
    assert m.remove_extra("c") is False
    assert set(m.stream_set()) == {"a", "b"}


def test_channel_list_truncation():
    m = StreamingManager()
    m.set_profile_channels([Ch(f"c{i}") for i in range(40)])
    chans, truncated = m.channel_list()
    assert truncated is True and len(chans) == StreamingManager.MAX_CHANNELS
    m2 = StreamingManager()
    m2.set_profile_channels([Ch("x")])
    chans2, t2 = m2.channel_list()
    assert t2 is False and len(chans2) == 1


def test_compute_period_us():
    assert StreamingManager.compute_period_us([Var(10), Var(50), Var(0)]) == 10000
    assert StreamingManager.compute_period_us([]) == 20000       # 默认 20ms
    assert StreamingManager.compute_period_us([Var(1)]) == 1000  # 下限 100us 之上
    assert StreamingManager.compute_period_us([Var(100)]) == 65535  # 上限钳制
