"""
test_transport.py — Transport 层单元测试

验证 ITransport 抽象接口的两个实现：
  - MockTransport: 内存模拟，用于测试
  - SerialTransport: 真实串口封装（需 pyserial）

TDD 流程:
  1. RED: 测试先写，运行应失败
  2. GREEN: 实现最小代码让测试通过
  3. REFACTOR: 清理，确保接口一致
"""
from __future__ import annotations

import os
import sys
import time
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QCoreApplication, QObject, Signal

from power_scope.transport import ITransport, MockTransport, SerialTransport


# 确保 QCoreApplication 存在
@pytest.fixture(scope="module", autouse=True)
def _ensure_qapp():
    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication([])
    yield app


class TestMockTransport:
    """MockTransport 单元测试 — 纯内存模拟，无需硬件"""

    def _pump(self, count: int = 3) -> None:
        """处理 Qt 事件循环"""
        app = QCoreApplication.instance()
        for _ in range(count):
            app.processEvents()

    def test_create_not_open(self):
        """创建后默认未连接"""
        t = MockTransport()
        assert t.is_open is False
        assert t.port == "mock"

    def test_open_and_close(self):
        """打开后连接，关闭后断开"""
        t = MockTransport()
        t.open()
        assert t.is_open is True
        t.close()
        assert t.is_open is False

    def test_write_when_closed_raises(self):
        """未打开时写入应抛异常"""
        t = MockTransport()
        with pytest.raises(RuntimeError, match="not open"):
            t.write(b"\xA5\x5A")

    def test_read_callback(self):
        """注入数据后，ready_read 信号应触发回调"""
        t = MockTransport()
        received: list[bytes] = []

        def on_data(data: bytes):
            received.append(data)

        t.ready_read.connect(on_data)
        t.open()
        t.inject_data(b"\x01\x02\x03")
        self._pump()

        assert len(received) == 1
        assert received[0] == b"\x01\x02\x03"

    def test_write_bytes(self):
        """写入的数据应被记录"""
        t = MockTransport()
        t.open()
        written = t.write(b"\xA5\x5A\x01\x02")
        assert written == 4
        assert t.written_bytes() == b"\xA5\x5A\x01\x02"

    def test_inject_multiple_packets(self):
        """多次注入数据，每次独立触发 ready_read"""
        t = MockTransport()
        received: list[bytes] = []
        t.ready_read.connect(lambda d: received.append(d))
        t.open()

        t.inject_data(b"aaa")
        t.inject_data(b"bbb")
        self._pump()

        assert len(received) == 2
        assert received[0] == b"aaa"
        assert received[1] == b"bbb"

    def test_close_no_crash(self):
        """重复关闭不应崩溃"""
        t = MockTransport()
        t.close()
        t.close()
        assert t.is_open is False

    def test_state_changed_signal(self):
        """连接状态变更应触发 state_changed 信号"""
        t = MockTransport()
        states: list[bool] = []
        t.state_changed.connect(lambda s: states.append(s))

        t.open()
        self._pump()
        assert states[-1] is True

        t.close()
        self._pump()
        assert states[-1] is False


class TestSerialTransportBasic:
    """SerialTransport 基础测试 — 不依赖真实串口硬件"""

    def test_creation_without_open(self):
        """仅创建对象不应打开串口"""
        t = SerialTransport(port="COM99", baudrate=115200)
        assert t.is_open is False
        assert t.port == "COM99"
        assert t.baudrate == 115200

    def test_default_params(self):
        """默认参数验证"""
        t = SerialTransport(port="COM1")
        assert t.baudrate == 115200
        assert t.bytesize == 8
        assert t.parity == "N"
        assert t.stopbits == 1

    def test_custom_params(self):
        """自定义参数"""
        t = SerialTransport(
            port="COM3", baudrate=921600,
            bytesize=7, parity="E", stopbits=2
        )
        assert t.baudrate == 921600
        assert t.bytesize == 7
        assert t.parity == "E"
        assert t.stopbits == 2

    def test_open_bad_port_raises(self):
        """打开不存在的串口应抛异常"""
        t = SerialTransport(port="COM_NOT_EXIST")
        with pytest.raises(Exception):
            t.open()


class TestTransportInterface:
    """验证两个实现都满足 ITransport 接口契约"""

    def test_mock_is_transport(self):
        assert isinstance(MockTransport(), ITransport)

    def test_serial_is_transport(self):
        assert isinstance(SerialTransport("COM1"), ITransport)

    def test_interface_methods_exist(self):
        """所有实现都有必需的接口方法"""
        for cls in (MockTransport, SerialTransport):
            t = cls() if cls is MockTransport else cls("COM1")
            assert hasattr(t, "open")
            assert hasattr(t, "close")
            assert hasattr(t, "write")
            assert hasattr(t, "is_open")
            assert hasattr(t, "ready_read")
            assert hasattr(t, "state_changed")
            assert hasattr(t, "error_occurred")


class TestMockTransportIntegration:
    """MockTransport 与 ProtocolEngine 集成"""

    def _pump(self, count: int = 5) -> None:
        app = QCoreApplication.instance()
        for _ in range(count):
            app.processEvents()

    def test_feeds_protocol_engine(self):
        """MockTransport 接收的数据可喂给 ProtocolEngine 解析"""
        from power_scope.core.protocol_engine import ProtocolEngine
        from power_scope.core.cffi_loader import DebugProtocol

        t = MockTransport()
        engine = ProtocolEngine()
        events: list = []
        t.ready_read.connect(engine.feed)
        # engine.feed 返回 list[FrameReceivedEvent]，我们需要连接到一个槽
        # 但由于 ready_read 发射的是 bytes，而 engine.feed 接收 bytes 返回 list，
        # 这里需要一个小适配 lambda
        t.ready_read.connect(lambda d: events.extend(engine.feed(d)))

        t.open()
        resp = DebugProtocol.build_response(0x07, 0x0001, 0x00, b"info")
        t.inject_data(resp)
        self._pump()

        assert len(events) == 1
        assert events[0].cmd == 0x07
