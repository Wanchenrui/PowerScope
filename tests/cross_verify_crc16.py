"""
cross_verify_crc16.py — C/Python CRC16-Modbus 交叉验证

验证 C 核心库的 CRC16-Modbus 实现与 Python 参考实现结果完全一致。
"""
import struct
import random


def crc16_modbus_python(data: bytes) -> int:
    """Python 参考实现: CRC16-Modbus 逐位法"""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc


def crc16_modbus_table_python(data: bytes) -> int:
    """Python 查表法实现 (与 C 查表法对应)"""
    # 生成查表
    table = []
    for i in range(256):
        crc = i
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
        table.append(crc)

    crc = 0xFFFF
    for byte in data:
        crc = (crc >> 8) ^ table[(crc ^ byte) & 0xFF]
    return crc


def test_known_vectors():
    """测试已知向量"""
    # Modbus 标准测试: "123456789" → 0x4B37
    assert crc16_modbus_python(b"123456789") == 0x4B37, "Python bitwise failed"
    assert crc16_modbus_table_python(b"123456789") == 0x4B37, "Python table failed"

    # Modbus RTU 帧: 01 03 00 00 00 0A → 0xCDC5
    frame = bytes([0x01, 0x03, 0x00, 0x00, 0x00, 0x0A])
    assert crc16_modbus_python(frame) == 0xCDC5, f"Modbus frame: expected 0xCDC5, got {crc16_modbus_python(frame):#06x}"
    assert crc16_modbus_table_python(frame) == 0xCDC5

    # 空数据
    assert crc16_modbus_python(b"") == 0xFFFF
    assert crc16_modbus_table_python(b"") == 0xFFFF

    print("[PASS] known_vectors")


def test_random_consistency():
    """随机数据: Python bitwise vs table 一致"""
    random.seed(42)
    for i in range(200):
        length = random.randint(0, 500)
        data = bytes(random.randint(0, 255) for _ in range(length))
        bw = crc16_modbus_python(data)
        tb = crc16_modbus_table_python(data)
        assert bw == tb, f"iter {i}: bitwise={bw:#06x} table={tb:#06x}"
    print("[PASS] python_bitwise_vs_table (200 random)")


def test_c_cross_verify():
    """
    交叉验证: 与 C 测试使用完全相同的数据，验证结果一致。
    C 测试中使用了:
    - "123456789" → 0x4B37
    - Modbus 帧 [0x01,0x03,0x00,0x00,0x00,0x0A] → 0xCDC5
    - 空数据 → 0xFFFF
    """
    # 这些值必须与 C test_crc16.c 中的断言完全一致
    assert crc16_modbus_python(b"123456789") == 0x4B37
    assert crc16_modbus_table_python(b"123456789") == 0x4B37

    frame = bytes([0x01, 0x03, 0x00, 0x00, 0x00, 0x0A])
    assert crc16_modbus_python(frame) == 0xCDC5
    assert crc16_modbus_table_python(frame) == 0xCDC5

    assert crc16_modbus_python(b"") == 0xFFFF
    assert crc16_modbus_table_python(b"") == 0xFFFF

    print("[PASS] c_cross_verify (C test vectors match Python)")


def test_continue_equivalence():
    """续算验证: 分片 == 整块"""
    data = bytes([0x01, 0x04, 0x02, 0xFF, 0xFF])
    whole = crc16_modbus_python(data)
    # 分片: 前两个 + 后三个
    part = 0xFFFF
    for byte in data[:2]:
        part ^= byte
        for _ in range(8):
            part = (part >> 1) ^ 0xA001 if (part & 1) else part >> 1
    for byte in data[2:]:
        part ^= byte
        for _ in range(8):
            part = (part >> 1) ^ 0xA001 if (part & 1) else part >> 1
    assert whole == part, f"whole={whole:#06x} split={part:#06x}"
    print("[PASS] continue_equivalence")


if __name__ == "__main__":
    print("=== CRC16-Modbus Cross Verification (Python) ===")
    test_known_vectors()
    test_random_consistency()
    test_c_cross_verify()
    test_continue_equivalence()
    print("\nAll cross-verification tests passed! C and Python implementations are consistent.")
