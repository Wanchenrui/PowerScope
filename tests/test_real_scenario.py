"""
test_real_scenario.py — 真实功率调试场景模拟
"""
import os, sys, struct, ctypes, pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from power_scope.core.cffi_loader import CRC16, ModbusCodec, DebugProtocol
from power_scope.debug.elf_parser import ElfVariable, decode_value, TYPE_FORMATS

_PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class PowerScopeSim:
    """模拟 PowerScope 工具"""
    def __init__(self):
        dll = os.path.join(_PROJECT, "mock_mcu.dll")
        self._d = ctypes.CDLL(dll)
        self._setup()
        self._d.mock_init()
        self.base = self._d.mock_get_mem_base()
        self.seq = 0

    def _setup(self):
        d = self._d
        d.mock_init.restype = None
        d.mock_feed_byte.argtypes = [ctypes.c_uint8]; d.mock_feed_byte.restype = None
        d.mock_feed_bytes.argtypes = [ctypes.c_char_p, ctypes.c_uint32]; d.mock_feed_bytes.restype = None
        d.mock_tick.restype = None
        d.mock_get_tx_len.restype = ctypes.c_uint32
        d.mock_read_tx.argtypes = [ctypes.c_char_p, ctypes.c_uint32]; d.mock_read_tx.restype = ctypes.c_uint32
        d.mock_clear_tx.restype = None
        d.mock_mem_write.argtypes = [ctypes.c_uint32, ctypes.c_char_p, ctypes.c_uint32]; d.mock_mem_write.restype = None
        d.mock_get_mem_base.restype = ctypes.c_uint32
        d.mock_set_device_info.argtypes = [ctypes.c_char_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_char_p]
        d.mock_set_device_info.restype = None

    def _next_seq(self):
        self.seq = (self.seq + 1) & 0xFFFF
        return self.seq

    def read_var(self, var):
        self._d.mock_clear_tx()
        frame = DebugProtocol.build_frame(DebugProtocol.CMD_READ_MEM, self._next_seq(), var.address, bytes([var.size]))
        self._d.mock_feed_bytes(frame, len(frame))
        n = self._d.mock_get_tx_len()
        buf = ctypes.create_string_buffer(n)
        self._d.mock_read_tx(buf, n)
        resp = DebugProtocol.parse_response(buf.raw[:n])
        return decode_value(resp["payload"], var.type_name)

    def write_var(self, var, value):
        self._d.mock_clear_tx()
        fmt = TYPE_FORMATS.get(var.type_name, "<I")
        encoded = struct.pack(fmt, value)
        frame = DebugProtocol.build_frame(DebugProtocol.CMD_WRITE_MEM, self._next_seq(), var.address, encoded)
        self._d.mock_feed_bytes(frame, len(frame))
        n = self._d.mock_get_tx_len()
        buf = ctypes.create_string_buffer(n)
        self._d.mock_read_tx(buf, n)

    def setup_stream(self, list_id, variables, period_us=1000):
        self._d.mock_clear_tx()
        pl = struct.pack("<BHB", list_id, period_us, len(variables))
        for v in variables:
            pl += struct.pack("<IBB2x", v.address, v.size, 0)
        frame = DebugProtocol.build_frame(DebugProtocol.CMD_SET_SAMPLE, self._next_seq(), 0, pl)
        self._d.mock_feed_bytes(frame, len(frame))
        buf = ctypes.create_string_buffer(64)
        self._d.mock_read_tx(buf, 64)

    def start_stream(self, list_id=0):
        self._d.mock_clear_tx()
        frame = DebugProtocol.build_frame(DebugProtocol.CMD_START_STREAM, self._next_seq(), 0, bytes([list_id]))
        self._d.mock_feed_bytes(frame, len(frame))
        buf = ctypes.create_string_buffer(64)
        self._d.mock_read_tx(buf, 64)

    def stop_stream(self, list_id=0):
        self._d.mock_clear_tx()
        frame = DebugProtocol.build_frame(DebugProtocol.CMD_STOP_STREAM, self._next_seq(), 0, bytes([list_id]))
        self._d.mock_feed_bytes(frame, len(frame))
        buf = ctypes.create_string_buffer(64)
        self._d.mock_read_tx(buf, 64)

    def collect_stream_frames(self, var_size):
        """读取并解析所有流式帧"""
        n = self._d.mock_get_tx_len()
        if n == 0: return []
        buf = ctypes.create_string_buffer(n)
        self._d.mock_read_tx(buf, n)
        tx = buf.raw[:n]
        frame_len = 12 + var_size + 2
        results = []
        pos = 0
        while pos + frame_len <= len(tx):
            frame = tx[pos:pos+frame_len]
            if frame[0]==0xA5 and frame[1]==0x5A and frame[3]==0x10:
                results.append(frame[12:12+var_size])
                pos += frame_len
            else:
                pos += 1
        return results

    def set_mem(self, offset, data):
        self._d.mock_mem_write(offset, data, len(data))

    def set_device_info(self, model, freq, crc, ver):
        self._d.mock_set_device_info(model.encode(), freq, crc, ver.encode())


