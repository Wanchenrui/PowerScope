"""
test_stress_perf.py — 性能压力测试

验证 C 核心库在高频/大数据量场景下的性能和稳定性。
覆盖: CRC16 百万次/环形缓冲区十万次/Modbus 千次/调试协议万次/流式连续采集。
"""
import os, sys, struct, time, ctypes, pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from power_scope.core.cffi_loader import CRC16, RingBuffer, ModbusCodec, DebugProtocol

# MockMCU 路径
_PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestCRC16Performance:
    """CRC16 性能测试"""

    def test_crc16_1mb_throughput(self):
        """1MB 数据 CRC16 计算耗时 < 50ms"""
        data = b"\x55" * (1024 * 1024)
        t0 = time.perf_counter()
        for _ in range(10):
            CRC16.calc(data)
        elapsed = (time.perf_counter() - t0) / 10
        assert elapsed < 0.05, f"CRC16 1MB耗时 {elapsed*1000:.1f}ms > 50ms"

    def test_crc16_10000_random_small(self):
        """10000 次小数据 CRC16 计算，结果稳定"""
        import random
        random.seed(777)
        results = set()
        t0 = time.perf_counter()
        for _ in range(10000):
            data = bytes(random.randint(0, 255) for _ in range(random.randint(1, 64)))
            results.add(CRC16.calc(data))
        elapsed = time.perf_counter() - t0
        assert elapsed < 1.0, f"10000次CRC耗时 {elapsed:.2f}s"
        assert len(results) > 100  # 结果分布应足够分散

    def test_crc16_continue_large_stream(self):
        """流式 CRC 续算 1MB 分块，结果与整体计算一致"""
        data = b"\xAA\xBB\xCC" * (350000)  # ~1MB
        whole = CRC16.calc(data)
        # 分 1000 字节块续算
        crc = 0xFFFF
        for i in range(0, len(data), 1000):
            chunk = data[i:i+1000]
            crc = CRC16.continue_calc(crc, chunk)
        assert crc == whole


class TestRingBufferStress:
    """环形缓冲区压力测试"""

    def test_100k_write_read_cycles(self):
        """10万次写读循环，无数据丢失"""
        rb = RingBuffer(1024)
        import random
        random.seed(42)
        for _ in range(100000):
            n = random.randint(1, 100)
            data = bytes(random.randint(0, 255) for _ in range(n))
            written = rb.write(data)
            read = rb.read(written)
            assert read == data[:written]
        assert rb.available == 0

    def test_overflow_behavior(self):
        """缓冲区满后写入丢弃超出部分"""
        rb = RingBuffer(64)
        # 写满
        w1 = rb.write(b"\x01" * 64)
        assert w1 == 64
        # 再写应返回0 (满)
        w2 = rb.write(b"\x02" * 10)
        assert w2 == 0
        assert rb.available == 64
        # 读一半再写
        rb.read(32)
        w3 = rb.write(b"\x03" * 40)
        assert w3 == 32  # 只能写剩余空间

    def test_wraparound_stress(self):
        """多次回绕测试"""
        rb = RingBuffer(16)
        for cycle in range(1000):
            rb.write(b"\xAA" * 12)
            rb.read(12)
        assert rb.available == 0
        assert rb.free_space == 16

    def test_capacity_boundaries(self):
        """各种容量边界: 1, 2, 3, 7(非2幂), 1024"""
        for cap in [1, 2, 3, 7, 8, 1024]:
            rb = RingBuffer(cap)
            assert rb.capacity == cap
            rb.write(b"\xFF" * cap)
            assert rb.available == cap
            data = rb.read(cap)
            assert data == b"\xFF" * cap


class TestModbusPerformance:
    """Modbus 编解码性能"""

    def test_build_parse_10000_roundtrips(self):
        """10000 次 Modbus 构建→解析 roundtrip"""
        import random
        random.seed(123)
        t0 = time.perf_counter()
        for _ in range(10000):
            slave = random.randint(1, 247)
            count = random.randint(1, 20)
            regs = [random.randint(0, 65535) for _ in range(count)]
            # 构建响应
            payload = struct.pack(">BBB", slave, 3, count * 2)
            for r in regs:
                payload += struct.pack(">H", r)
            crc = CRC16.calc(payload)
            resp = payload + struct.pack("<H", crc)
            result = ModbusCodec.parse_response(resp)
            assert result["registers"] == regs
        elapsed = time.perf_counter() - t0
        assert elapsed < 2.0, f"10000次roundtrip {elapsed:.2f}s"

    def test_max_register_count(self):
        """最大寄存器数量 (125个)"""
        regs = list(range(125))
        payload = struct.pack(">BBB", 1, 3, 250)
        for r in regs:
            payload += struct.pack(">H", r)
        crc = CRC16.calc(payload)
        resp = payload + struct.pack("<H", crc)
        result = ModbusCodec.parse_response(resp)
        assert len(result["registers"]) == 125
        assert result["registers"] == regs


