"""test_step_capture.py — StepCaptureController (Task 2 Slice 3)"""
from __future__ import annotations

import pytest

from power_scope.core.event_bus import EventBus, VarUpdatedEvent
from tests.conftest import pump_events


def _evt(name, t, v):
    return VarUpdatedEvent(name=name, raw_value=v, phys_value=v, unit="",
                           timestamp=t, source="stream")


@pytest.fixture
def make_cap(qapp):
    from power_scope.core.step_capture import StepCaptureController
    return StepCaptureController


def test_records_named_channel_until_duration(make_cap):
    cap = make_cap("Iout", duration_s=0.1)
    done = []
    cap.finished.connect(lambda s: done.append(s))
    cap.start()
    bus = EventBus.instance()
    for k in range(13):
        bus.publish("var/updated", _evt("Iout", k * 0.01, float(k)))
        bus.publish("var/updated", _evt("Other", k * 0.01, 999.0))
    pump_events()
    assert len(done) == 1
    samples = done[0]
    assert samples[0] == (0.0, 0.0)
    assert samples[-1][0] == pytest.approx(0.10)        # 跨度达 0.1s 收尾
    assert all(v != 999.0 for _, v in samples)          # 其它通道被忽略
    assert not cap.is_active


def test_mark_step_uses_last_sample_time(make_cap):
    cap = make_cap("Iout", duration_s=10.0)             # 不会自动收尾
    cap.start()
    bus = EventBus.instance()
    bus.publish("var/updated", _evt("Iout", 1.00, 5.0))
    bus.publish("var/updated", _evt("Iout", 1.02, 5.0))
    pump_events()
    cap.mark_step()
    assert cap.t_step == pytest.approx(1.02)


def test_stop_prevents_finish_and_recording(make_cap):
    cap = make_cap("Iout", duration_s=0.1)
    done = []
    cap.finished.connect(lambda s: done.append(s))
    cap.start()
    cap.stop()
    EventBus.instance().publish("var/updated", _evt("Iout", 0.0, 1.0))
    pump_events()
    assert done == []
    assert cap.samples == []
    assert not cap.is_active


def test_only_feedback_channel_recorded(make_cap):
    cap = make_cap("Vfb", duration_s=10.0)
    cap.start()
    bus = EventBus.instance()
    bus.publish("var/updated", _evt("Iout", 0.0, 1.0))
    bus.publish("var/updated", _evt("Vfb", 0.0, 2.0))
    bus.publish("var/updated", _evt("Vfb", 0.01, 3.0))
    pump_events()
    assert cap.samples == [(0.0, 2.0), (0.01, 3.0)]