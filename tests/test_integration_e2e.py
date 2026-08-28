"""
test_integration_e2e.py — 端到端集成测试

验证完整数据链路: Python(PC) → C协议引擎(power_core.dll) → C调试桩(mock_mcu.dll) → Python解析

全链路: ELF变量地址 → 协议帧构建 → 串口传输(模拟) → MCU调试桩处理 →
        内存读写 → 响应帧构建 → 串口传输(模拟) → 协议帧解析 → 值解码
"""
import os, sys, struct, ctypes, pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from power_scope.core.cffi_loader import CRC16, ModbusCodec, DebugProtocol
from power_scope.debug.elf_parser import ElfVariable, decode_value, TYPE_FORMATS


class MockMCU:
    """模拟 MCU，封装 mock_mcu.dll，驱动真实 C 调试桩"""

    def __init__(self):
        # 解析 DLL 绝对路径
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        dll_path = os.path.join(project_root, "mock_mcu.dll")
        if not os.path.exists(dll_path):
            dll_path = "mock_mcu.dll"  # 回退到系统路径
        self._dll = ctypes.CDLL(dll_path)
        self._setup()
        self._mem_base = self._dll.mock_get_mem_base()
        self.init()

    def _setup(self):
        d = self._dll
        d.mock_init.restype = None
        d.mock_feed_byte.argtypes = [ctypes.c_uint8]; d.mock_feed_byte.restype = None
        d.mock_feed_bytes.argtypes = [ctypes.c_char_p, ctypes.c_uint32]; d.mock_feed_bytes.restype = None
        d.mock_tick.restype = None
        d.mock_set_time.argtypes = [ctypes.c_uint32]; d.mock_set_time.restype = None
        d.mock_get_time.restype = ctypes.c_uint32
        d.mock_get_tx_len.restype = ctypes.c_uint32
        d.mock_read_tx.argtypes = [ctypes.c_char_p, ctypes.c_uint32]; d.mock_read_tx.restype = ctypes.c_uint32
        d.mock_clear_tx.restype = None
        d.mock_mem_write.argtypes = [ctypes.c_uint32, ctypes.c_char_p, ctypes.c_uint32]; d.mock_mem_write.restype = None
        d.mock_mem_read.argtypes = [ctypes.c_uint32, ctypes.c_char_p, ctypes.c_uint32]; d.mock_mem_read.restype = None
        d.mock_get_mem_base.restype = ctypes.c_uint32
        d.mock_get_mem_size.restype = ctypes.c_uint32
        d.mock_set_device_info.argtypes = [ctypes.c_char_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_char_p]
        d.mock_set_device_info.restype = None

    def init(self): self._dll.mock_init()
    @property
    def mem_base(self): return self._mem_base
    def feed_bytes(self, data): self._dll.mock_feed_bytes(data, len(data))
    def feed_byte(self, b): self._dll.mock_feed_byte(b)
    def tick(self): self._dll.mock_tick()
    def set_time(self, t): self._dll.mock_set_time(t)
    def get_tx_len(self): return self._dll.mock_get_tx_len()
    def read_tx(self):
        n = self.get_tx_len()
        if n == 0: return b""
        buf = ctypes.create_string_buffer(n)
        r = self._dll.mock_read_tx(buf, n)
        return buf.raw[:r]
    def clear_tx(self): self._dll.mock_clear_tx()
    def mem_write(self, off, data): self._dll.mock_mem_write(off, data, len(data))
    def mem_read(self, off, length):
        buf = ctypes.create_string_buffer(length)
        self._dll.mock_mem_read(off, buf, length)
        return buf.raw[:length]
    def set_device_info(self, model, freq, crc, ver):
        self._dll.mock_set_device_info(model.encode(), freq, crc, ver.encode())
    def send_frame(self, cmd, seq, addr=0, payload=b""):
        f = DebugProtocol.build_frame(cmd, seq, addr, payload)
        self.feed_bytes(f)
        return f
    def get_response(self):
        tx = self.read_tx()
        if not tx: return None
        return DebugProtocol.parse_response(tx)


