"""
test_modbus_full.py — Modbus 全功能码与协议合规性测试
"""
import os, sys, struct, pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from power_scope.core.cffi_loader import CRC16, ModbusCodec

FC_READ_HOLDING = 0x03
FC_READ_INPUT = 0x04
FC_WRITE_SINGLE_REG = 0x06
FC_WRITE_MULTI_REG = 0x10
EXC_ILLEGAL_FUNC = 0x01
EXC_ILLEGAL_ADDR = 0x02
EXC_ILLEGAL_VALUE = 0x03
EXC_SLAVE_FAILURE = 0x04


class TestReadFunctionCodes:
    def test_fc03_read_holding(self):
        frame = ModbusCodec.build_read_holding(1, 100, 4)
        assert frame[1] == FC_READ_HOLDING
        assert struct.unpack(">H", frame[2:4])[0] == 100
        assert struct.unpack(">H", frame[4:6])[0] == 4

    def test_fc04_read_input_response(self):
        regs = [0x1111, 0x2222]
        payload = struct.pack(">BBB", 1, FC_READ_INPUT, 4)
        for r in regs: payload += struct.pack(">H", r)
        crc = CRC16.calc(payload)
        result = ModbusCodec.parse_response(payload + struct.pack("<H", crc))
        assert result["function_code"] == FC_READ_INPUT
        assert result["registers"] == regs

    def test_fc03_response_byte_count(self):
        for count in [1, 2, 10, 50, 125]:
            regs = [0xAAAA] * count
            payload = struct.pack(">BBB", 1, FC_READ_HOLDING, count * 2)
            for r in regs: payload += struct.pack(">H", r)
            crc = CRC16.calc(payload)
            result = ModbusCodec.parse_response(payload + struct.pack("<H", crc))
            assert result["byte_count"] == count * 2
            assert len(result["registers"]) == count


class TestWriteFunctionCodes:
    def test_fc06_write_single(self):
        frame = ModbusCodec.build_write_single(1, 0x1000, 0x012C)
        assert frame[1] == FC_WRITE_SINGLE_REG
        assert struct.unpack(">H", frame[2:4])[0] == 0x1000
        assert struct.unpack(">H", frame[4:6])[0] == 0x012C

    def test_fc06_response_echo(self):
        req = ModbusCodec.build_write_single(1, 0x2000, 0xABCD)
        result = ModbusCodec.parse_response(req)
        assert result["written_addr"] == 0x2000
        assert result["written_count"] == 0xABCD

    def test_fc10_write_multi(self):
        regs = [0x0001, 0x0002, 0x0003]
        frame = ModbusCodec.build_write_multi(1, 0x0100, regs)
        assert frame[1] == FC_WRITE_MULTI_REG
        assert struct.unpack(">H", frame[2:4])[0] == 0x0100
        assert struct.unpack(">H", frame[4:6])[0] == 3
        assert frame[6] == 6

    def test_fc10_response(self):
        payload = struct.pack(">BBHH", 1, FC_WRITE_MULTI_REG, 0x0100, 3)
        crc = CRC16.calc(payload)
        result = ModbusCodec.parse_response(payload + struct.pack("<H", crc))
        assert result["written_addr"] == 0x0100
        assert result["written_count"] == 3


class TestExceptionResponses:
    @pytest.mark.parametrize("exc_code", [EXC_ILLEGAL_FUNC, EXC_ILLEGAL_ADDR, EXC_ILLEGAL_VALUE, EXC_SLAVE_FAILURE])
    def test_exception_codes(self, exc_code):
        payload = struct.pack(">BBB", 1, 0x83, exc_code)
        crc = CRC16.calc(payload)
        result = ModbusCodec.parse_response(payload + struct.pack("<H", crc))
        assert result["is_exception"]
        assert result["exception_code"] == exc_code

    def test_exception_fc_high_bit(self):
        for fc in [0x01, 0x03, 0x06, 0x10]:
            payload = struct.pack(">BBB", 1, fc | 0x80, EXC_ILLEGAL_ADDR)
            crc = CRC16.calc(payload)
            result = ModbusCodec.parse_response(payload + struct.pack("<H", crc))
            assert result["is_exception"]
            assert result["function_code"] == (fc | 0x80)


