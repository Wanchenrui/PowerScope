"""test_tuning_step_integration.py — 阶跃响应闭环接线 (Task 2 Slice 4)

用 fake DebugService + 真实 SafetyController + 模拟 var/updated 反馈，验证：
  触发 → 读基线 → 经 SafetyController 写阶跃(MONITORING) → 采集 → 分析回填指标 → 恢复基线(IDLE)；
  以及前置门槛拒绝(不在流/未配置)与安全停机中止。
"""
from __future__ import annotations

import math
import pytest

from power_scope.core.event_bus import EventBus, VarUpdatedEvent
from power_scope.config.device_profile import DeviceProfile
from power_scope.core.debug_service import SampleChannel
from power_scope.debug.elf_parser import encode_value, decode_value
from tests.conftest import pump_events

SP_ADDR = 0x20000100
FB_ADDR = 0x20000200


class FakeDebug:
    def __init__(self):
        self.mem = {}
        self.writes = []          # (addr, data)

    def read_memory(self, addr, size, callback=None):
        data = self.mem.get(addr, b"\x00" * size)
        if callback:
            callback({"status": 0, "payload": data[:size]})
        return 1

    def write_and_verify(self, addr, data, size, callback=None):
        self.mem[addr] = bytes(data)
        self.writes.append((addr, bytes(data)))
        if callback:
            callback(True, bytes(data))
        return 1


def _resolver(name):
    return {
        "Iref": SampleChannel("Iref", SP_ADDR, 2, "int16_t", 1.0, 0.0, "A"),
        "Ifb": SampleChannel("Ifb", FB_ADDR, 4, "float", 1.0, 0.0, "A"),
    }.get(name)


def _profile(step_max=20.0, setpoint="Iref", feedback="Ifb"):
    loop = {"id": "L1", "label": "环1",
            "params": {"Kp": "kp", "Ki": "ki", "Kd": None},
            "setpoint": setpoint, "feedback": feedback,
            "step_default": 1.0, "step_max": step_max}
    return DeviceProfile(name="t", device_type="x", version="1",
                         variables=[], control_buttons=[], status_indicators=[],
                         dashboard=[], tuning={"loops": [loop], "safety": {"limits": {}}})


def _make_view(profile, streaming=("Ifb",), sp_base=100, fb_base=5.0):
    from power_scope.ui.tuning_view import TuningView
    from power_scope.core.safety_controller import SafetyController, AnomalyCriteria
    from power_scope.core.guardrails import Guardrails
    fake = FakeDebug()
    fake.mem[SP_ADDR] = encode_value(sp_base, "int16_t")
    fake.mem[FB_ADDR] = encode_value(fb_base, "float")
    view = TuningView(profile)
    view.set_debug_service(fake)
    view.set_channel_resolver(_resolver)
    safety = SafetyController(fake, Guardrails(profile), AnomalyCriteria())
    view.set_safety_controller(safety)
    view.set_stream_check(lambda: set(streaming))
    view.set_connected(True)
    return view, fake, safety


def _sp_writes(fake):
    return [decode_value(d[:2], "int16_t") for a, d in fake.writes if a == SP_ADDR]


@pytest.fixture
def env(qapp):
    return _make_view(_profile())


def test_active_step_happy_path(env):
    view, fake, safety = env
    view._step_amp.setValue(10.0)
    view._step_dur.setValue(100)
    view._on_trigger_step()
    pump_events()

    # 阶跃已写：MONITORING，setpoint = 基线100 + 10 = 110
    assert view._step_capture is not None and view._step_capture.is_active
    assert safety.state == "MONITORING"
    assert 110 in _sp_writes(fake)

    # 注入一阶反馈响应：从 5 升到 ~15
    bus = EventBus.instance()
    for k in range(13):
        t = k * 0.01
        y = 5.0 + 10.0 * (1 - math.exp(-t / 0.025))
        bus.publish("var/updated", VarUpdatedEvent("Ifb", y, y, "A", t, "stream"))
    pump_events()

    # 采集结束 → 恢复基线 → IDLE → 指标回填
    assert view._step_capture is None
    assert safety.state == "IDLE"
    assert _sp_writes(fake)[-1] == 100                 # setpoint 已回滚到基线
    assert view._manual_rise_time.value() > 0
    assert view._manual_overshoot.value() < 5.0        # 一阶 ~0 超调


def test_refuses_when_feedback_not_streaming(qapp):
    view, fake, safety = _make_view(_profile(), streaming=())   # 流里没有 Ifb
    view._step_amp.setValue(10.0)
    view._on_trigger_step()
    pump_events()
    assert view._step_capture is None
    assert fake.writes == []                           # 没有任何写入
    assert safety.state == "IDLE"


def test_refuses_when_loop_not_configured(qapp):
    view, fake, safety = _make_view(_profile(step_max=0.0))     # 未配 step_max
    view._step_amp.setValue(10.0)
    view._on_trigger_step()
    pump_events()
    assert view._step_capture is None
    assert fake.writes == []


def test_safe_stop_aborts_active_step(env):
    view, fake, safety = env
    view._step_amp.setValue(10.0)
    view._step_dur.setValue(100)
    view._on_trigger_step()
    pump_events()
    assert view._step_capture is not None and view._step_capture.is_active

    # 模拟安全停机触发(看门狗) → 阶跃测试中止
    view._on_safety_state("SAFE_STOP")
    assert view._step_capture is None