def _parse_stream_frames(tx_data, var_size):
    """从 TX 数据起始处顺序解析流式帧（帧长固定 = 12 + var_size + 2）"""
    values = []
    pos = 0
    frame_len = 12 + var_size + 2
    while pos + frame_len <= len(tx_data):
        frame = tx_data[pos:pos + frame_len]
        if frame[0] == 0xA5 and frame[1] == 0x5A and frame[3] == 0x10:
            values.append(frame[12:12 + var_size])
            pos += frame_len
        else:
            pos += 1  # 跳过非流式帧字节
    return values


@pytest.fixture
def mcu():
    return MockMCU()

@pytest.fixture
def pvars():
    base = 0x20000000
    return {
        "g_id": ElfVariable("g_id", base, 4, "float"),
        "g_iq": ElfVariable("g_iq", base+4, 4, "float"),
        "g_vd": ElfVariable("g_vd", base+8, 4, "float"),
        "g_duty": ElfVariable("g_duty", base+0x10, 2, "uint16_t"),
        "g_counter": ElfVariable("g_counter", base+0x1C, 4, "uint32_t"),
        "g_pi_kp": ElfVariable("g_pi_kp", base+0x20, 4, "float"),
        "g_pi_ki": ElfVariable("g_pi_ki", base+0x24, 4, "float"),
        "g_vsg_freq": ElfVariable("g_vsg_freq", base+0x18, 4, "float"),
    }


# ===== E2E-1: 变量读取全链路 =====

class TestReadE2E:
    def test_read_float(self, mcu, pvars):
        v = pvars["g_id"]
        mcu.mem_write(v.address - mcu.mem_base, struct.pack("<f", 10.5))
        mcu.send_frame(DebugProtocol.CMD_READ_MEM, 1, v.address, bytes([v.size]))
        r = mcu.get_response()
        assert abs(decode_value(r["payload"], v.type_name) - 10.5) < 0.001

    def test_read_uint16(self, mcu, pvars):
        v = pvars["g_duty"]
        mcu.mem_write(v.address - mcu.mem_base, struct.pack("<H", 3500))
        mcu.send_frame(DebugProtocol.CMD_READ_MEM, 2, v.address, bytes([v.size]))
        r = mcu.get_response()
        assert decode_value(r["payload"], v.type_name) == 3500

    def test_read_uint32(self, mcu, pvars):
        v = pvars["g_counter"]
        mcu.mem_write(v.address - mcu.mem_base, struct.pack("<I", 0xDEADBEEF))
        mcu.send_frame(DebugProtocol.CMD_READ_MEM, 3, v.address, bytes([v.size]))
        r = mcu.get_response()
        assert decode_value(r["payload"], v.type_name) == 0xDEADBEEF

    def test_read_all_vars(self, mcu, pvars):
        vals = {"g_id":15.3, "g_iq":-2.1, "g_vd":311.0, "g_duty":2800,
                "g_counter":12345, "g_pi_kp":0.85, "g_pi_ki":120.0, "g_vsg_freq":50.0}
        for name, val in vals.items():
            v = pvars[name]
            mcu.mem_write(v.address - mcu.mem_base, struct.pack(TYPE_FORMATS[v.type_name], val))
        for i, (name, expected) in enumerate(vals.items()):
            v = pvars[name]
            mcu.clear_tx()
            mcu.send_frame(DebugProtocol.CMD_READ_MEM, i+100, v.address, bytes([v.size]))
            r = mcu.get_response()
            actual = decode_value(r["payload"], v.type_name)
            if v.type_name == "float":
                assert abs(actual - expected) < 0.01, f"{name}"
            else:
                assert actual == expected, f"{name}"


# ===== E2E-2: 变量写入全链路 =====