class TestMultiSlave:
    def test_different_slave_ids(self):
        for slave in [1, 10, 50, 100, 200, 247]:
            frame = ModbusCodec.build_read_holding(slave, 0, 1)
            assert frame[0] == slave

    def test_slave_mismatch_rejected(self):
        regs = [0x1234, 0x5678]
        payload = struct.pack(">BBB", 2, FC_READ_HOLDING, 4)
        for r in regs: payload += struct.pack(">H", r)
        crc = CRC16.calc(payload)
        resp = payload + struct.pack("<H", crc)
        with pytest.raises(ValueError):
            ModbusCodec.parse_response(resp, slave_id=1, fc=FC_READ_HOLDING)


class TestExpectedFrameLength:
    def test_read_response_length(self):
        payload = struct.pack(">BBB", 1, FC_READ_HOLDING, 4)
        payload += struct.pack(">HH", 0x1111, 0x2222)
        crc = CRC16.calc(payload)
        assert len(payload + struct.pack("<H", crc)) == 9

    def test_write_single_length(self):
        assert len(ModbusCodec.build_write_single(1, 0, 0)) == 8

    def test_exception_length(self):
        payload = struct.pack(">BBB", 1, 0x83, 0x02)
        crc = CRC16.calc(payload)
        assert len(payload + struct.pack("<H", crc)) == 5


class TestModbusCRCRobustness:
    def test_single_bit_flip_detected(self):
        frame = bytearray(ModbusCodec.build_read_holding(1, 0, 1))
        for bit in range(8 * len(frame)):
            flipped = bytearray(frame)
            flipped[bit // 8] ^= (1 << (bit % 8))
            with pytest.raises(ValueError):
                ModbusCodec.parse_response(bytes(flipped))

    def test_double_bit_flip_in_data(self):
        frame = bytearray(ModbusCodec.build_read_holding(1, 0, 1))
        frame[2] ^= 0x01
        frame[3] ^= 0x02
        with pytest.raises(ValueError):
            ModbusCodec.parse_response(bytes(frame))


class TestPowerElectronicsModbus:
    def test_read_inverter_power(self):
        """读取逆变器功率 (32位有符号, -1250W=发电)"""
        power = -1250
        payload = struct.pack(">BBB", 1, FC_READ_HOLDING, 4)
        payload += struct.pack(">i", power)
        crc = CRC16.calc(payload)
        result = ModbusCodec.parse_response(payload + struct.pack("<H", crc))
        raw = struct.pack(">HH", result["registers"][0], result["registers"][1])
        assert struct.unpack(">i", raw)[0] == -1250

    def test_write_pi_parameter(self):
        """写 PI 参数 (地址40153, 值5000=50.00)"""
        frame = ModbusCodec.build_write_single(1, 152, 5000)
        assert struct.unpack(">H", frame[4:6])[0] == 5000

    def test_read_multiple_params_batch(self):
        """批量读多个参数 (电压+电流+功率+温度)"""
        values = [2200, 150, 33000, 4500]  # 220.0V, 1.50A, 330.0W, 45.0C
        payload = struct.pack(">BBB", 1, FC_READ_HOLDING, 8)
        for v in values: payload += struct.pack(">H", v)
        crc = CRC16.calc(payload)
        result = ModbusCodec.parse_response(payload + struct.pack("<H", crc))
        assert result["registers"] == values
        # 语义转换: 寄存器值 / 10 = 物理量
        assert result["registers"][0] / 10.0 == 220.0
        assert result["registers"][3] / 100.0 == 45.0

    def test_modbus_poll_simulation(self):
        """模拟 Modbus Poll 轮询 10 次"""
        for i in range(10):
            frame = ModbusCodec.build_read_holding(1, i * 10, 10)
            assert len(frame) == 8
            assert frame[0] == 1
