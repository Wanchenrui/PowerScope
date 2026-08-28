"""
test_elf_parser.py — ELF 解析器测试
"""
import os, sys, struct, pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from power_scope.debug.elf_parser import ElfVariable, StructMember, decode_value, ELFParser

class TestDecodeValue:
    def test_uint8(self):
        assert decode_value(b"\xFF", "uint8_t") == 255
    def test_int8(self):
        assert decode_value(b"\xFF", "int8_t") == -1
    def test_uint16(self):
        assert decode_value(b"\x64\x00", "uint16_t") == 100
    def test_int16(self):
        assert decode_value(b"\xFF\xFF", "int16_t") == -1
    def test_uint32(self):
        assert decode_value(b"\x78\x56\x34\x12", "uint32_t") == 0x12345678
    def test_float(self):
        assert abs(decode_value(struct.pack("<f", 3.14), "float") - 3.14) < 0.001
    def test_double(self):
        assert abs(decode_value(struct.pack("<d", 3.14159265358979), "double") - 3.14159265358979) < 1e-10
    def test_unknown_returns_raw(self):
        assert decode_value(b"\x01\x02", "unknown") == b"\x01\x02"

class TestElfVariable:
    def test_simple_var(self):
        v = ElfVariable("g_counter", 0x20001000, 4, "uint32_t")
        assert v.name == "g_counter" and v.address == 0x20001000 and not v.is_struct
    def test_struct_members(self):
        members = [
            StructMember("kp", 0, 4, "float"),
            StructMember("ki", 4, 4, "float"),
            StructMember("integral", 12, 4, "float"),
        ]
        v = ElfVariable("g_pi", 0x20002000, 16, "PIController", is_struct=True, members=members)
        assert v.is_struct and len(v.members) == 3
        addr, sz, typ = v.member_address("ki")
        assert addr == 0x20002004 and typ == "float"
        addr, sz, typ = v.member_address("integral")
        assert addr == 0x2000200C
    def test_member_not_found(self):
        v = ElfVariable("g_x", 0x1000, 4, "uint32_t")
        with pytest.raises(KeyError):
            v.member_address("nope")

class TestPowerElectronics:
    @staticmethod
    def create_vars():
        return [
            ElfVariable("g_id", 0x20001000, 4, "float"),
            ElfVariable("g_iq", 0x20001004, 4, "float"),
            ElfVariable("g_vd", 0x20001008, 4, "float"),
            ElfVariable("g_vq", 0x2000100C, 4, "float"),
            ElfVariable("g_current_pi", 0x20002000, 16, "PIController", is_struct=True, members=[
                StructMember("kp", 0, 4, "float"),
                StructMember("ki", 4, 4, "float"),
                StructMember("kd", 8, 4, "float"),
                StructMember("integral", 12, 4, "float"),
            ]),
            ElfVariable("g_duty", 0x20003000, 2, "uint16_t"),
            ElfVariable("g_grid_angle", 0x20003004, 4, "float"),
            ElfVariable("g_vsg_freq", 0x20003008, 4, "float"),
        ]
    def test_addresses(self):
        vm = {v.name: v for v in self.create_vars()}
        assert vm["g_id"].address == 0x20001000
        assert vm["g_duty"].type_name == "uint16_t"
    def test_pi_members(self):
        pi = next(v for v in self.create_vars() if v.name == "g_current_pi")
        assert pi.member_address("kp")[0] == 0x20002000
        assert pi.member_address("ki")[0] == 0x20002004
        assert pi.member_address("integral")[0] == 0x2000200C
    def test_decode_values(self):
        assert abs(decode_value(struct.pack("<f", 10.5), "float") - 10.5) < 0.001
        assert decode_value(struct.pack("<H", 3500), "uint16_t") == 3500
        assert abs(decode_value(struct.pack("<f", 1.5708), "float") - 1.5708) < 0.001

class TestRealELF:
    def test_nonexistent(self):
        with pytest.raises(FileNotFoundError):
            ELFParser("nonexistent.elf")