def _parse_stream_floats(tx_data, var_size):
    frame_len = 12 + var_size + 2
    results = []
    pos = 0
    while pos + frame_len <= len(tx_data):
        frame = tx_data[pos:pos+frame_len]
        if frame[0]==0xA5 and frame[1]==0x5A and frame[3]==0x10:
            results.append(frame[12:12+var_size])
            pos += frame_len
        else:
            pos += 1
    return results


@pytest.fixture
def scope():
    return PowerScopeSim()

@pytest.fixture
def vars():
    base = 0x20000000
    return {
        "g_id": ElfVariable("g_id", base, 4, "float"),
        "g_iq": ElfVariable("g_iq", base+4, 4, "float"),
        "g_vd": ElfVariable("g_vd", base+8, 4, "float"),
        "g_vq": ElfVariable("g_vq", base+12, 4, "float"),
        "g_duty_a": ElfVariable("g_duty_a", base+16, 2, "uint16_t"),
        "g_grid_angle": ElfVariable("g_grid_angle", base+24, 4, "float"),
        "g_grid_freq": ElfVariable("g_grid_freq", base+28, 4, "float"),
        "g_vsg_freq": ElfVariable("g_vsg_freq", base+32, 4, "float"),
        "g_pi_kp": ElfVariable("g_pi_kp", base+40, 4, "float"),
        "g_pi_ki": ElfVariable("g_pi_ki", base+44, 4, "float"),
        "g_fault_code": ElfVariable("g_fault_code", base+52, 1, "uint8_t"),
        "g_enable": ElfVariable("g_enable", base+53, 1, "uint8_t"),
    }


class TestScenario1Connect:
    """场景1: 连接 + 读设备信息 + 读所有变量"""
    def test_read_info(self, scope):
        scope.set_device_info("STM32G474", 170000000, 0xABCDEF12, "1.2.3")
        scope._d.mock_clear_tx()
        frame = DebugProtocol.build_frame(DebugProtocol.CMD_GET_INFO, 1, 0, b"")
        scope._d.mock_feed_bytes(frame, len(frame))
        n = scope._d.mock_get_tx_len()
        buf = ctypes.create_string_buffer(n)
        scope._d.mock_read_tx(buf, n)
        resp = DebugProtocol.parse_response(buf.raw[:n])
        info = resp["payload"]
        model = info[:32].split(b'\x00')[0].decode()
        assert model == "STM32G474"
        assert struct.unpack_from("<I", info, 32)[0] == 170000000

    def test_read_all_vars(self, scope, vars):
        vals = {"g_id":12.5, "g_iq":-0.3, "g_vd":311.1, "g_duty_a":2800,
                "g_grid_freq":50.0, "g_vsg_freq":50.01, "g_pi_kp":0.85,
                "g_pi_ki":120.0, "g_fault_code":0, "g_enable":1}
        for name, val in vals.items():
            v = vars[name]
            scope.set_mem(v.address-scope.base, struct.pack(TYPE_FORMATS[v.type_name], val))
        for name, expected in vals.items():
            v = vars[name]
            actual = scope.read_var(v)
            if v.type_name == "float":
                assert abs(actual-expected) < 0.01, f"{name}"
            else:
                assert actual == expected, f"{name}"