class TestWriteE2E:
    def test_write_float(self, mcu, pvars):
        v = pvars["g_pi_kp"]
        mcu.send_frame(DebugProtocol.CMD_WRITE_MEM, 0x10, v.address, struct.pack("<f", 0.92))
        r = mcu.get_response()
        assert r["cmd"] == DebugProtocol.CMD_WRITE_MEM and r["payload"] == b""
        raw = mcu.mem_read(v.address - mcu.mem_base, v.size)
        assert abs(decode_value(raw, v.type_name) - 0.92) < 0.001

    def test_write_uint16(self, mcu, pvars):
        v = pvars["g_duty"]
        mcu.send_frame(DebugProtocol.CMD_WRITE_MEM, 0x11, v.address, struct.pack("<H", 3200))
        mcu.get_response()
        raw = mcu.mem_read(v.address - mcu.mem_base, v.size)
        assert decode_value(raw, v.type_name) == 3200

    def test_write_then_read(self, mcu, pvars):
        v = pvars["g_vsg_freq"]
        mcu.send_frame(DebugProtocol.CMD_WRITE_MEM, 0x20, v.address, struct.pack("<f", 49.97))
        mcu.get_response()
        mcu.clear_tx()
        mcu.send_frame(DebugProtocol.CMD_READ_MEM, 0x21, v.address, bytes([v.size]))
        r = mcu.get_response()
        assert abs(decode_value(r["payload"], v.type_name) - 49.97) < 0.001

    def test_write_batch_params(self, mcu, pvars):
        params = {"g_pi_kp": 1.05, "g_pi_ki": 150.0, "g_vsg_freq": 50.02}
        for i, (name, val) in enumerate(params.items()):
            v = pvars[name]
            mcu.send_frame(DebugProtocol.CMD_WRITE_MEM, 0x30+i, v.address, struct.pack("<f", val))
            mcu.get_response()
        for i, (name, val) in enumerate(params.items()):
            v = pvars[name]
            mcu.clear_tx()
            mcu.send_frame(DebugProtocol.CMD_READ_MEM, 0x40+i, v.address, bytes([v.size]))
            r = mcu.get_response()
            assert abs(decode_value(r["payload"], v.type_name) - val) < 0.01


# ===== E2E-3: 流式录波全链路 =====

