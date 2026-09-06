import json
from pathlib import Path
import struct
import pytest
from power_scope.core.debug_service import DebugService, SampleChannel
from power_scope.core.cffi_loader import DebugProtocol


def test_actual_c_get_info_vector():
    vector = json.loads((Path(__file__).parent / "fixtures/ns5039-get-info.json").read_text())
    frame = bytes.fromhex(vector["frame_hex"])
    svc = DebugService(writer=lambda data: None)
    svc._seq = 0x1233
    seen = []
    svc.get_info(seen.append)
    svc.feed(frame)
    assert len(seen) == 1
    info = svc.parse_device_info(seen[0]["payload"])
    assert info["identity"].build_id.hex() == vector["build_id"]
    caps = info["capabilities"]
    assert caps.supported_commands == frozenset(vector["supported_commands"])
    assert (caps.read_memory_bytes, caps.batch_items, caps.sample_row_bytes) == (181, 16, 64)
    assert not info["identity"].artifacts_verified
    payload = frame[9:-2]
    for n in range(58):
        assert svc.parse_device_info(payload[:n]) == {}
    for n in range(58, 174):
        partial = svc.parse_device_info(payload[:n])
        assert partial["identity"].build_id is None
        assert partial["capabilities"].sample_items is None
    unknown = b"UNKNOWN" + payload[7:]
    assert svc.parse_device_info(unknown)["capabilities"].read_memory_bytes is None


def test_memory_and_batch_blocks_follow_wire_limits():
    sent, seen = [], []
    svc = DebugService(writer=sent.append)
    svc.read_memory_block(0x20000000, 400, seen.append)
    for count in (181, 181, 38):
        req = DebugProtocol.parse_frame(sent[-1])
        assert req["payload"] == bytes([count])
        svc.feed(DebugProtocol.build_response(1, req["seq"], 0, bytes(count)))
    assert len(seen[0]["payload"]) == 400
    sent.clear(); seen.clear()
    svc.read_batch_blocks([(0x20000000+i*8, 8) for i in range(33)], seen.append)
    for count in (16, 16, 1):
        req = DebugProtocol.parse_frame(sent[-1])
        assert req["payload"][0] == count
        svc.feed(DebugProtocol.build_response(3, req["seq"], 0, bytes(count*8)))
    assert len(seen[0]["payload"]) == 264


@pytest.mark.parametrize("size", [0, 182, 192, 193, 256])
def test_single_read_rejects_unsafe_size(size):
    sent = []
    with pytest.raises(ValueError):
        DebugService(writer=sent.append).read_memory(0x20000000, size)
    assert not sent


def test_sample_limits_and_ack_period():
    sent = []
    svc = DebugService(writer=sent.append)
    channels = [SampleChannel(str(i), 0x20000000+i*4, 4) for i in range(16)]
    seq = svc.setup_sample_list(0, 100000, channels)
    assert not svc.has_layout(0)
    svc.feed(DebugProtocol.build_response(4, seq, 0, b""))
    assert not svc.has_layout(0)
    svc.feed(DebugProtocol.build_response(4, seq, 0, struct.pack("<I", 110000)))
    assert svc._periods_us[0] == 110000
    with pytest.raises(ValueError):
        svc.setup_sample_list(0, 100000, channels + channels[:1])
    with pytest.raises(ValueError):
        svc.setup_sample_list(0, 100000, [SampleChannel(str(i), 0x20000000+i*8, 8) for i in range(9)])
