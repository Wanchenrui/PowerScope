import struct
import pytest
from power_scope.session.session_controller import SessionController
from power_scope.core.debug_service import DebugService, SampleChannel
from power_scope.core.msg_service import MsgService
from power_scope.core.cffi_loader import DebugProtocol


def test_epoch_cancels_layout_and_rejects_old_ack():
    session = SessionController()
    svc = DebugService(session=session, writer=lambda data: None)
    # Codec test uses writer only, explicitly remove capability gate.
    svc._session = None
    got = []
    seq = svc.read_memory(0x20000000, 4, got.append)
    svc.register_sample_layout(0, [SampleChannel("x", 0x20000000, 4)])
    session.invalidate("ELF changed")
    assert got[0]["cancelled"] and not svc.has_layout(0)
    new = svc.read_memory(0x20000000, 4, got.append)
    assert new != seq
    svc.feed(DebugProtocol.build_response(1, seq, 0, bytes(4)))
    assert len(got) == 1
    svc.feed(DebugProtocol.build_response(2, new, 0, bytes(4)))
    svc.feed(DebugProtocol.build_response(1, new, 0, bytes(3)))
    assert len(got) == 1
    svc.feed(DebugProtocol.build_response(0xff, new, 4, b""))
    assert got[-1]["status"] == 4


def test_sequence_wrap_never_reuses_completed_or_cancelled():
    svc = DebugService(writer=lambda data: None)
    first = svc.read_memory(0x20000000, 1)
    svc.clear_pending()
    svc._seq = 65535
    assert svc.read_memory(0x20000000, 1) != first
    svc._used_sequences = set(range(1, 65536))
    with pytest.raises(RuntimeError, match="exhausted"):
        svc.get_info()


def test_timeout_clears_layout_even_without_callback():
    now = [0.0]
    svc = DebugService(writer=lambda data: None, clock=lambda: now[0])
    svc.register_sample_layout(0, [SampleChannel("x", 0x20000000, 4)])
    svc.read_memory(0x20000000, 1)
    now[0] = 2
    svc._expire_pending()
    assert not svc._pending and not svc.has_layout(0)


def test_msg_timeout_late_ack_cannot_finish_new_command_after_reset():
    now = [0.0]
    got, sent = [], []
    svc = MsgService(writer=sent.append, clock=lambda: now[0])
    svc.request_write(0x2001, [1], got.append)
    now[0] = 2
    svc.expire_pending()
    svc.clear_pending()
    with pytest.raises(RuntimeError, match="unknown"):
        svc.request_write(0x2001, [0], got.append)
    svc.feed(struct.pack(">HH", 0xdfdf, 0x2001))
    assert len(sent) == 1 and got[0]["kind"] == "timeout"
    svc.request_read(0x2101, 1, got.append)
    svc.feed(struct.pack(">HHH H", 0xefef, 0x2101, 1, 0))
    assert got[-1]["kind"] == "data"
    with pytest.raises(RuntimeError):
        svc.request_write(0x2001, [0])


def test_exclusive_and_protocol_scheduling():
    session = SessionController()
    session.connect_mock()
    session.begin_request("debug", 1)
    with pytest.raises(RuntimeError):
        session.begin_request("msg", 0x2101)
    session.end_request("debug", 1)
    token = session.acquire_exclusive("upgrade")
    with pytest.raises(RuntimeError):
        session.write(b"x")
    with pytest.raises(RuntimeError):
        session.write_service("debug", b"x")
    assert session.write_service("upgrade", b"x", token) == 1
    session.release_exclusive(token)
    with pytest.raises(RuntimeError):
        session.write_service("raw", b"x")
    session.disconnect()


def test_real_raw_rejected_while_mock_demo_is_allowed():
    session = SessionController()
    session.connect_mock()
    assert session.write(b"demo") == 4
    session._transport_type = lambda: "serial"
    with pytest.raises(RuntimeError, match="RAW"):
        session.write(b"unowned")
    assert session.write_service("debug", b"query") == 5
    session.disconnect()


def test_identity_verification_is_epoch_and_build_bound():
    from power_scope.core.contracts import DeviceIdentity
    session = SessionController()
    session.identity = DeviceIdentity(family="NS800RT5039", build_id=bytes(range(32)))
    with pytest.raises(ValueError):
        session.set_artifact_verification(session.epoch+1, bytes(range(32)), "a"*64, True)
    with pytest.raises(ValueError):
        session.set_artifact_verification(session.epoch, bytes(32), "a"*64, True)
    session.set_artifact_verification(session.epoch, bytes(range(32)), "a"*64, True)
    assert session.identity.artifacts_verified
    epoch = session.epoch
    session.set_artifact_verification(epoch, bytes(range(32)), None, False)
    assert session.epoch > epoch and not session.identity.artifacts_verified


def test_handshake_populates_capabilities_without_control_authority():
    import json
    from pathlib import Path
    from power_scope.core.cffi_loader import CRC16
    vector = json.loads((Path(__file__).parent / "fixtures/ns5039-get-info.json").read_text())
    session = SessionController()
    sent = []
    svc = DebugService(session=session, writer=sent.append)
    session.connect_mock()
    session.negotiate()
    req = DebugProtocol.parse_frame(sent[-1])
    frame = bytearray.fromhex(vector["frame_hex"])
    struct.pack_into("<H", frame, 4, req["seq"])
    struct.pack_into("<H", frame, len(frame)-2, CRC16.calc(bytes(frame[:-2])))
    svc.feed(bytes(frame))
    assert session.ready and session.capabilities.sample_items == 16
    assert not session.identity.artifacts_verified
    with pytest.raises(RuntimeError, match="control"):
        svc.write_memory(0x20000000, bytes(4))
    old = session.epoch
    session.device_restarted()
    assert session.epoch > old and not session.ready
    session.disconnect()
