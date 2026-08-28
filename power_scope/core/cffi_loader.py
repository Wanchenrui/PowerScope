"""
cffi_loader.py — ctypes 加载 power_core.dll，提供 Python 友好的 C 核心库接口

使用 ctypes 标准库: 无需额外编译 Python 扩展，直接加载 DLL。
所有封装类共享同一个 ctypes 库句柄，避免 DLL 重复加载。
"""
from __future__ import annotations

import ctypes
import os
import sys
import weakref
from typing import Callable


# ========== 查找 DLL ==========

def _find_dll(dll_name: str) -> str | None:
    """在多个候选路径中查找 DLL (支持 PyInstaller 打包环境)"""
    candidates = []
    # 1. PyInstaller 单文件模式（运行时解压到临时目录）
    if hasattr(sys, "_MEIPASS"):
        candidates.append(os.path.join(sys._MEIPASS, dll_name))
    # 2. PyInstaller 目录模式 / 普通可执行文件
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        candidates.extend([
            os.path.join(exe_dir, "_internal", dll_name),
            os.path.join(exe_dir, dll_name),
        ])
    else:
        # 3. 开发模式（源码运行）
        pkg_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(os.path.dirname(pkg_dir))
        candidates.extend([
            os.path.join(project_root, dll_name),
            os.path.join(pkg_dir, dll_name),
            os.path.join(os.getcwd(), dll_name),
        ])
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


# ========== 加载 DLL ==========

_lib: ctypes.CDLL | None = None