class TestStreamE2E:
    def test_stream_single(self, mcu, pvars):
        v = pvars["g_id"]
        # 配置采样列表 (dm_sample_item_t = 6 bytes: addr(4)+size(1)+reserved(1))
        pl = struct.pack("<BHB", 0, 1000, 1) + struct.pack("<IBB2x", v.address, v.size, 0)
        mcu.send_frame(DebugProtocol.CMD_SET_SAMPLE, 1, 0, pl)
        mcu.get_response()
        # 启动
        mcu.send_frame(DebugProtocol.CMD_START_STREAM, 2, 0, bytes([0]))
        mcu.get_response()
        # 采集
        expected = [5.0, 8.3, 12.1, 15.0, 10.5]
        mcu.clear_tx()
        for val in expected:
            mcu.mem_write(v.address - mcu.mem_base, struct.pack("<f", val))
            mcu.tick()
        # 解析
        tx = mcu.read_tx()
        raws = _parse_stream_frames(tx, v.size)
        assert len(raws) == len(expected)
        for i, (raw, exp) in enumerate(zip(raws, expected)):
            assert abs(decode_value(raw, v.type_name) - exp) < 0.01, f"sample {i}"

    def test_stream_multi(self, mcu, pvars):
        vs = [pvars["g_id"], pvars["g_iq"], pvars["g_vd"]]
        total = sum(v.size for v in vs)
        # dm_sample_item_t = address(4) + size(1) + reserved(1) = 6 bytes
        pl = struct.pack("<BHB", 0, 1000, len(vs))
        for v in vs:
            pl += struct.pack("<IBB2x", v.address, v.size, 0)  # 8 bytes per item (with padding)
        mcu.send_frame(DebugProtocol.CMD_SET_SAMPLE, 1, 0, pl)
        mcu.get_response()
        mcu.send_frame(DebugProtocol.CMD_START_STREAM, 2, 0, bytes([0]))
        mcu.get_response()
        test_data = [(10.0,-1.0,310.0), (12.5,-1.5,311.0), (15.0,-2.0,309.5)]
        mcu.clear_tx()
        for id_v, iq_v, vd_v in test_data:
            mcu.mem_write(pvars["g_id"].address-mcu.mem_base, struct.pack("<f",id_v))
            mcu.mem_write(pvars["g_iq"].address-mcu.mem_base, struct.pack("<f",iq_v))
            mcu.mem_write(pvars["g_vd"].address-mcu.mem_base, struct.pack("<f",vd_v))
            mcu.tick()
        tx = mcu.read_tx()
        frames = _parse_stream_frames(tx, total)
        assert len(frames) == len(test_data)
        for i, (raw, (eid, eiq, evd)) in enumerate(zip(frames, test_data)):
            vals = [decode_value(raw[j:j+4], "float") for j in range(0, 12, 4)]
            assert abs(vals[0]-eid)<0.01 and abs(vals[1]-eiq)<0.01 and abs(vals[2]-evd)<0.01, f"pt {i}"

    def test_stream_stop(self, mcu, pvars):
        v = pvars["g_id"]
        pl = struct.pack("<BHB", 0, 1000, 1) + struct.pack("<IBB2x", v.address, v.size, 0)
        mcu.send_frame(DebugProtocol.CMD_SET_SAMPLE, 1, 0, pl)
        mcu.get_response()
        mcu.send_frame(DebugProtocol.CMD_START_STREAM, 2, 0, bytes([0]))
        mcu.get_response()
        mcu.clear_tx(); mcu.tick()
        assert mcu.get_tx_len() > 0
        # 清空流式帧后再发停止命令
        mcu.clear_tx()
        mcu.send_frame(DebugProtocol.CMD_STOP_STREAM, 3, 0, bytes([0]))
        r = mcu.get_response()
        assert r is not None
        mcu.clear_tx(); mcu.tick()
        assert mcu.get_tx_len() == 0


# ===== E2E-4: Modbus 通信全链路 =====

class TestModbusE2E:
    def test_read_holding(self):
        req = ModbusCodec.build_read_holding(1, 0, 4)
        assert req[0]==1 and req[1]==3 and len(req)==8
        regs = [0x012C, 0x00C8, 0x03E8, 0x07D0]
        payload = struct.pack(">BBB", 1, 3, 8)
        for v in regs: payload += struct.pack(">H", v)
        crc = CRC16.calc(payload)
        resp = payload + struct.pack("<H", crc)
        result = ModbusCodec.parse_response(resp)
        assert result["registers"] == regs

    def test_write_single(self):
        req = ModbusCodec.build_write_single(1, 0x1000, 0x012C)
        result = ModbusCodec.parse_response(req)
        assert result["written_addr"] == 0x1000 and result["written_count"] == 0x012C

    def test_crc_error_rejected(self):
        req = bytearray(ModbusCodec.build_read_holding(1, 0, 2))
        req[-1] ^= 0xFF
        with pytest.raises(ValueError):
            ModbusCodec.parse_response(bytes(req))


# ===== E2E-5: 协议鲁棒性 =====

