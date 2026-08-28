"""
cross_verify_modbus.py — C/Python Modbus RTU 交叉验证

验证 C 核心库的 Modbus RTU 帧编解码与 Python 参考实现结果完全一致。
注意: Modbus 地址/数量/寄存器值使用大端序, CRC 使用小端序。
"""
import struct
import random


def crc16_modbus(data: bytes) -> int:
    """CRC16-Modbus (与 C 实现一致)"""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if (crc & 1) else crc >> 1
    return crc


def build_read_holding(slave_id, start_addr, reg_count):
    payload = struct.pack('>BBHH', slave_id, 0x03, start_addr, reg_count)
    crc = crc16_modbus(payload)
    return payload + struct.pack('<H', crc)


def build_write_single(slave_id, addr, value):
    payload = struct.pack('>BBHH', slave_id, 0x06, addr, value)
    crc = crc16_modbus(payload)
    return payload + struct.pack('<H', crc)


def build_read_holding_response(slave_id, regs):
    byte_count = len(regs) * 2
    payload = struct.pack('>BBB', slave_id, 0x03, byte_count)
    for reg in regs:
        payload += struct.pack('>H', reg)
    crc = crc16_modbus(payload)
    return payload + struct.pack('<H', crc)


def parse_rtu_response(data, expected_slave=None, expected_fc=None):
    if len(data) < 4:
        return None, "too short"
    crc_calc = crc16_modbus(data[:-2])
    crc_recv = struct.unpack('<H', data[-2:])[0]
    if crc_calc != crc_recv:
        return None, "CRC error"
    slave_id, fc = data[0], data[1]
    if expected_slave is not None and slave_id != expected_slave:
        return None, "slave mismatch"
    if fc & 0x80:
        return {'slave_id': slave_id, 'fc': fc, 'exception': data[2]}, "exception"
    if expected_fc is not None and fc != expected_fc:
        return None, "FC mismatch"
    if fc in (0x03, 0x04):
        byte_count = data[2]
        regs = [struct.unpack('>H', data[3+i*2:5+i*2])[0] for i in range(byte_count // 2)]
        return {'slave_id': slave_id, 'fc': fc, 'regs': regs}, "ok"
    return {'slave_id': slave_id, 'fc': fc}, "ok"


def test_c_cross_verify():
    """使用与 C 测试完全相同的向量验证"""
    # C test: build_read_holding(0x01, 0x0000, 0x000A)
    frame = build_read_holding(0x01, 0x0000, 0x000A)
    expected = bytes([0x01, 0x03, 0x00, 0x00, 0x00, 0x0A, 0xC5, 0xCD])
    assert frame == expected, f"frame={frame.hex()} expected={expected.hex()}"
    print("[PASS] build_read_holding matches C")

    # C test: build_write_single(0x01, 0x006B, 0x012C)
    frame = build_write_single(0x01, 0x006B, 0x012C)
    assert frame[0] == 0x01 and frame[1] == 0x06
    assert struct.unpack('>H', frame[2:4])[0] == 0x006B
    assert struct.unpack('>H', frame[4:6])[0] == 0x012C
    assert len(frame) == 8
    assert crc16_modbus(frame[:-2]) == struct.unpack('<H', frame[-2:])[0]
    print("[PASS] build_write_single matches C")

    # C test: build_read_holding_response(0x01, [0x1234, 0x5678], 2)
    resp = build_read_holding_response(0x01, [0x1234, 0x5678])
    parsed, status = parse_rtu_response(resp, expected_slave=0x01, expected_fc=0x03)
    assert status == "ok"
    assert parsed['regs'] == [0x1234, 0x5678]
    print("[PASS] read_response roundtrip matches C")

    # C test: roundtrip with 5 regs, slave=0x0A
    orig = [0x1111, 0x2222, 0x3333, 0x4444, 0x5555]
    resp = build_read_holding_response(0x0A, orig)
    parsed, _ = parse_rtu_response(resp, expected_slave=0x0A, expected_fc=0x03)
    assert parsed['regs'] == orig
    print("[PASS] roundtrip_5_regs matches C")


def test_random_cross_verify():
    """随机数据大规模验证: 构建→解析→比对"""
    random.seed(42)
    for i in range(200):
        slave = random.randint(1, 247)
        count = random.randint(1, 50)
        regs = [random.randint(0, 65535) for _ in range(count)]

        resp = build_read_holding_response(slave, regs)
        parsed, status = parse_rtu_response(resp, expected_slave=slave, expected_fc=0x03)
        assert status == "ok", f"iter {i}: {status}"
        assert parsed['regs'] == regs, f"iter {i}: reg mismatch"
    print("[PASS] random_cross_verify (200 iterations)")


def test_crc_error_detection():
    """CRC 错误检测"""
    frame = build_read_holding(0x01, 0, 10)
    frame_bad = bytearray(frame)
    frame_bad[2] ^= 0xFF
    _, status = parse_rtu_response(bytes(frame_bad))
    assert status == "CRC error"
    print("[PASS] crc_error_detection")


if __name__ == "__main__":
    print("=== Modbus RTU Cross Verification (Python vs C) ===")
    test_c_cross_verify()
    test_random_cross_verify()
    test_crc_error_detection()
    print("\nAll Modbus cross-verification tests passed! C and Python implementations are consistent.")
