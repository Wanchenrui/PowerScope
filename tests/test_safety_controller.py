"""SafetyController — 写入、监测、分级回退与安全停机。"""
from __future__ import annotations

from power_scope.core.debug_service import SampleChannel
from power_scope.core.event_bus import VarUpdatedEvent
from power_scope.core.guardrails import Guardrails


class FakeDebug:
    def __init__(self, fail_addresses=()):
        self.fail_addresses = set(fail_addresses)
        self.writes = []
        self.controls = []
        self.memory = {}

    def write_and_verify(self, address, data, size, callback=None):
        self.writes.append((address, bytes(data), size))
        ok = address not in self.fail_addresses
        if callback:
            callback(ok, bytes(data) if ok else b"")
        return len(self.writes)

    def read_memory(self, address, size, callback=None):
        data = self.memory.get(address, b"\x00" * size)
        if callback:
            callback({"status": 0, "payload": data})
        return 1

    def device_control(self, running, callback=None):
        self.controls.append(bool(running))
        if callback:
            callback({"status": 0, "payload": b""})
        return 1


def channel(name, address):
    return SampleChannel(name, address, 4, "float")


def controller(clock, fail=()):
    from power_scope.core.safety_controller import AnomalyCriteria, SafetyController
    guard = Guardrails()
    guard.record("kp", 1.0)
    guard.record("ki", 2.0)
    debug = FakeDebug(fail)
    criteria = AnomalyCriteria(
        limits={"output": (0.0, 10.0)}, fault_vars={"fault"},
        severe_ratio=2.0, comms_timeout_s=1.0, window_s=5.0)
    ctrl = SafetyController(debug, guard, criteria, clock=lambda: clock[0])
    params = [("kp", channel("kp", 0x20000100), 1.5),
              ("ki", channel("ki", 0x20000104), 2.5)]
    return ctrl, debug, guard, params


def event(name, value):
    return VarUpdatedEvent(name, value, float(value), "", 0.0)


def test_begin_success_enters_monitoring_with_guardrail_anchors(qapp):
    ctrl, debug, _guard, params = controller([0.0])
    assert ctrl.begin(params) is True
    assert ctrl.state == "MONITORING"
    assert len(debug.writes) == 2
    assert ctrl.anchors == {"kp": 1.0, "ki": 2.0}


def test_uncertain_write_failure_restores_attempted_item_and_escalates_if_needed(qapp):
    ctrl, debug, _guard, params = controller([0.0], fail={0x20000104})
    ctrl.begin(params)
    assert ctrl.state == "SAFE_STOP"
    assert [call[0] for call in debug.writes] == [
        0x20000100, 0x20000104, 0x20000100, 0x20000104]
    assert debug.controls == [False]


def test_window_timeout_commits_new_baseline(qapp):
    now = [0.0]
    ctrl, _debug, guard, params = controller(now)
    ctrl.begin(params)
    ctrl._on_var_updated(event("output", 5.0))
    now[0] = 5.1
    ctrl.on_tick()
    assert ctrl.state == "IDLE"
    assert guard.get_last_value("kp") == 1.5
    assert guard.get_last_value("ki") == 2.5


def test_confirm_commits_and_revert_restores_without_record(qapp):
    ctrl, debug, guard, params = controller([0.0])
    ctrl.begin(params)
    ctrl.confirm()
    assert ctrl.state == "IDLE" and guard.get_last_value("kp") == 1.5

    guard.record("kp", 1.0)
    guard.record("ki", 2.0)
    ctrl.begin(params)
    ctrl.revert()
    assert ctrl.state == "IDLE"
    assert guard.get_last_value("kp") == 1.0
    assert [call[0] for call in debug.writes[-2:]] == [0x20000100, 0x20000104]


def test_mild_limit_violation_rolls_back_without_stop(qapp):
    ctrl, debug, _guard, params = controller([0.0])
    ctrl.begin(params)
    ctrl._on_var_updated(event("output", 11.0))
    assert ctrl.state == "IDLE"
    assert debug.controls == []


def test_severe_limit_violation_stops_then_rolls_back(qapp):
    ctrl, debug, _guard, params = controller([0.0])
    ctrl.begin(params)
    ctrl._on_var_updated(event("output", 31.0))
    assert debug.controls == [False]
    assert ctrl.state == "SAFE_STOP"


def test_fault_variable_nonzero_is_severe(qapp):
    ctrl, debug, _guard, params = controller([0.0])
    ctrl.begin(params)
    ctrl._on_var_updated(event("fault", 1))
    assert debug.controls == [False]
    assert ctrl.state == "SAFE_STOP"


def test_comms_timeout_is_fail_safe(qapp):
    now = [0.0]
    ctrl, debug, _guard, params = controller(now)
    ctrl.begin(params)
    now[0] = 1.1
    ctrl.on_tick()
    assert debug.controls == [False]
    assert ctrl.state == "SAFE_STOP"


def test_atomic_group_rollback_writes_all_anchors(qapp):
    ctrl, debug, _guard, params = controller([0.0])
    ctrl.begin(params)
    before = len(debug.writes)
    ctrl.revert()
    assert [call[0] for call in debug.writes[before:]] == [0x20000100, 0x20000104]


def test_safe_stop_rejects_begin_until_cleared(qapp):
    ctrl, debug, _guard, params = controller([0.0])
    ctrl.begin(params)
    ctrl._on_var_updated(event("fault", 1))
    assert ctrl.begin(params) is False
    count = len(debug.controls)
    ctrl.clear_safe_stop()
    assert ctrl.state == "IDLE"
    assert len(debug.controls) == count


def test_missing_anchor_is_read_before_write(qapp):
    from power_scope.core.safety_controller import AnomalyCriteria, SafetyController
    debug = FakeDebug()
    debug.memory[0x20000100] = b"\x00\x00\x80?"  # float 1.0
    ctrl = SafetyController(debug, Guardrails(), AnomalyCriteria(window_s=5.0), clock=lambda: 0.0)
    assert ctrl.begin([("kp", channel("kp", 0x20000100), 1.5)])
    assert ctrl.anchors == {"kp": 1.0}
    assert ctrl.state == "MONITORING"


def test_rollback_verify_failure_escalates_to_safe_stop(qapp):
    ctrl, debug, _guard, params = controller([0.0])
    ctrl.begin(params)
    debug.fail_addresses.add(0x20000100)
    ctrl.revert()
    assert ctrl.state == "SAFE_STOP"
    assert debug.controls == [False]


def test_begin_rejected_when_required_monitor_is_not_streamed(qapp):
    ctrl, debug, _guard, params = controller([0.0])
    missing = ctrl.set_stream_channels({"fault"})
    assert missing == {"output"}
    assert ctrl.begin(params) is False
    assert debug.writes == []


