"""test_protocol_reverse.py — 协议逆向启发式推断"""
import pytest
from power_scope.llm import protocol_reverse as pr


def _make_crc_frame(sof, payload):
    """SOF + len(payload) + payload + CRC16LE"""
    body = bytes([sof, len(payload)]) + bytes(payload)
    crc = pr.crc16_modbus(body)
    return body + bytes([crc & 0xFF, (crc >> 8) & 0xFF])


def test_crc16_roundtrip():
    body = bytes([0x01, 0x03, 0x00, 0x00, 0x00, 0x01])
    crc = pr.crc16_modbus(body)
    frame = body + bytes([crc & 0xFF, (crc >> 8) & 0xFF])
    # 反向校验：去掉尾部 2 字节重算应一致
    assert pr.crc16_modbus(frame[:-2]) == (frame[-2] | (frame[-1] << 8))


def test_detect_header_common_prefix():
    frames = [bytes([0xAA, 0x01, 0x02]), bytes([0xAA, 0x03, 0x04]), bytes([0xAA, 0x09])]
    h = pr.detect_header(frames)
    assert h["sof"] == bytes([0xAA]) and h["confidence"] == 1.0


def test_detect_length_field():
    frames = [_make_crc_frame(0xAA, [1, 2, 3]), _make_crc_frame(0xAA, [9, 8]),
              _make_crc_frame(0xAA, [5, 5, 5, 5])]
    lf = pr.detect_length_field(frames)
    assert lf["found"] is True
    assert lf["offset"] == 1               # 第 2 字节是 payload 长度
    # 总长 = payload_len + 4 (sof+len+crc*2)
    assert lf["delta_to_total_len"] == 4


def test_detect_checksum_crc16_le():
    frames = [_make_crc_frame(0xAA, [1, 2, 3]), _make_crc_frame(0xAA, [7, 7]),
              _make_crc_frame(0xAA, [4, 5, 6, 7])]
    cs = pr.detect_checksum(frames)
    assert cs["found"] is True
    assert cs["type"] == "crc16_modbus"
    assert cs["endian"] == "little"
    assert cs["check_len"] == 2


def test_detect_checksum_sum8():
    def sframe(payload):
        body = bytes([0x55]) + bytes(payload)
        return body + bytes([sum(body) & 0xFF])
    frames = [sframe([1, 2, 3]), sframe([9]), sframe([4, 5, 6, 7])]
    cs = pr.detect_checksum(frames)
    assert cs["found"] and cs["type"] == "sum8" and cs["check_len"] == 1


def test_field_stability():
    frames = [bytes([0xAA, 0x01, 0x10]), bytes([0xAA, 0x02, 0x10]), bytes([0xAA, 0x03, 0x10])]
    st = pr.field_stability(frames)
    assert st[0]["kind"] == "const" and st[0]["value"] == 0xAA
    assert st[1]["kind"] == "var"
    assert st[2]["kind"] == "const" and st[2]["value"] == 0x10


def test_split_stream():
    f1 = bytes([0xAA, 1, 2]); f2 = bytes([0xAA, 3]); f3 = bytes([0xAA, 9, 9, 9])
    stream = f1 + f2 + f3
    frames = pr.split_stream(stream, bytes([0xAA]))
    assert frames == [f1, f2, f3]


def test_analyze_and_summary_smoke():
    frames = [_make_crc_frame(0xAA, [1, 2, 3]), _make_crc_frame(0xAA, [7, 7])]
    a = pr.analyze_frames(frames)
    assert a["header"]["sof"] == bytes([0xAA])
    assert a["checksum"]["found"] is True
    s = pr.summarize(a)
    assert "帧头" in s and "校验" in s
    prompt = pr.build_llm_prompt(a, sample_hex="AA 03 01 02 03 ..")
    assert "偏移" in prompt