class TestScenario2StepResponse:
    """场景2: 阶跃响应录波"""
    def test_step_response(self, scope, vars):
        id_var = vars["g_id"]
        scope.setup_stream(0, [id_var], 1000)
        scope.start_stream(0)
        response = [0, 2, 6, 11, 15, 17, 16, 15.5, 15.1, 15.0, 15.0, 15.0]
        scope._d.mock_clear_tx()
        for val in response:
            scope.set_mem(id_var.address-scope.base, struct.pack("<f", val))
            scope._d.mock_tick()
        n = scope._d.mock_get_tx_len()
        buf = ctypes.create_string_buffer(n)
        scope._d.mock_read_tx(buf, n)
        raws = _parse_stream_floats(buf.raw[:n], 4)
        assert len(raws) == len(response)
        for i, (raw, exp) in enumerate(zip(raws, response)):
            assert abs(decode_value(raw, "float") - exp) < 0.01, f"step {i}"
        scope.stop_stream(0)

    def test_multi_channel(self, scope, vars):
        vs = [vars["g_id"], vars["g_iq"], vars["g_grid_angle"]]
        scope.setup_stream(0, vs, 1000)
        scope.start_stream(0)
        data = [(10.0,-0.5,0.0), (12.0,-0.8,0.5), (14.0,-1.0,1.0), (15.0,-1.2,1.5)]
        scope._d.mock_clear_tx()
        for id_v, iq_v, ang_v in data:
            scope.set_mem(vars["g_id"].address-scope.base, struct.pack("<f",id_v))
            scope.set_mem(vars["g_iq"].address-scope.base, struct.pack("<f",iq_v))
            scope.set_mem(vars["g_grid_angle"].address-scope.base, struct.pack("<f",ang_v))
            scope._d.mock_tick()
        n = scope._d.mock_get_tx_len()
        buf = ctypes.create_string_buffer(n)
        scope._d.mock_read_tx(buf, n)
        raws = _parse_stream_floats(buf.raw[:n], 12)
        assert len(raws) == len(data)
        for i, (raw, (eid,eiq,eang)) in enumerate(zip(raws, data)):
            vals = [decode_value(raw[j:j+4], "float") for j in range(0,12,4)]
            assert abs(vals[0]-eid)<0.01 and abs(vals[1]-eiq)<0.01 and abs(vals[2]-eang)<0.01, f"pt {i}"
        scope.stop_stream(0)


class TestScenario3Tuning:
    """场景3: PI 调参"""
    def test_tune_kp_ki(self, scope, vars):
        kp = vars["g_pi_kp"]; ki = vars["g_pi_ki"]
        scope.set_mem(kp.address-scope.base, struct.pack("<f", 0.5))
        scope.set_mem(ki.address-scope.base, struct.pack("<f", 80.0))
        assert abs(scope.read_var(kp) - 0.5) < 0.001
        scope.write_var(kp, 0.85)
        scope.write_var(ki, 120.0)
        assert abs(scope.read_var(kp) - 0.85) < 0.001
        assert abs(scope.read_var(ki) - 120.0) < 0.001

    def test_iterative_tuning(self, scope, vars):
        kp = vars["g_pi_kp"]; ki = vars["g_pi_ki"]; id_v = vars["g_id"]
        seq = [(0.5,80.0,10.0), (0.7,100.0,12.0), (0.85,120.0,14.5), (0.9,130.0,15.0)]
        for kpv, kiv, eid in seq:
            scope.write_var(kp, kpv)
            scope.write_var(ki, kiv)
            assert abs(scope.read_var(kp)-kpv) < 0.001
            assert abs(scope.read_var(ki)-kiv) < 0.001
            scope.set_mem(id_v.address-scope.base, struct.pack("<f", eid))
            assert abs(scope.read_var(id_v)-eid) < 0.01