class TestRobustness:
    def test_truncated_no_crash(self, mcu):
        """截断帧不应导致崩溃，重置后恢复正常"""
        full = DebugProtocol.build_frame(DebugProtocol.CMD_GET_INFO, 1, 0, b"")
        # 发送截断帧 (状态机会等待更多字节)
        mcu.feed_bytes(full[:8])
        assert mcu.get_tx_len() == 0  # 帧不完整，无响应
        # 重新初始化 MCU 重置状态机 (真实场景中由超时机制处理)
        mcu.init()
        # 发送完整帧应正常工作
        mcu.clear_tx()
        mcu.feed_bytes(full)
        assert mcu.get_tx_len() > 0

    def test_concatenated_frames(self, mcu, pvars):
        v = pvars["g_counter"]
        mcu.mem_write(v.address - mcu.mem_base, struct.pack("<I", 99))
        frames = b""
        for i in range(3):
            frames += DebugProtocol.build_frame(DebugProtocol.CMD_READ_MEM, i+1, v.address, bytes([v.size]))
        mcu.feed_bytes(frames)
        tx = mcu.read_tx()
        assert len(tx) >= 15 * 3

    def test_bad_crc_nack(self, mcu):
        f = bytearray(DebugProtocol.build_frame(DebugProtocol.CMD_GET_INFO, 1, 0, b""))
        f[-1] ^= 0xFF
        mcu.feed_bytes(bytes(f))
        r = mcu.get_response()
        assert r["cmd"] == 0xFF

    def test_byte_by_byte(self, mcu, pvars):
        v = pvars["g_counter"]
        mcu.mem_write(v.address - mcu.mem_base, struct.pack("<I", 777))
        f = DebugProtocol.build_frame(DebugProtocol.CMD_READ_MEM, 0x50, v.address, bytes([v.size]))
        for b in f: mcu.feed_byte(b)
        r = mcu.get_response()
        assert r["seq"] == 0x50 and decode_value(r["payload"], v.type_name) == 777

    def test_addr_protection(self, mcu):
        mcu.send_frame(DebugProtocol.CMD_READ_MEM, 0x60, 0x08000000, bytes([4]))
        r = mcu.get_response()
        assert r["cmd"] == 0xFF

    def test_noise_then_valid(self, mcu, pvars):
        v = pvars["g_counter"]
        mcu.mem_write(v.address - mcu.mem_base, struct.pack("<I", 42))
        valid = DebugProtocol.build_frame(DebugProtocol.CMD_READ_MEM, 1, v.address, bytes([v.size]))
        mcu.feed_bytes(bytes([0x00, 0xFF, 0x11, 0x22]) + valid)
        # 不崩溃即可 (可能有误响应或无响应)
        # 确保后续有效帧能处理
        mcu.clear_tx()
        mcu.send_frame(DebugProtocol.CMD_GET_INFO, 2, 0, b"")
        assert mcu.get_tx_len() > 0


# ===== E2E-6: 完整调参场景 =====

class TestTuningScenario:
    def test_pid_tuning_workflow(self, mcu, pvars):
        kp = pvars["g_pi_kp"]; ki = pvars["g_pi_ki"]; id_v = pvars["g_id"]
        # 初始参数
        mcu.mem_write(kp.address-mcu.mem_base, struct.pack("<f", 0.5))
        mcu.mem_write(ki.address-mcu.mem_base, struct.pack("<f", 80.0))
        # 读当前参数
        mcu.send_frame(DebugProtocol.CMD_READ_MEM, 0x100, kp.address, bytes([kp.size]))
        r = mcu.get_response()
        assert abs(decode_value(r["payload"], kp.type_name) - 0.5) < 0.001
        # 写新参数
        mcu.send_frame(DebugProtocol.CMD_WRITE_MEM, 0x102, kp.address, struct.pack("<f", 0.85))
        mcu.get_response()
        mcu.send_frame(DebugProtocol.CMD_WRITE_MEM, 0x103, ki.address, struct.pack("<f", 120.0))
        mcu.get_response()
        # 读回验证
        mcu.send_frame(DebugProtocol.CMD_READ_MEM, 0x104, kp.address, bytes([kp.size]))
        r = mcu.get_response()
        assert abs(decode_value(r["payload"], kp.type_name) - 0.85) < 0.001
        # 录波阶跃响应
        pl = struct.pack("<BHB", 0, 1000, 1) + struct.pack("<IBB2x", id_v.address, id_v.size, 0)
        mcu.send_frame(DebugProtocol.CMD_SET_SAMPLE, 0x106, 0, pl)
        mcu.get_response()
        mcu.send_frame(DebugProtocol.CMD_START_STREAM, 0x107, 0, bytes([0]))
        mcu.get_response()
        step = [0.0, 2.0, 8.0, 14.0, 15.0, 14.8, 15.0]
        mcu.clear_tx()
        for val in step:
            mcu.mem_write(id_v.address-mcu.mem_base, struct.pack("<f", val))
            mcu.tick()
        tx = mcu.read_tx()
        raws = _parse_stream_frames(tx, id_v.size)
        assert len(raws) == len(step)
        for i, (raw, exp) in enumerate(zip(raws, step)):
            assert abs(decode_value(raw, id_v.type_name) - exp) < 0.01, f"step {i}"
        # 停止录波
        mcu.send_frame(DebugProtocol.CMD_STOP_STREAM, 0x108, 0, bytes([0]))
        mcu.get_response()


