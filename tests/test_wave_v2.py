"""Wave v2 extension, trigger/upload commands and Live block integration."""
import struct

import pytest

from power_scope.core.cffi_loader import DebugProtocol
from power_scope.core.debug_service import (
    DebugService,
    SampleChannel,
    WAVE_ENCODING_LIVE_CHANNEL,
    WAVE_MODE_LIVE,
    WAVE_MODE_TRIGGERED,
    WAVE_TYPE_S16,
    WAVE_TYPE_U64,
)
from power_scope.core.event_bus import EventBus
from power_scope.core.wave_codec import encode_channel
from tests.conftest import pump_events


def test_triggered_config_uses_extended_descriptors_and_commands(qapp):
    sent = []
    service = DebugService(writer=sent.append)
    channels = [
        SampleChannel("counter64", 0x20101000, 8, "uint64_t",
                      sequence_address=0x20100020),
        SampleChannel("current", 0x20001000, 2, "int16_t"),
    ]

    service.configure_wave(
        channels, points=4096, mode=WAVE_MODE_TRIGGERED,
        pretrigger_points=1024, posttrigger_points=3072)
    frame = DebugProtocol.parse_frame(sent[-1])
    assert struct.unpack_from("<BBIIB", frame["payload"], 0) == (
        WAVE_MODE_TRIGGERED, 1, 25, 4096, 2)
    assert struct.unpack_from("<IIHBB", frame["payload"], 11) == (
        1024, 3072, 0, 1, 10)
    assert struct.unpack_from("<IBBI", frame["payload"], 23) == (
        0x20101000, 8, WAVE_TYPE_U64, 0x20100020)
    assert struct.unpack_from("<IBBI", frame["payload"], 33) == (
        0x20001000, 2, WAVE_TYPE_S16, 0)

    service.trigger_wave()
    assert DebugProtocol.parse_frame(sent[-1])["cmd"] == service.CMD_WAVE_TRIGGER
    service.start_wave_upload(offset=128)
    upload = DebugProtocol.parse_frame(sent[-1])
    assert upload["cmd"] == service.CMD_WAVE_UPLOAD
    assert struct.unpack("<IH", upload["payload"]) == (128, 0)


def test_extended_status_is_incrementally_parsed():
    payload = bytearray(71)
    payload[:4] = bytes([6, 1, WAVE_MODE_TRIGGERED, 2])
    struct.pack_into("<IIIHHII", payload, 4, 9, 100, 300, 10, 25, 1000, 3)
    payload[28] = 4
    struct.pack_into("<IIHHIIIIHIII", payload, 29,
                     100, 200, 5, 12, 1, 7, 8, 2, 1 << 0, 321, 4096, 512)
    status = DebugService.parse_wave_status(payload)
    assert status.pretrigger_points == 100
    assert status.posttrigger_points == 200
    assert status.tx_low_water == 12
    assert status.tx_low_overflow == 7
    assert status.atomic_failures == 2
    assert status.non_atomic_mask == 1
    assert status.capture_isr_max_cycles == 321
    assert status.live_encoded_bytes == 512


def test_unsolicited_live_block_decodes_in_batch_and_reports_gap(qapp):
    sent = []
    service = DebugService(writer=sent.append)
    channel = SampleChannel("current", 0x20001000, 2, "int16_t", scale=0.1)
    seq = service.configure_wave(
        [channel], points=4096, mode=WAVE_MODE_LIVE, block_points=8)
    config_payload = struct.pack("<IIIHBB", 11, 25, 4096, 2, 1, 1)
    service.feed(DebugProtocol.build_response(
        service.CMD_WAVE_CONFIG, seq, 0, config_payload))

    events = []
    EventBus.instance().subscribe("wave/live_block", events.append)
    raw = struct.pack("<4h", -10, -9, -8, -7)
    encoded = encode_channel(raw, 2, type_code=WAVE_TYPE_S16)

    def send(first_sample_id, block_seq):
        live = struct.pack(
            "<BBBBH", 0, encoded.codec_id, encoded.parameter, 2,
            len(encoded.payload)) + encoded.payload
        common = struct.pack(
            "<IHIIHBBH", 11, block_seq, 0, first_sample_id, 4,
            WAVE_ENCODING_LIVE_CHANNEL, 1, len(live)) + live
        service.feed(DebugProtocol.build_response(
            service.CMD_WAVE_DATA, 0, 0, common))
        pump_events()

    send(0, 1)
    send(6, 2)
    assert events[-2]["raw_values"] == [-10, -9, -8, -7]
    assert events[-2]["phys_values"] == pytest.approx([-1.0, -0.9, -0.8, -0.7])
    assert events[-2]["timestamps"] == pytest.approx([0, 25e-6, 50e-6, 75e-6])
    assert events[-1]["gap_samples"] == 2
    assert service.stats.wave_gap_samples == 2


