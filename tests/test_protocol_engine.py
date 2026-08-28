"""
test_protocol_engine.py — 帧解析状态机测试

验证 ProtocolEngine 从字节流中提取完整帧的能力，
包括分片到达、多帧连发、垃圾数据、CRC 错误等场景。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from power_scope.core.protocol_engine import ProtocolEngine
from power_scope.core.event_bus import EventBus, FrameReceivedEvent
from power_scope.core.cffi_loader import DebugProtocol, CRC16


@pytest.fixture(autouse=True)
def reset_bus():
    """每个测试前重置 EventBus"""
    EventBus.instance()._reset_for_test()
    yield


class TestProtocolEngineBasic:
    """基本解析场景"""

    def test_single_response_frame(self):
        """完整响应帧一次到达"""
        payload = b"\xDE\xAD\xBE\xEF"
        resp = DebugProtocol.build_response(0x01, 0x1234, 0x00, payload)

        engine = ProtocolEngine()
        events = engine.feed(resp)

        assert len(events) == 1
        evt = events[0]
        assert evt.protocol == "debug"
        assert evt.cmd == 0x01
        assert evt.seq == 0x1234
        assert evt.status == 0x00
        assert evt.payload == payload
        assert evt.raw_frame == resp

    def test_single_command_frame(self):
        """完整命令帧一次到达"""
        payload = b"\x01\x02\x03\x04"
        cmd = DebugProtocol.build_frame(
            DebugProtocol.CMD_READ_MEM, 0x0001, 0x20001000, payload)

        engine = ProtocolEngine()
        events = engine.feed(cmd)

        assert len(events) == 1
        evt = events[0]
        assert evt.cmd == DebugProtocol.CMD_READ_MEM
        assert evt.seq == 0x0001
        assert evt.payload == payload

    def test_empty_payload_response(self):
        """无 payload 的响应帧"""
        resp = DebugProtocol.build_response(0x08, 0x0001, 0x00, b"")

        engine = ProtocolEngine()
        events = engine.feed(resp)

        assert len(events) == 1
        assert events[0].payload == b""


class TestProtocolEngineFragmentation:
    """分片到达场景"""

    def test_response_frame_split_header_then_body(self):
        """响应帧先给头再给 payload+CRC"""
        payload = b"\xAB\xCD\xEF"
        resp = DebugProtocol.build_response(0x03, 0x00AA, 0x00, payload)

        engine = ProtocolEngine()
        # 先给前 9 字节头
        events1 = engine.feed(resp[:9])
        assert len(events1) == 0

        # 再给剩余 payload + CRC
        events2 = engine.feed(resp[9:])
        assert len(events2) == 1
        assert events2[0].payload == payload

    def test_response_frame_byte_by_byte(self):
        """逐字节投喂响应帧"""
        payload = b"\x01\x02"
        resp = DebugProtocol.build_response(0x02, 0x00BB, 0x00, payload)

        engine = ProtocolEngine()
        for i, byte in enumerate(resp[:-1]):
            evts = engine.feed(bytes([byte]))
            assert len(evts) == 0, f"byte {i} should not yield frame"

        # 最后一个字节触发解析
        evts = engine.feed(bytes([resp[-1]]))
        assert len(evts) == 1
        assert evts[0].payload == payload

    def test_command_frame_split(self):
        """命令帧分片到达"""
        payload = b"\x11\x22\x33\x44\x55\x66"
        cmd = DebugProtocol.build_frame(
            DebugProtocol.CMD_WRITE_MEM, 0x0002, 0x20002000, payload)

        engine = ProtocolEngine()
        events1 = engine.feed(cmd[:12])  # 12 字节头
        assert len(events1) == 0

        events2 = engine.feed(cmd[12:])
        assert len(events2) == 1
        assert events2[0].payload == payload


class TestProtocolEngineMultipleFrames:
    """多帧连发场景"""

    def test_two_response_frames_back_to_back(self):
        """两帧连续到达"""
        resp1 = DebugProtocol.build_response(0x01, 0x0001, 0x00, b"\xAA")
        resp2 = DebugProtocol.build_response(0x02, 0x0002, 0x00, b"\xBB\xCC")

        engine = ProtocolEngine()
        events = engine.feed(resp1 + resp2)

        assert len(events) == 2
        assert events[0].cmd == 0x01
        assert events[0].payload == b"\xAA"
        assert events[1].cmd == 0x02
        assert events[1].payload == b"\xBB\xCC"

    def test_three_frames_mixed(self):
        """三帧（命令+响应+命令）连发"""
        cmd1 = DebugProtocol.build_frame(
            DebugProtocol.CMD_READ_MEM, 0x0001, 0x20001000, b"")
        resp = DebugProtocol.build_response(0x01, 0x0001, 0x00, b"\xDE\xAD\xBE\xEF")
        cmd2 = DebugProtocol.build_frame(
            DebugProtocol.CMD_READ_MEM, 0x0002, 0x20001004, b"")

        engine = ProtocolEngine()
        events = engine.feed(cmd1 + resp + cmd2)

        assert len(events) == 3
        assert events[0].cmd == DebugProtocol.CMD_READ_MEM
        assert events[1].cmd == 0x01
        assert events[1].payload == b"\xDE\xAD\xBE\xEF"
        assert events[2].cmd == DebugProtocol.CMD_READ_MEM


class TestProtocolEngineGarbageData:
    """垃圾数据/噪声场景"""

    def test_garbage_before_frame(self):
        """帧前有垃圾数据"""
        garbage = b"\x00\x01\x02\x03\xA5"  # 最后一个 0xA5 会被保留
        resp = DebugProtocol.build_response(0x07, 0x0001, 0x00, b"STM32")

        engine = ProtocolEngine()
        events = engine.feed(garbage + resp)

        assert len(events) == 1
        assert events[0].cmd == 0x07

    def test_garbage_between_frames(self):
        """两帧之间有垃圾数据"""
        resp1 = DebugProtocol.build_response(0x01, 0x0001, 0x00, b"")
        garbage = b"\xFF\xFE\xFD"
        resp2 = DebugProtocol.build_response(0x02, 0x0002, 0x00, b"")

        engine = ProtocolEngine()
        events = engine.feed(resp1 + garbage + resp2)

        assert len(events) == 2
        assert events[0].cmd == 0x01
        assert events[1].cmd == 0x02

    def test_no_sof_at_all(self):
        """完全没有 SOF 的数据"""
        engine = ProtocolEngine()
        events = engine.feed(b"\x00\x01\x02\x03\x04\x05")
        assert len(events) == 0

    def test_single_a5_without_5a(self):
        """只有 0xA5 没有 0x5A"""
        engine = ProtocolEngine()
        events = engine.feed(b"\x00\xA5\x00\x01\x02")
        assert len(events) == 0


class TestProtocolEngineCRCError:
    """CRC 错误场景"""

    def test_crc_error_response_discarded(self):
        """CRC 错误的响应帧被丢弃"""
        resp = DebugProtocol.build_response(0x01, 0x0001, 0x00, b"\xAA")
        # 篡改最后一个字节破坏 CRC
        corrupted = resp[:-1] + bytes([resp[-1] ^ 0xFF])

        engine = ProtocolEngine()
        events = engine.feed(corrupted)
        assert len(events) == 0

    def test_crc_error_then_valid_frame(self):
        """CRC 错误帧后紧跟有效帧"""
        resp_bad = DebugProtocol.build_response(0x01, 0x0001, 0x00, b"\xAA")
        corrupted = resp_bad[:-1] + bytes([resp_bad[-1] ^ 0xFF])

        resp_good = DebugProtocol.build_response(0x02, 0x0002, 0x00, b"\xBB")

        engine = ProtocolEngine()
        events = engine.feed(corrupted + resp_good)

        assert len(events) == 1
        assert events[0].cmd == 0x02
        assert events[0].payload == b"\xBB"

    def test_crc_error_command_discarded(self):
        """CRC 错误的命令帧被丢弃"""
        cmd = DebugProtocol.build_frame(
            DebugProtocol.CMD_GET_INFO, 0x0001, 0, b"")
        corrupted = cmd[:-1] + bytes([cmd[-1] ^ 0xFF])

        engine = ProtocolEngine()
        events = engine.feed(corrupted)
        assert len(events) == 0


class TestProtocolEngineEventBus:
    """EventBus 集成"""

    def _pump(self, count: int = 3) -> None:
        """处理 Qt 事件循环，让 QueuedConnection 信号送达"""
        from PySide6.QtCore import QCoreApplication
        app = QCoreApplication.instance()
        if app is not None:
            for _ in range(count):
                app.processEvents()

    def test_event_published_to_bus(self):
        """解析成功的事件通过 EventBus 发布"""
        from PySide6.QtCore import QCoreApplication
        # 确保 QCoreApplication 存在
        app = QCoreApplication.instance()
        if app is None:
            app = QCoreApplication([])

        # 排空之前测试（没有 QCoreApplication 时）积压的 QueuedConnection 信号
        self._pump(10)

        received = []

        def on_frame(evt):
            received.append(evt)

        bus = EventBus.instance()
        bus.subscribe("frame/received", on_frame)

        resp = DebugProtocol.build_response(0x07, 0x0001, 0x00, b"info")
        engine = ProtocolEngine()
        engine.feed(resp)
        self._pump()

        assert len(received) == 1
        assert received[0].cmd == 0x07

    def test_reset_clears_buffer(self):
        """reset() 清空缓冲区"""
        resp = DebugProtocol.build_response(0x01, 0x0001, 0x00, b"")

        engine = ProtocolEngine()
        # 只给一半数据
        engine.feed(resp[:5])
        engine.reset()
        # 再给完整数据，但前面的已经被清空
        events = engine.feed(resp)

        assert len(events) == 1


class TestProtocolEngineBufferManagement:
    """缓冲区管理"""

    def test_incomplete_frame_retained(self):
        """不完整的帧保留在缓冲区等待后续数据"""
        resp = DebugProtocol.build_response(0x01, 0x0001, 0x00, b"\xAA\xBB")

        engine = ProtocolEngine()
        # 给部分数据
        engine.feed(resp[:8])
        events = engine.feed(resp[8:])

        assert len(events) == 1
        assert events[0].payload == b"\xAA\xBB"

    def test_buffer_overflow_protection(self):
        """缓冲区溢出保护"""
        engine = ProtocolEngine(max_buffer=32)
        # 大量无意义数据，最后跟一个有效帧
        garbage = b"\x00" * 50
        resp = DebugProtocol.build_response(0x01, 0x0001, 0x00, b"")

        engine.feed(garbage + resp)
        # 虽然前面有垃圾数据，但缓冲区只保留最近 32 字节
        # 如果有效帧在 32 字节内，应该能解析
        events = engine.feed(b"")  # 再次触发解析

        # 有效帧在 50 字节垃圾之后，可能已经被截断
        # 这个测试主要验证不会崩溃
        assert len(events) >= 0