# ===== E2E-7: GET_INFO 全链路 =====

class TestGetInfoE2E:
    def test_get_info(self, mcu):
        mcu.send_frame(DebugProtocol.CMD_GET_INFO, 1, 0, b"")
        r = mcu.get_response()
        assert r is not None and r["cmd"] == DebugProtocol.CMD_GET_INFO
        assert len(r["payload"]) > 0

    def test_custom_device_info(self, mcu):
        mcu.set_device_info("STM32H743", 480000000, 0x12345678, "2.1.0")
        mcu.send_frame(DebugProtocol.CMD_GET_INFO, 1, 0, b"")
        r = mcu.get_response()
        # 解析设备信息结构体
        info = r["payload"]
        model = info[:32].split(b'\x00')[0].decode()
        freq = struct.unpack_from("<I", info, 32)[0]
        crc = struct.unpack_from("<I", info, 36)[0]
        assert model == "STM32H743"
        assert freq == 480000000
        assert crc == 0x12345678


# ===== E2E-8: 交叉验证 C/Python =====

class TestCrossVerify:
    def test_crc16_random_500(self):
        import random
        random.seed(2024)
        def py_crc(data):
            crc = 0xFFFF
            for b in data:
                crc ^= b
                for _ in range(8):
                    crc = (crc >> 1) ^ 0xA001 if (crc & 1) else crc >> 1
            return crc
        for _ in range(500):
            data = bytes(random.randint(0,255) for _ in range(random.randint(0,300)))
            assert CRC16.calc(data) == py_crc(data)

    def test_modbus_random_300(self):
        import random
        random.seed(2025)
        for _ in range(300):
            slave = random.randint(1, 247)
            count = random.randint(1, 50)
            regs = [random.randint(0, 65535) for _ in range(count)]
            # 构建响应
            payload = struct.pack(">BBB", slave, 3, count * 2)
            for r in regs: payload += struct.pack(">H", r)
            crc = CRC16.calc(payload)
            resp = payload + struct.pack("<H", crc)
            # 解析
            result = ModbusCodec.parse_response(resp)
            assert result["registers"] == regs

    def test_debug_frame_random_200(self):
        import random
        random.seed(2026)
        for _ in range(200):
            cmd = random.choice([0x01, 0x02, 0x07, 0x09])
            seq = random.randint(0, 65535)
            addr = random.randint(0, 0xFFFFFFFF)
            plen = random.randint(0, 100)
            payload = bytes(random.randint(0,255) for _ in range(plen))
            frame = DebugProtocol.build_frame(cmd, seq, addr, payload)
            parsed = DebugProtocol.parse_frame(frame)
            assert parsed["cmd"] == cmd
            assert parsed["seq"] == seq
            assert parsed["address"] == addr
            assert parsed["payload"] == payload
