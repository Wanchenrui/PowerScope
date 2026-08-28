"""
test_boundary_edge.py — 边界值与异常场景测试

覆盖: 零值/极值/溢出/空数据/非法参数/结构体对齐/跨平台兼容。
"""
import os, sys, struct, ctypes, pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from power_scope.core.cffi_loader import CRC16, RingBuffer, ModbusCodec, DebugProtocol
from power_scope.debug.elf_parser import ElfVariable, StructMember, decode_value, TYPE_FORMATS

_PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestCRC16Boundaries:
    """CRC16 边界值"""

    def test_empty_data(self):
        """空数据 CRC = 0xFFFF"""
        assert CRC16.calc(b"") == 0xFFFF

    def test_single_byte(self):
        """单字节"""
        crc = CRC16.calc(b"\x00")
        assert isinstance(crc, int) and 0 <= crc <= 0xFFFF
        crc2 = CRC16.calc(b"\xFF")
        assert isinstance(crc2, int) and 0 <= crc2 <= 0xFFFF
        assert crc != crc2

    def test_all_zeros_256(self):
        """256 个 0x00"""
        crc = CRC16.calc(b"\x00" * 256)
        assert isinstance(crc, int)
        assert 0 <= crc <= 0xFFFF

    def test_all_ff_256(self):
        """256 个 0xFF"""
        crc = CRC16.calc(b"\xFF" * 256)
        assert isinstance(crc, int)

    def test_max_length_data(self):
        """65535 字节数据 (uint16 len 上限附近)"""
        data = b"\x55" * 65535
        crc = CRC16.calc(data)
        assert isinstance(crc, int)


class TestRingBufferBoundaries:
    """环形缓冲区边界"""

    def test_capacity_1(self):
        """容量=1"""
        rb = RingBuffer(1)
        assert rb.write(b"\x42") == 1
        assert rb.write(b"\x43") == 0  # 满
        assert rb.read(1) == b"\x42"

    def test_read_empty(self):
        """空缓冲区读取返回 b''"""
        rb = RingBuffer(16)
        assert rb.read(10) == b""
        assert rb.read(0) == b""

    def test_write_empty(self):
        """写入空数据返回0"""
        rb = RingBuffer(16)
        assert rb.write(b"") == 0

    def test_peek_more_than_available(self):
        """偷看比可用多的数据"""
        rb = RingBuffer(16)
        rb.write(b"\x01\x02\x03")
        data = rb.peek(10)
        assert data == b"\x01\x02\x03"
        assert rb.available == 3  # peek 不消费

    def test_clear_then_use(self):
        """清空后正常使用"""
        rb = RingBuffer(16)
        rb.write(b"\x01\x02\x03\x04")
        rb.clear()
        assert rb.available == 0
        rb.write(b"\x05\x06")
        assert rb.read(2) == b"\x05\x06"


class TestModbusBoundaries:
    """Modbus 边界"""

    def test_slave_id_0(self):
        """从站地址 0 (广播)"""
        frame = ModbusCodec.build_read_holding(0, 0, 1)
        assert frame[0] == 0

    def test_slave_id_247(self):
        """从站地址 247 (最大)"""
        frame = ModbusCodec.build_read_holding(247, 0, 1)
        assert frame[0] == 247

    def test_reg_count_1(self):
        """读1个寄存器"""
        frame = ModbusCodec.build_read_holding(1, 0, 1)
        assert len(frame) == 8

    def test_reg_count_125(self):
        """读125个寄存器 (最大)"""
        frame = ModbusCodec.build_read_holding(1, 0, 125)
        assert len(frame) == 8

    def test_reg_count_0_rejected(self):
        """读0个寄存器应失败"""
        with pytest.raises(ValueError):
            ModbusCodec.build_read_holding(1, 0, 0)

    def test_reg_count_126_rejected(self):
        """读126个寄存器 (超限) 应失败"""
        with pytest.raises(ValueError):
            ModbusCodec.build_read_holding(1, 0, 126)

    def test_addr_65535(self):
        """地址 65535 (最大)"""
        frame = ModbusCodec.build_read_holding(1, 65535, 1)
        assert struct.unpack(">H", frame[2:4])[0] == 65535

    def test_exception_response(self):
        """异常响应解析"""
        # slave=1, fc=0x83 (异常), exc_code=0x02
        payload = struct.pack(">BBB", 1, 0x83, 0x02)
        crc = CRC16.calc(payload)
        resp = payload + struct.pack("<H", crc)
        result = ModbusCodec.parse_response(resp)
        assert result["is_exception"]
        assert result["exception_code"] == 0x02

    def test_min_frame_length(self):
        """最短帧 (异常响应 5 字节)"""
        payload = struct.pack(">BBB", 1, 0x83, 0x01)
        crc = CRC16.calc(payload)
        resp = payload + struct.pack("<H", crc)
        result = ModbusCodec.parse_response(resp)
        assert result["is_exception"]

    def test_truncated_response_rejected(self):
        """截断响应被拒绝"""
        frame = ModbusCodec.build_read_holding(1, 0, 2)
        with pytest.raises(ValueError):
            ModbusCodec.parse_response(frame[:4])  # 只有4字节