class TestDebugProtocolStress:
    """调试协议压力测试"""

    def test_build_parse_5000_frames(self):
        """5000 次调试帧构建→解析"""
        import random
        random.seed(999)
        for _ in range(5000):
            cmd = random.choice([0x01, 0x02, 0x07, 0x08])
            seq = random.randint(0, 65535)
            addr = random.randint(0, 0xFFFFFFFF)
            plen = random.randint(0, 200)
            payload = bytes(random.randint(0, 255) for _ in range(plen))
            frame = DebugProtocol.build_frame(cmd, seq, addr, payload)
            parsed = DebugProtocol.parse_frame(frame)
            assert parsed["cmd"] == cmd
            assert parsed["seq"] == seq
            assert parsed["address"] == addr
            assert parsed["payload"] == payload

    def test_stream_frame_1000(self):
        """1000 次流式帧构建"""
        import random
        random.seed(888)
        for _ in range(1000):
            seq = random.randint(0, 65535)
            ts = random.randint(0, 0xFFFFFFFF)
            data = bytes(random.randint(0, 255) for _ in range(random.randint(1, 100)))
            frame = DebugProtocol.build_stream_frame(seq, ts, 0, 1, data)
            assert len(frame) == 12 + len(data) + 2
            assert frame[0] == 0xA5 and frame[1] == 0x5A


class TestMockMCUStress:
    """模拟 MCU 压力测试 — 高频流式采集"""

    @pytest.fixture
    def mcu(self):
        dll_path = os.path.join(_PROJECT, "mock_mcu.dll")
        d = ctypes.CDLL(dll_path)
        d.mock_init.restype = None
        d.mock_feed_byte.argtypes = [ctypes.c_uint8]; d.mock_feed_byte.restype = None
        d.mock_feed_bytes.argtypes = [ctypes.c_char_p, ctypes.c_uint32]; d.mock_feed_bytes.restype = None
        d.mock_tick.restype = None
        d.mock_get_tx_len.restype = ctypes.c_uint32
        d.mock_read_tx.argtypes = [ctypes.c_char_p, ctypes.c_uint32]; d.mock_read_tx.restype = ctypes.c_uint32
        d.mock_clear_tx.restype = None
        d.mock_mem_write.argtypes = [ctypes.c_uint32, ctypes.c_char_p, ctypes.c_uint32]; d.mock_mem_write.restype = None
        d.mock_get_mem_base.restype = ctypes.c_uint32
        d.mock_init()
        return d

    def test_stream_1000_samples(self, mcu):
        """连续 1000 次流式采样，验证无崩溃和数据完整性"""
        from power_scope.debug.elf_parser import ElfVariable, decode_value
        base = mcu.mock_get_mem_base()
        var = ElfVariable("g_id", base, 4, "float")

        # 配置采样列表
        pl = struct.pack("<BHB", 0, 1000, 1) + struct.pack("<IBB2x", var.address, var.size, 0)
        frame = DebugProtocol.build_frame(0x04, 1, 0, pl)
        mcu.mock_feed_bytes(frame, len(frame))
        mcu.mock_read_tx(ctypes.create_string_buffer(64), 64)  # 清响应

        # 启动
        frame = DebugProtocol.build_frame(0x05, 2, 0, bytes([0]))
        mcu.mock_feed_bytes(frame, len(frame))
        mcu.mock_read_tx(ctypes.create_string_buffer(64), 64)

        # 连续 1000 次 tick
        mcu.mock_clear_tx()
        for i in range(1000):
            val = float(i) * 0.1
            mcu.mock_mem_write(0, struct.pack("<f", val), 4)
            mcu.mock_tick()

        # 验证 TX 数据量 (每帧 12+4+2=18 字节)
        tx_len = mcu.mock_get_tx_len()
        assert tx_len == 1000 * 18, f"期望 {1000*18}, 实际 {tx_len}"