def _load_lib() -> ctypes.CDLL:
    """加载 C 动态库，返回 ctypes 库句柄"""
    global _lib
    if _lib is not None:
        return _lib

    dll_name = "power_core.dll" if sys.platform == "win32" else "libpower_core.so"
    path = _find_dll(dll_name)
    if path is None:
        raise RuntimeError(f"无法找到 {dll_name}，请确保已编译。")

    lib = ctypes.CDLL(path)

    # --- CRC16 ---
    lib.crc16_modbus.argtypes = [ctypes.POINTER(ctypes.c_uint8), ctypes.c_uint32]
    lib.crc16_modbus.restype = ctypes.c_uint16

    lib.crc16_modbus_continue.argtypes = [ctypes.c_uint16, ctypes.POINTER(ctypes.c_uint8), ctypes.c_uint32]
    lib.crc16_modbus_continue.restype = ctypes.c_uint16

    lib.crc16_modbus_bitwise.argtypes = [ctypes.POINTER(ctypes.c_uint8), ctypes.c_uint32]
    lib.crc16_modbus_bitwise.restype = ctypes.c_uint16

    # --- RingBuffer ---
    lib.ring_buffer_create.argtypes = [ctypes.c_uint32]
    lib.ring_buffer_create.restype = ctypes.c_void_p

    lib.ring_buffer_destroy.argtypes = [ctypes.c_void_p]
    lib.ring_buffer_destroy.restype = None

    lib.ring_buffer_write.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint8), ctypes.c_uint32]
    lib.ring_buffer_write.restype = ctypes.c_uint32

    lib.ring_buffer_read.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint8), ctypes.c_uint32]
    lib.ring_buffer_read.restype = ctypes.c_uint32

    lib.ring_buffer_peek.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint8), ctypes.c_uint32]
    lib.ring_buffer_peek.restype = ctypes.c_uint32

    lib.ring_buffer_available.argtypes = [ctypes.c_void_p]
    lib.ring_buffer_available.restype = ctypes.c_uint32

    lib.ring_buffer_free_space.argtypes = [ctypes.c_void_p]
    lib.ring_buffer_free_space.restype = ctypes.c_uint32

    lib.ring_buffer_clear.argtypes = [ctypes.c_void_p]
    lib.ring_buffer_clear.restype = None

    lib.ring_buffer_capacity.argtypes = [ctypes.c_void_p]
    lib.ring_buffer_capacity.restype = ctypes.c_uint32

    # --- Modbus ---
    lib.modbus_build_read_holding.argtypes = [
        ctypes.POINTER(ctypes.c_uint8), ctypes.c_uint32,
        ctypes.c_uint8, ctypes.c_uint16, ctypes.c_uint16,
    ]
    lib.modbus_build_read_holding.restype = ctypes.c_int32

    lib.modbus_build_write_single.argtypes = [
        ctypes.POINTER(ctypes.c_uint8), ctypes.c_uint32,
        ctypes.c_uint8, ctypes.c_uint16, ctypes.c_uint16,
    ]
    lib.modbus_build_write_single.restype = ctypes.c_int32

    lib.modbus_build_write_multi.argtypes = [
        ctypes.POINTER(ctypes.c_uint8), ctypes.c_uint32,
        ctypes.c_uint8, ctypes.c_uint16,
        ctypes.POINTER(ctypes.c_uint16), ctypes.c_uint16,
    ]
    lib.modbus_build_write_multi.restype = ctypes.c_int32

    lib.modbus_build_read_holding_response.argtypes = [
        ctypes.POINTER(ctypes.c_uint8), ctypes.c_uint32,
        ctypes.c_uint8, ctypes.POINTER(ctypes.c_uint16), ctypes.c_uint16,
    ]
    lib.modbus_build_read_holding_response.restype = ctypes.c_int32

    lib.modbus_parse_rtu_response.argtypes = [
        ctypes.POINTER(ctypes.c_uint8), ctypes.c_uint32,
        ctypes.c_void_p, ctypes.c_void_p,
    ]
    lib.modbus_parse_rtu_response.restype = ctypes.c_int32

    lib.modbus_rtu_expected_len.argtypes = [ctypes.POINTER(ctypes.c_uint8), ctypes.c_uint32]
    lib.modbus_rtu_expected_len.restype = ctypes.c_uint32

    # --- Debug Protocol ---
    lib.dbg_build_frame.argtypes = [
        ctypes.POINTER(ctypes.c_uint8), ctypes.c_uint32,
        ctypes.c_uint8, ctypes.c_uint16, ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_uint8), ctypes.c_uint16,
    ]
    lib.dbg_build_frame.restype = ctypes.c_int32

    lib.dbg_parse_frame.argtypes = [
        ctypes.POINTER(ctypes.c_uint8), ctypes.c_uint32,
        ctypes.c_void_p,
    ]
    lib.dbg_parse_frame.restype = ctypes.c_int32

    lib.dbg_build_response.argtypes = [
        ctypes.POINTER(ctypes.c_uint8), ctypes.c_uint32,
        ctypes.c_uint8, ctypes.c_uint16, ctypes.c_uint8,
        ctypes.POINTER(ctypes.c_uint8), ctypes.c_uint16,
    ]
    lib.dbg_build_response.restype = ctypes.c_int32

    lib.dbg_build_stream_frame.argtypes = [
        ctypes.POINTER(ctypes.c_uint8), ctypes.c_uint32,
        ctypes.c_uint16, ctypes.c_uint32,
        ctypes.c_uint8, ctypes.c_uint8,
        ctypes.POINTER(ctypes.c_uint8), ctypes.c_uint16,
    ]
    lib.dbg_build_stream_frame.restype = ctypes.c_int32

    lib.dbg_parse_stream_frame.argtypes = [
        ctypes.POINTER(ctypes.c_uint8), ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_uint16), ctypes.POINTER(ctypes.c_uint32),
        ctypes.POINTER(ctypes.c_uint8), ctypes.POINTER(ctypes.c_uint8),
        ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_uint16),
    ]
    lib.dbg_parse_stream_frame.restype = ctypes.c_int32

    lib.dbg_expected_frame_len.argtypes = [ctypes.POINTER(ctypes.c_uint8), ctypes.c_uint32]
    lib.dbg_expected_frame_len.restype = ctypes.c_uint32

    # --- Version ---
    lib.pc_get_version.argtypes = []
    lib.pc_get_version.restype = ctypes.c_char_p

    _lib = lib
    return lib


lib = _load_lib()


# ========== 结构体定义 ==========

class _ModbusRequest(ctypes.Structure):
    _fields_ = [
        ("slave_id", ctypes.c_uint8),
        ("function_code", ctypes.c_uint8),
        ("start_addr", ctypes.c_uint16),
        ("reg_count", ctypes.c_uint16),
        ("write_value", ctypes.c_uint16),
    ]


class _ModbusResponse(ctypes.Structure):
    _fields_ = [
        ("slave_id", ctypes.c_uint8),
        ("function_code", ctypes.c_uint8),
        ("byte_count", ctypes.c_uint8),
        ("registers", ctypes.c_uint16 * 256),
        ("reg_count", ctypes.c_uint8),
        ("written_addr", ctypes.c_uint16),
        ("written_count", ctypes.c_uint16),
        ("exception_code", ctypes.c_uint8),
        ("is_exception", ctypes.c_bool),
    ]


class _DbgFrame(ctypes.Structure):
    _fields_ = [
        ("version", ctypes.c_uint8),
        ("cmd", ctypes.c_uint8),
        ("seq", ctypes.c_uint16),
        ("address", ctypes.c_uint32),
        ("length", ctypes.c_uint16),
        ("payload", ctypes.POINTER(ctypes.c_uint8)),
        ("payload_len", ctypes.c_uint16),
    ]


# ========== 辅助函数 ==========