def test_live_ring_reserves_internal_sentinel_without_losing_requested_capacity():
    sent = []
    service = DebugService(writer=sent.append)
    channels = [
        SampleChannel(f"v{index}", 0x20001000 + index * 4, 4, "uint32_t")
        for index in range(16)
    ]
    max_points = (128 * 1024) // (64 + 4) - 1

    service.configure_wave(
        channels, points=max_points, mode=WAVE_MODE_LIVE, block_points=16)
    assert sent
    with pytest.raises(ValueError, match="128KB"):
        service.configure_wave(
            channels, points=max_points + 1,
            mode=WAVE_MODE_LIVE, block_points=16)
    with pytest.raises(ValueError, match="2..65534"):
        service.configure_wave(
            [channels[0]], points=65535,
            mode=WAVE_MODE_LIVE, block_points=16)


def test_live_defaults_to_512_point_blocks_and_validates_ring_capacity():
    sent = []
    service = DebugService(writer=sent.append)
    channel = SampleChannel("current", 0x20001000, 2, "int16_t")

    service.configure_wave([channel], points=4096, mode=WAVE_MODE_LIVE)
    payload = DebugProtocol.parse_frame(sent[-1])["payload"]
    assert struct.unpack_from("<H", payload, 19)[0] == 512

    with pytest.raises(ValueError, match="1..512"):
        service.configure_wave(
            [channel], points=4096, mode=WAVE_MODE_LIVE, block_points=513)
    with pytest.raises(ValueError, match="不能小于"):
        service.configure_wave(
            [channel], points=32, mode=WAVE_MODE_LIVE, block_points=64)


def _configured_live_service():
    sent = []
    service = DebugService(writer=sent.append)
    channel = SampleChannel("current", 0x20001000, 2, "int16_t")
    seq = service.configure_wave(
        [channel], points=4096, mode=WAVE_MODE_LIVE, block_points=8)
    config_payload = struct.pack("<IIIHBB", 11, 25, 4096, 2, 1, 1)
    service.feed(DebugProtocol.build_response(
        service.CMD_WAVE_CONFIG, seq, 0, config_payload))
    return service


def _feed_live(service, capture_id, first_sample_id, block_seq):
    raw = struct.pack("<4h", 1, 2, 3, 4)
    encoded = encode_channel(raw, 2, type_code=WAVE_TYPE_S16)
    live = struct.pack(
        "<BBBBH", 0, encoded.codec_id, encoded.parameter, 2,
        len(encoded.payload)) + encoded.payload
    common = struct.pack(
        "<IHIIHBBH", capture_id, block_seq, 0, first_sample_id, 4,
        WAVE_ENCODING_LIVE_CHANNEL, 1, len(live)) + live
    service.feed(DebugProtocol.build_response(
        service.CMD_WAVE_DATA, 0, 0, common))


def test_live_rejects_residual_capture_and_duplicate_block(qapp):
    service = _configured_live_service()
    blocks = []
    errors = []
    EventBus.instance().subscribe("wave/live_block", blocks.append)
    EventBus.instance().subscribe("wave/error", errors.append)

    _feed_live(service, 10, 0, 1)
    _feed_live(service, 11, 0, 1)
    _feed_live(service, 11, 0, 1)
    pump_events()

    assert len(blocks) == 1
    assert any("capture_id" in event["reason"] for event in errors)
    assert any("重复或倒序" in event["reason"] for event in errors)


def test_live_sample_id_wrap_keeps_monotonic_25us_time(qapp):
    service = _configured_live_service()
    blocks = []
    EventBus.instance().subscribe("wave/live_block", blocks.append)

    _feed_live(service, 11, 0xFFFFFFFC, 0xFFFF)
    _feed_live(service, 11, 0, 1)
    pump_events()

    assert len(blocks) == 2
    assert blocks[1]["gap_samples"] == 0
    assert blocks[1]["first_sample_id_unwrapped"] == 0x100000000
    assert blocks[1]["timestamps"][0] > blocks[0]["timestamps"][-1]
    assert (blocks[1]["timestamps"][0] - blocks[0]["timestamps"][-1]
            == pytest.approx(25e-6))
