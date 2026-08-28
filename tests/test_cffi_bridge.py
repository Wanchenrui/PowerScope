"""
test_cffi_bridge.py — CFFI 桥接层测试

验证 Python 通过 CFFI 调用 C 核心库的功能正确性，
并与纯 Python 参考实现交叉验证。
"""
import os
import sys
import struct
import pytest

# 确保能导入 power_scope
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from power_scope.core.cffi_loader import CRC16, RingBuffer, ModbusCodec, DebugProtocol


def test_crc16_basic():
    """CRC16 基本计算"""
    # "123456789" → 0x4B37
    assert CRC16.calc(b"123456789") == 0x4B37
    # 空数据 → 0xFFFF
    assert CRC16.calc(b"") == 0xFFFF
    # Modbus 帧
    frame = bytes([0x01, 0x03, 0x00, 0x00, 0x00, 0x0A])
    assert CRC16.calc(frame) == 0xCDC5


def test_crc16_bitwise_vs_table():
    """查表法 vs 逐位法一致性"""
    import random
    random.seed(42)
    for _ in range(50):
        data = bytes(random.randint(0, 255) for _ in range(random.randint(1, 100)))
        assert CRC16.calc(data) == CRC16.bitwise(data)


def test_crc16_continue():
    """续算功能"""
    data = b"\x01\x04\x02\xFF\xFF"
    whole = CRC16.calc(data)
    part = CRC16.continue_calc(0xFFFF, data[:2])
    part = CRC16.continue_calc(part, data[2:])
    assert whole == part


def test_ring_buffer_basic():
    """环形缓冲区基本操作"""
    rb = RingBuffer(64)
    assert rb.capacity == 64
    assert rb.available == 0

    rb.write(b"\x01\x02\x03\x04\x05")
    assert rb.available == 5

    data = rb.read(3)
    assert data == b"\x01\x02\x03"
    assert rb.available == 2

    data = rb.read(10)
    assert data == b"\x04\x05"
    assert rb.available == 0


def test_ring_buffer_wraparound():
    """环形缓冲区回绕"""
    rb = RingBuffer(8)
    rb.write(b"\x01\x02\x03\x04\x05\x06\x07\x08")
    rb.read(4)
    rb.write(b"\x09\x0A\x0B\x0C")
    data = rb.read(8)
    assert data == bytes([5, 6, 7, 8, 9, 10, 11, 12])


def test_ring_buffer_peek():
    """偷看不消费"""
    rb = RingBuffer(16)
    rb.write(b"\x10\x20\x30")
    data = rb.peek(3)
    assert data == b"\x10\x20\x30"
    assert rb.available == 3


def test_ring_buffer_full_discard():
    """满缓冲丢弃"""
    rb = RingBuffer(4)
    written = rb.write(b"\x01\x02\x03\x04\x05\x06")
    assert written == 4


def test_modbus_build_read_holding():
    """Modbus 读保持寄存器请求构建"""
    frame = ModbusCodec.build_read_holding(0x01, 0x0000, 0x000A)
    assert len(frame) == 8
    assert frame[0] == 0x01  # slave
    assert frame[1] == 0x03  # FC
    assert frame[6] == 0xC5  # CRC lo
    assert frame[7] == 0xCD  # CRC hi


def test_modbus_parse_response():
    """Modbus 响应解析"""
    regs = [0x1234, 0x5678]
    # 手动构建响应帧
    import struct
    payload = struct.pack('>BBB', 0x01, 0x03, 4) + struct.pack('>HH', *regs)
    from power_scope.core.cffi_loader import CRC16
    crc = CRC16.calc(payload)
    resp_frame = payload + struct.pack('<H', crc)
    # 不传 req (slave_id=None) 避免 reg_count 检查
    result = ModbusCodec.parse_response(resp_frame)
    assert result["slave_id"] == 0x01
    assert result["function_code"] == 0x03
    assert result["registers"] == [0x1234, 0x5678]


def test_debug_protocol_roundtrip():
    """调试协议帧构建→解析 roundtrip"""
    payload = b"\xDE\xAD\xBE\xEF"
    frame = DebugProtocol.build_frame(
        DebugProtocol.CMD_READ_MEM, 0x1234, 0x20001000, payload)
    parsed = DebugProtocol.parse_frame(frame)
    assert parsed["cmd"] == DebugProtocol.CMD_READ_MEM
    assert parsed["seq"] == 0x1234
    assert parsed["address"] == 0x20001000
    assert parsed["payload"] == payload


def test_debug_protocol_stream():
    """流式帧构建→解析"""
    data = b"\x00\x00\x80\x3F\x00\x00\x00\x40"
    frame = DebugProtocol.build_stream_frame(0x0007, 0x123456, 0, 1, data)
    # 流式帧需要手动解析 (parse_frame 不适用于流式帧)
    assert len(frame) == 12 + len(data) + 2
    assert frame[0] == 0xA5 and frame[1] == 0x5A
    assert frame[3] == DebugProtocol.CMD_STREAM_DATA


def test_debug_protocol_expected_len():
    """期望帧长判断"""
    frame = DebugProtocol.build_frame(DebugProtocol.CMD_GET_INFO, 1, 0, b"")
    elen = DebugProtocol.expected_frame_len(frame[:12])
    assert elen == len(frame)


def test_cross_verify_crc16_with_python():
    """C/Python CRC16 交叉验证"""
    def crc16_python(data: bytes) -> int:
        crc = 0xFFFF
        for byte in data:
            crc ^= byte
            for _ in range(8):
                crc = (crc >> 1) ^ 0xA001 if (crc & 1) else crc >> 1
        return crc

    import random
    random.seed(99)
    for _ in range(100):
        data = bytes(random.randint(0, 255) for _ in range(random.randint(0, 200)))
        c_result = CRC16.calc(data)
        py_result = crc16_python(data)
        assert c_result == py_result, f"CRC mismatch for data len={len(data)}"