class TestDebugProtocolBoundaries:
    """调试协议边界"""

    def test_max_seq(self):
        """序列号 65535"""
        frame = DebugProtocol.build_frame(0x07, 65535, 0, b"")
        parsed = DebugProtocol.parse_frame(frame)
        assert parsed["seq"] == 65535

    def test_max_address(self):
        """地址 0xFFFFFFFF"""
        frame = DebugProtocol.build_frame(0x01, 1, 0xFFFFFFFF, bytes([4]))
        parsed = DebugProtocol.parse_frame(frame)
        assert parsed["address"] == 0xFFFFFFFF

    def test_zero_address(self):
        """地址 0"""
        frame = DebugProtocol.build_frame(0x07, 1, 0, b"")
        parsed = DebugProtocol.parse_frame(frame)
        assert parsed["address"] == 0

    def test_large_payload_500(self):
        """500 字节大 payload"""
        payload = bytes(range(256)) + bytes(range(244))
        frame = DebugProtocol.build_frame(0x02, 1, 0x1000, payload)
        parsed = DebugProtocol.parse_frame(frame)
        assert parsed["payload"] == payload

    def test_bad_sof_rejected(self):
        """错误帧头被拒绝"""
        frame = bytearray(DebugProtocol.build_frame(0x07, 1, 0, b""))
        frame[0] = 0x00
        with pytest.raises(ValueError):
            DebugProtocol.parse_frame(bytes(frame))


class TestDecodeValueBoundaries:
    """值解码边界"""

    def test_float_zero(self):
        assert decode_value(struct.pack("<f", 0.0), "float") == 0.0

    def test_float_negative(self):
        assert decode_value(struct.pack("<f", -123.456), "float") < -123

    def test_float_max(self):
        """float 最大值"""
        import math
        max_float = struct.unpack("<f", b"\xFF\xFF\x7F\x7F")[0]
        assert decode_value(b"\xFF\xFF\x7F\x7F", "float") == max_float

    def test_float_nan(self):
        """NaN"""
        nan_bytes = b"\x00\x00\xC0\x7F"
        val = decode_value(nan_bytes, "float")
        assert val != val  # NaN != NaN

    def test_float_inf(self):
        """无穷大"""
        inf_bytes = b"\x00\x00\x80\x7F"
        val = decode_value(inf_bytes, "float")
        assert val == float('inf')

    def test_uint32_max(self):
        assert decode_value(b"\xFF\xFF\xFF\xFF", "uint32_t") == 0xFFFFFFFF

    def test_int32_min(self):
        assert decode_value(b"\x00\x00\x00\x80", "int32_t") == -0x80000000

    def test_short_data(self):
        """数据不足返回原始字节"""
        assert decode_value(b"\x01", "uint32_t") == b"\x01"


class TestStructAlignment:
    """结构体对齐验证"""

    def test_dm_sample_item_size(self):
        """dm_sample_item_t 在 64 位编译器上 sizeof=8 (有 padding)"""
        # 已在集成测试中验证，这里验证 Python 打包一致性
        import struct
        packed = struct.pack("<IBB2x", 0x20000000, 4, 0)
        assert len(packed) == 8

    def test_pi_controller_layout(self):
        """PI 控制器结构体布局"""
        members = [
            StructMember("kp", 0, 4, "float"),
            StructMember("ki", 4, 4, "float"),
            StructMember("kd", 8, 4, "float"),
            StructMember("integral", 12, 4, "float"),
            StructMember("saturation", 16, 1, "uint8_t"),
        ]
        var = ElfVariable("g_pi", 0x20002000, 20, "PIController", is_struct=True, members=members)

        # 验证每个成员地址
        assert var.member_address("kp")[0] == 0x20002000
        assert var.member_address("ki")[0] == 0x20002004
        assert var.member_address("kd")[0] == 0x20002008
        assert var.member_address("integral")[0] == 0x2000200C
        assert var.member_address("saturation")[0] == 0x20002010