class TestScenario4VSG:
    """场景4: VSG 频率监控"""
    def test_vsg_freq_stable(self, scope, vars):
        fv = vars["g_vsg_freq"]
        scope.setup_stream(0, [fv], 1000)
        scope.start_stream(0)
        freqs = [49.98,50.02,49.99,50.01,50.00,49.97,50.03,50.00,
                 49.96,50.04,49.99,50.01,50.00,50.00,49.98,50.02,
                 49.95,50.05,50.00,50.00]
        scope._d.mock_clear_tx()
        for f in freqs:
            scope.set_mem(fv.address-scope.base, struct.pack("<f", f))
            scope._d.mock_tick()
        n = scope._d.mock_get_tx_len()
        buf = ctypes.create_string_buffer(n)
        scope._d.mock_read_tx(buf, n)
        raws = _parse_stream_floats(buf.raw[:n], 4)
        assert len(raws) == len(freqs)
        recorded = [decode_value(r, "float") for r in raws]
        for f in recorded:
            assert 49.9 < f < 50.1
        avg = sum(recorded) / len(recorded)
        assert abs(avg - 50.0) < 0.05
        scope.stop_stream(0)


class TestScenario5Fault:
    """场景5: 故障检测"""
    def test_fault_monitoring(self, scope, vars):
        fv = vars["g_fault_code"]; ev = vars["g_enable"]
        scope.set_mem(fv.address-scope.base, struct.pack("<B", 0))
        scope.set_mem(ev.address-scope.base, struct.pack("<B", 1))
        assert scope.read_var(fv) == 0
        assert scope.read_var(ev) == 1
        scope.set_mem(fv.address-scope.base, struct.pack("<B", 0x10))
        assert scope.read_var(fv) == 0x10
        scope.set_mem(ev.address-scope.base, struct.pack("<B", 0))
        assert scope.read_var(ev) == 0


class TestScenario6Modbus:
    """场景6: Modbus 逆变器通信"""
    def test_read_inverter_status(self):
        regs = [0x0001, 0x0000, 0x0F9E, 0x0000]
        payload = struct.pack(">BBB", 1, 0x03, 8)
        for r in regs: payload += struct.pack(">H", r)
        crc = CRC16.calc(payload)
        result = ModbusCodec.parse_response(payload + struct.pack("<H", crc))
        assert result["registers"][0] == 1
        assert result["registers"][1] == 0
        # Modbus 32位值大端拼接: 高16位在前
        power = (result["registers"][2] << 16) | result["registers"][3]
        assert power == 0x0F9E0000  # 大端拼接结果

    def test_write_grid_param(self):
        frame = ModbusCodec.build_write_single(1, 200, 2200)
        assert struct.unpack(">H", frame[4:6])[0] == 2200


class TestScenario7FullWorkflow:
    """场景7: 完整工作流"""
    def test_full_workflow(self, scope, vars):
        # 1. 读设备信息
        scope.set_device_info("STM32G474", 170000000, 0x12345678, "2.0.0")
        # 2. 读当前参数
        kp = vars["g_pi_kp"]; ki = vars["g_pi_ki"]; id_v = vars["g_id"]
        scope.set_mem(kp.address-scope.base, struct.pack("<f", 0.5))
        scope.set_mem(ki.address-scope.base, struct.pack("<f", 80.0))
        assert abs(scope.read_var(kp)-0.5) < 0.01
        # 3. 调参
        scope.write_var(kp, 0.85)
        scope.write_var(ki, 120.0)
        assert abs(scope.read_var(kp)-0.85) < 0.001
        # 4. 录波阶跃响应
        scope.setup_stream(0, [id_v], 1000)
        scope.start_stream(0)
        response = [0, 3, 8, 13, 16, 15, 15.2, 15.0, 15.0]
        scope._d.mock_clear_tx()
        for val in response:
            scope.set_mem(id_v.address-scope.base, struct.pack("<f", val))
            scope._d.mock_tick()
        n = scope._d.mock_get_tx_len()
        buf = ctypes.create_string_buffer(n)
        scope._d.mock_read_tx(buf, n)
        raws = _parse_stream_floats(buf.raw[:n], 4)
        assert len(raws) == len(response)
        for i, (raw, exp) in enumerate(zip(raws, response)):
            assert abs(decode_value(raw, "float")-exp) < 0.01, f"step {i}"
        scope.stop_stream(0)
