"""Recorder 协议、RAW_EXACT 解码与 25us 时间轴测试。"""
import struct

import pytest

from power_scope.core.cffi_loader import DebugProtocol
from power_scope.core.debug_service import (
    DebugService,
    SampleChannel,
    WAVE_TYPE_F32,
    WAVE_TYPE_S16,
    WAVE_TYPE_U32,
    wave_type_code,
)
from power_scope.core.event_bus import EventBus
from tests.conftest import pump_events


def test_wave_type_code_maps_scalar_types():
    assert wave_type_code("int16_t", 2) == WAVE_TYPE_S16
    assert wave_type_code("float", 4) == WAVE_TYPE_F32
    assert wave_type_code("uint32_t", 4) == WAVE_TYPE_U32


def test_wave_config_wire_layout_and_128kb_limit(qapp):
    sent = []
    service = DebugService(writer=sent.append)
    channels = [
        SampleChannel("raw", 0x20001000, 2, "int16_t"),
        SampleChannel("value", 0x20001004, 4, "float"),
    ]

    service.configure_wave(channels, points=2048, tap_id=1)
    frame = DebugProtocol.parse_frame(sent[0])
    assert frame["cmd"] == DebugService.CMD_WAVE_CONFIG
    mode, tap, period, points, count = struct.unpack_from(
        "<BBIIB", frame["payload"], 0)
    assert (mode, tap, period, points, count) == (0, 1, 25, 2048, 2)
    assert struct.unpack_from("<IBB", frame["payload"], 11) == (
        0x20001000, 2, WAVE_TYPE_S16)
    assert struct.unpack_from("<IBB", frame["payload"], 17) == (
        0x20001004, 4, WAVE_TYPE_F32)

    with pytest.raises(ValueError, match="128KB"):
        service.configure_wave(channels, points=22000, tap_id=1)


def test_wave_status_and_data_parsers():
    status_payload = bytearray(29)
    status_payload[0:4] = bytes([3, 1, 0, 2])
    struct.pack_into("<IIIHHII", status_payload, 4,
                     7, 2048, 2048, 6, 25, 12288, 0)
    status = DebugService.parse_wave_status(bytes(status_payload))
    assert status is not None
    assert status.state == 3
    assert status.capture_id == 7
    assert status.row_bytes == 6
    assert status.buffer_high_water == 12288

    raw = struct.pack("<hf", -123, 1.25)
    data_payload = struct.pack(
        "<IHIIHBBH", 7, 4, 12, 2, 1, 0, 1, len(raw)) + raw
    block = DebugService.parse_wave_data(data_payload)
    assert block is not None
    assert block.capture_id == 7
    assert block.offset == 12
    assert block.first_sample_id == 2
    assert block.data == raw


def test_raw_capture_decodes_types_and_implicit_25us_axis():
    channels = [
        SampleChannel("raw", 0x20001000, 2, "int16_t", scale=0.1),
        SampleChannel("value", 0x20001004, 4, "float"),
    ]
    data = struct.pack("<hf", -20, 1.25) + struct.pack("<hf", 30, 2.5)
    decoded = DebugService.decode_wave_capture(data, channels, period_us=25)

    assert decoded["raw"]["raw_values"] == [-20, 30]
    assert decoded["raw"]["phys_values"] == [-2.0, 3.0]
    assert decoded["value"]["raw_values"] == pytest.approx([1.25, 2.5])
    assert decoded["raw"]["timestamps"] == pytest.approx([0.0, 25e-6])


def test_batched_live_samples_receive_distinct_timestamps(qapp):
    service = DebugService(writer=lambda _data: None)
    service.register_sample_layout(
        0, [SampleChannel("raw", 0x20001000, 2, "uint16_t")], period_us=25)
    events = []
    EventBus.instance().subscribe("var/updated", events.append)
    frame = DebugProtocol.build_stream_frame(
        seq=1, timestamp=1000, list_id=0, sample_count=2,
        data=struct.pack("<HH", 10, 11))

    service.feed(frame)
    pump_events()
    current = [event for event in events if event.name == "raw"]
    assert [event.raw_value for event in current[-2:]] == [10, 11]
    assert current[-2].timestamp == pytest.approx(0.001)
    assert current[-1].timestamp == pytest.approx(0.001025)
