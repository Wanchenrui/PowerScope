"""T04 independent protocol counterexamples (reviewer firmware_t03)."""
import struct

from power_scope.core.cffi_loader import CRC16, DebugProtocol
from power_scope.core.debug_service import DebugService, SampleChannel


def test_zero_effective_period_cannot_commit_sample_layout():
    service = DebugService(writer=lambda data: None)
    seq = service.setup_sample_list(0, 100000, [SampleChannel('x', 0x20000000, 4)])
    service.feed(DebugProtocol.build_response(4, seq, 0, bytes(4)))
    assert not service.has_layout(0)
    service.feed(DebugProtocol.build_response(4, seq, 0, struct.pack('<I', 100000)))
    assert service.has_layout(0)


def test_unknown_wire_version_cannot_dispatch_stream_or_wave():
    service = DebugService(writer=lambda data: None)
    service.register_sample_layout(0, [SampleChannel('x', 0x20000000, 4)])
    seen = []
    service._dispatch_stream = lambda *args: seen.append('stream')
    service._dispatch_wave_data = lambda *args: seen.append('wave')
    stream = bytearray(struct.pack('<BBBBHIBB', 0xA5, 0x5A, 2, 0x10, 1, 100, 0, 1) + bytes(4))
    stream += struct.pack('<H', CRC16.calc(bytes(stream)))
    wave = bytearray(DebugProtocol.build_response(0x24, 0, 0, bytes(20)))
    wave[2] = 2
    struct.pack_into('<H', wave, len(wave)-2, CRC16.calc(bytes(wave[:-2])))
    service.feed(bytes(stream) + bytes(wave))
    assert seen == []

def test_msg_read_api_cannot_send_control_opcode():
    import pytest
    from power_scope.core.msg_service import MsgService
    from power_scope.session.session_controller import SessionController
    session = SessionController()
    sent = []
    service = MsgService(session=session, writer=sent.append)
    for opcode in (0x2001, 0x2002, 0x2222):
        with pytest.raises((ValueError, RuntimeError)):
            service.request_read(opcode, 1)
    assert sent == []

def test_msg_legitimate_read_survives_gate_and_bad_count_does_not_send():
    import pytest
    from power_scope.core.msg_service import MsgService, build_msg_frame
    from power_scope.session.session_controller import SessionController
    session = SessionController()
    sent, seen = [], []
    service = MsgService(session=session, writer=sent.append)
    with pytest.raises((ValueError, RuntimeError)):
        service.request_read(0x2101, 2)
    service.request_read(0x2101, 1, seen.append)
    assert sent == [build_msg_frame(0x2101, (0,))]
    service.feed(build_msg_frame(0x2101, (1,)))
    assert seen[0]['words'] == (1,) and seen[0]['ok']
    assert not session._requests


def test_advertised_debug_control_never_bypasses_g0_with_writer_override():
    import pytest
    from power_scope.core.contracts import Capabilities
    from power_scope.session.session_controller import SessionController
    session = SessionController()
    session.capabilities = Capabilities(supported_commands=frozenset(range(256)))
    sent = []
    service = DebugService(session=session, writer=sent.append)
    for action in (lambda: service.write_memory(0x20000000, bytes(4)),
                   lambda: service.device_control(True),
                   lambda: service.device_control(False),
                   service.reset):
        with pytest.raises(RuntimeError):
            action()
    assert sent == [] and not service._pending and not session._requests
