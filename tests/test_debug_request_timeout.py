"""DebugService 请求超时必须让安全回退在断链时也能收尾。"""
import struct

from power_scope.core.cffi_loader import DebugProtocol
from power_scope.core.debug_service import DebugService, SampleChannel
from power_scope.core.guardrails import Guardrails
from power_scope.core.safety_controller import AnomalyCriteria, SafetyController


def test_request_timeout_returns_failure_and_removes_pending(qapp):
    now = [0.0]
    sent = []
    results = []
    service = DebugService(
        writer=sent.append, request_timeout_s=1.0, clock=lambda: now[0])
    service.write_and_verify(
        0x20000100, struct.pack("<f", 1.5), 4,
        callback=lambda ok, data: results.append((ok, data)))

    now[0] = 1.1
    service._expire_pending()

    assert results == [(False, b"")]
    assert not service._pending
    assert service.stats.request_timeouts == 1


def test_late_response_after_timeout_is_ignored(qapp):
    now = [0.0]
    sent = []
    responses = []
    service = DebugService(
        writer=sent.append, request_timeout_s=1.0, clock=lambda: now[0])
    seq = service.read_memory(
        0x20000100, 4, callback=lambda response: responses.append(response))
    now[0] = 1.1
    service._expire_pending()
    service.feed(DebugProtocol.build_response(
        DebugProtocol.CMD_READ_MEM, seq, 0, b"\x01\x02\x03\x04"))

    assert len(responses) == 1
    assert responses[0]["timeout"] is True
    assert responses[0]["status"] == DebugService.STATUS_TIMEOUT


def test_clear_pending_notifies_write_verify_failure(qapp):
    results = []
    service = DebugService(writer=lambda _data: None)
    service.write_and_verify(
        0x20000100, b"\x01\x00\x00\x00", 4,
        callback=lambda ok, data: results.append((ok, data)))
    service.clear_pending()

    assert results == [(False, b"")]
    assert not service._pending


def test_comms_loss_during_rollback_reaches_safe_stop(qapp):
    now = [0.0]
    sent = []
    service = DebugService(
        writer=sent.append, request_timeout_s=1.0, clock=lambda: now[0])
    guard = Guardrails()
    guard.record("kp", 1.0)
    control = SafetyController(
        service, guard,
        AnomalyCriteria(fault_vars={"fault"}, comms_timeout_s=1.0, window_s=5.0),
        clock=lambda: now[0],
    )
    channel = SampleChannel("kp", 0x20000100, 4, "float")

    assert control.begin([("kp", channel, 1.5)])
    write = DebugProtocol.parse_frame(sent[-1])
    service.feed(DebugProtocol.build_response(
        DebugProtocol.CMD_WRITE_MEM, write["seq"], 0, b""))
    read = DebugProtocol.parse_frame(sent[-1])
    service.feed(DebugProtocol.build_response(
        DebugProtocol.CMD_READ_MEM, read["seq"], 0, struct.pack("<f", 1.5)))
    assert control.state == "MONITORING"

    now[0] = 1.1
    control.on_tick()
    assert control.state == "MONITORING"  # 回退 WRITE 正在等待响应
    assert control._busy

    now[0] = 2.2
    service._expire_pending()
    assert control.state == "SAFE_STOP"
    assert not control._busy
    assert not service._pending
    control.close()


def test_send_exception_does_not_leave_late_duplicate_callback(qapp):
    def broken_writer(_data):
        raise OSError("disconnected")

    service = DebugService(writer=broken_writer)
    callbacks = []
    try:
        service.read_memory(0x20000100, 4, callback=callbacks.append)
    except OSError:
        pass

    assert not service._pending
    assert callbacks == []


def test_ambiguous_initial_write_timeout_attempts_anchor_restore(qapp):
    now = [0.0]
    sent = []
    service = DebugService(
        writer=sent.append, request_timeout_s=1.0, clock=lambda: now[0])
    guard = Guardrails()
    guard.record("kp", 1.0)
    control = SafetyController(
        service, guard, AnomalyCriteria(window_s=5.0), clock=lambda: now[0])
    channel = SampleChannel("kp", 0x20000100, 4, "float")

    control.begin([("kp", channel, 1.5)])
    now[0] = 1.1
    service._expire_pending()
    # 首次写响应丢失时，MCU 可能已写成功；必须尝试恢复锚点。
    assert control._busy
    assert len(sent) == 2

    now[0] = 2.2
    service._expire_pending()
    assert control.state == "SAFE_STOP"
    assert not control._busy
    control.close()


def test_qtimer_drives_request_timeout_without_manual_poll(qapp):
    from PySide6.QtTest import QTest

    results = []
    service = DebugService(writer=lambda _data: None, request_timeout_s=0.05)
    service.read_memory(0x20000100, 4, callback=results.append)
    QTest.qWait(120)

    assert results and results[0]["timeout"] is True
    assert not service._pending