def _to_uint8_ptr(data: bytes) -> ctypes.POINTER(ctypes.c_uint8):
    """将 bytes 转换为 ctypes uint8_t* 指针"""
    if not data:
        return None
    return (ctypes.c_uint8 * len(data)).from_buffer_copy(data)


def _buffer_to_bytes(buf, length: int) -> bytes:
    """将 ctypes 缓冲区转换为 Python bytes"""
    return bytes(ctypes.cast(buf, ctypes.POINTER(ctypes.c_uint8))[:length])


# ========== 公共接口 ==========

class CRC16:
    """CRC16-Modbus Python 封装 (ctypes 统一调用)"""

    @staticmethod
    def calc(data: bytes) -> int:
        """计算 Modbus CRC16"""
        buf = _to_uint8_ptr(data)
        return int(lib.crc16_modbus(buf, len(data) if data else 0))

    @staticmethod
    def continue_calc(crc: int, data: bytes) -> int:
        """续算 CRC16"""
        buf = _to_uint8_ptr(data)
        return int(lib.crc16_modbus_continue(crc, buf, len(data) if data else 0))

    @staticmethod
    def bitwise(data: bytes) -> int:
        """逐位计算 CRC16 (用于交叉验证)"""
        buf = _to_uint8_ptr(data)
        return int(lib.crc16_modbus_bitwise(buf, len(data) if data else 0))


class RingBuffer:
    """环形缓冲区 Python 封装 (ctypes)"""

    def __init__(self, capacity: int):
        self._rb = lib.ring_buffer_create(capacity)
        if self._rb is None:
            raise MemoryError("ring_buffer_create failed")
        weakref.finalize(self, lib.ring_buffer_destroy, self._rb)

    def write(self, data: bytes) -> int:
        buf = _to_uint8_ptr(data)
        return int(lib.ring_buffer_write(self._rb, buf, len(data)))

    def read(self, length: int) -> bytes:
        buf = (ctypes.c_uint8 * length)()
        n = lib.ring_buffer_read(self._rb, buf, length)
        return bytes(buf[:n])

    def peek(self, length: int) -> bytes:
        buf = (ctypes.c_uint8 * length)()
        n = lib.ring_buffer_peek(self._rb, buf, length)
        return bytes(buf[:n])

    @property
    def available(self) -> int:
        return int(lib.ring_buffer_available(self._rb))

    @property
    def free_space(self) -> int:
        return int(lib.ring_buffer_free_space(self._rb))

    def clear(self) -> None:
        lib.ring_buffer_clear(self._rb)

    @property
    def capacity(self) -> int:
        return int(lib.ring_buffer_capacity(self._rb))


class ModbusCodec:
    """Modbus RTU 帧编解码 Python 封装 (ctypes 统一调用)"""

    @staticmethod
    def build_read_holding(slave_id: int, start_addr: int, reg_count: int) -> bytes:
        buf = (ctypes.c_uint8 * 64)()
        n = lib.modbus_build_read_holding(buf, 64, slave_id, start_addr, reg_count)
        if n < 0:
            raise ValueError(f"build_read_holding failed: {n}")
        return bytes(buf[:n])

    @staticmethod
    def build_write_single(slave_id: int, addr: int, value: int) -> bytes:
        buf = (ctypes.c_uint8 * 64)()
        n = lib.modbus_build_write_single(buf, 64, slave_id, addr, value)
        if n < 0:
            raise ValueError(f"build_write_single failed: {n}")
        return bytes(buf[:n])

    @staticmethod
    def build_write_multi(slave_id: int, start_addr: int, regs: list[int]) -> bytes:
        buf_size = 256
        buf = (ctypes.c_uint8 * buf_size)()
        reg_arr = (ctypes.c_uint16 * len(regs))(*regs)
        n = lib.modbus_build_write_multi(buf, buf_size, slave_id, start_addr, reg_arr, len(regs))
        if n < 0:
            raise ValueError(f"build_write_multi failed: {n}")
        return bytes(buf[:n])

    @staticmethod
    def parse_response(data: bytes, slave_id: int | None = None, fc: int | None = None) -> dict:
        buf = _to_uint8_ptr(data)

        req_ptr = None
        if slave_id is not None:
            req = _ModbusRequest()
            req.slave_id = slave_id
            req.function_code = fc or 0
            req_ptr = ctypes.byref(req)

        resp = _ModbusResponse()
        rc = lib.modbus_parse_rtu_response(buf, len(data), req_ptr, ctypes.byref(resp))
        # rc=-6 (MB_ERR_EXCEPT) 表示异常响应，这是合法的协议响应，不抛异常
        if rc < 0 and rc != -6:
            raise ValueError(f"parse failed: {rc}")
        return {
            "slave_id": int(resp.slave_id),
            "function_code": int(resp.function_code),
            "is_exception": bool(resp.is_exception),
            "exception_code": int(resp.exception_code),
            "reg_count": int(resp.reg_count),
            "registers": [int(resp.registers[i]) for i in range(resp.reg_count)],
            "written_addr": int(resp.written_addr),
            "written_count": int(resp.written_count),
            "byte_count": int(resp.byte_count),
        }


class DebugProtocol:
    """调试协议引擎 Python 封装 (ctypes 统一调用)"""

    CMD_READ_MEM = 0x01
    CMD_WRITE_MEM = 0x02
    CMD_READ_BATCH = 0x03
    CMD_SET_SAMPLE = 0x04
    CMD_START_STREAM = 0x05
    CMD_STOP_STREAM = 0x06
    CMD_GET_INFO = 0x07
    CMD_STREAM_DATA = 0x10

    @staticmethod
    def build_frame(cmd: int, seq: int, address: int = 0, payload: bytes = b"") -> bytes:
        buf_size = 512 + len(payload)
        buf = (ctypes.c_uint8 * buf_size)()
        plen = len(payload)
        p_ptr = _to_uint8_ptr(payload) if plen > 0 else None
        n = lib.dbg_build_frame(buf, buf_size, cmd, seq, address, p_ptr, plen)
        if n < 0:
            raise ValueError(f"build_frame failed: {n}")
        return bytes(buf[:n])

    @staticmethod
    def build_response(cmd: int, seq: int, status: int = 0, payload: bytes = b"") -> bytes:
        """构建 MCU 响应帧"""
        buf_size = 512 + len(payload)
        buf = (ctypes.c_uint8 * buf_size)()
        plen = len(payload)
        p_ptr = _to_uint8_ptr(payload) if plen > 0 else None
        n = lib.dbg_build_response(buf, buf_size, cmd, seq, status, p_ptr, plen)
        if n < 0:
            raise ValueError(f"build_response failed: {n}")
        return bytes(buf[:n])

    @staticmethod
    def parse_frame(data: bytes) -> dict:
        buf = _to_uint8_ptr(data)
        frame = _DbgFrame()
        rc = lib.dbg_parse_frame(buf, len(data), ctypes.byref(frame))
        if rc != 0:
            raise ValueError(f"parse_frame failed: {rc}")
        payload = bytes(frame.payload[:frame.payload_len]) if frame.payload_len > 0 else b""
        return {
            "version": int(frame.version),
            "cmd": int(frame.cmd),
            "seq": int(frame.seq),
            "address": int(frame.address),
            "payload": payload,
        }

    @staticmethod
    def parse_response(data: bytes) -> dict:
        """解析 MCU 响应帧 (9字节头: SOF+VER+CMD+SEQ+STATUS+LEN)"""
        if len(data) < 11:  # 9(hdr) + 0(payload) + 2(crc) 最小
            raise ValueError(f"response too short: {len(data)}")
        if data[0] != 0xA5 or data[1] != 0x5A:
            raise ValueError("bad SOF")
        cmd = data[3]
        seq = data[4] | (data[5] << 8)
        status = data[6]
        plen = data[7] | (data[8] << 8)
        expected_total = 9 + plen + 2
        if len(data) < expected_total:
            raise ValueError(f"response truncated: {len(data)} < {expected_total}")
        # CRC 校验
        crc_calc = CRC16.calc(data[:9 + plen])
        crc_recv = data[9 + plen] | (data[10 + plen] << 8)
        if crc_calc != crc_recv:
            raise ValueError(f"response CRC error: calc={crc_calc:04X} recv={crc_recv:04X}")
        payload = data[9:9 + plen] if plen > 0 else b""
        return {
            "version": data[2],
            "cmd": cmd,
            "seq": seq,
            "status": status,
            "payload": payload,
        }

    @staticmethod
    def build_stream_frame(seq: int, timestamp: int, list_id: int,
                           sample_count: int, data: bytes) -> bytes:
        buf_size = 512 + len(data)
        buf = (ctypes.c_uint8 * buf_size)()
        dlen = len(data)
        d_ptr = _to_uint8_ptr(data) if dlen > 0 else None
        n = lib.dbg_build_stream_frame(buf, buf_size, seq, timestamp, list_id, sample_count, d_ptr, dlen)
        if n < 0:
            raise ValueError(f"build_stream_frame failed: {n}")
        return bytes(buf[:n])

    @staticmethod
    def expected_frame_len(data: bytes) -> int:
        if len(data) < 12:
            return 0
        buf = _to_uint8_ptr(data)
        return int(lib.dbg_expected_frame_len(buf, len(data)))

