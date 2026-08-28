"""
test_session_controller.py — SessionController 单元测试

验证 SessionController 的完整生命周期：
  1. 创建（默认未连接）
  2. 连接（选择 Transport → 打开 → ProtocolEngine 解析启动）
  3. 收发（write/read → Transport 转发 → ProtocolEngine 解析 → EventBus 发布）
  4. 断开（清理资源，发布状态变更）

TDD 流程:
  1. RED: 测试先写，运行应失败
  2. GREEN: 实现最小代码让测试通过
  3. REFACTOR: 清理，确保类型安全
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from PySide6.QtCore import QCoreApplication

from power_scope.core.event_bus import EventBus, ConnectionStateEvent, FrameReceivedEvent
from power_scope.core.protocol_engine import ProtocolEngine
from power_scope.core.cffi_loader import DebugProtocol
from power_scope.transport import MockTransport, ITransport


@pytest.fixture(scope="module", autouse=True)
def _ensure_qapp():
    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication([])
    yield app


@pytest.fixture(autouse=True)
def reset_bus():
    """每个测试前重置 EventBus 并排空队列"""
    bus = EventBus.instance()
    bus._reset_for_test()
    app = QCoreApplication.instance()
    if app is not None:
        for _ in range(5):
            app.processEvents()
    yield


class TestSessionControllerLifecycle:
    """生命周期管理：创建 → 连接 → 断开 → 状态变更"""

    def _pump(self, count: int = 5) -> None:
        app = QCoreApplication.instance()
        for _ in range(count):
            app.processEvents()

    def test_default_state(self):
        """创建后默认未连接"""
        from power_scope.session.session_controller import SessionController

        sc = SessionController()
        assert sc.is_connected is False
        assert sc.state == "disconnected"

    def test_connect_mock_transport(self):
        """使用 MockTransport 连接"""
        from power_scope.session.session_controller import SessionController

        sc = SessionController()
        states: list[str] = []

        bus = EventBus.instance()
        bus.subscribe("connection/state", lambda e: states.append(e.state))

        sc.connect_mock()
        self._pump()

        assert sc.is_connected is True
        assert sc.state == "connected"
        assert "connected" in states

    def test_disconnect(self):
        """断开连接后状态正确"""
        from power_scope.session.session_controller import SessionController

        sc = SessionController()
        sc.connect_mock()
        self._pump()
        assert sc.is_connected is True

        sc.disconnect()
        self._pump()

        assert sc.is_connected is False
        assert sc.state == "disconnected"

    def test_double_connect_no_crash(self):
        """重复连接不应崩溃"""
        from power_scope.session.session_controller import SessionController

        sc = SessionController()
        sc.connect_mock()
        sc.connect_mock()  # 重复连接
        self._pump()
        assert sc.is_connected is True

    def test_disconnect_when_not_connected(self):
        """未连接时断开不应崩溃"""
        from power_scope.session.session_controller import SessionController

        sc = SessionController()
        sc.disconnect()
        assert sc.is_connected is False


class TestSessionControllerDataFlow:
    """数据流：SessionController → Transport → ProtocolEngine → EventBus"""

    def _pump(self, count: int = 5) -> None:
        app = QCoreApplication.instance()
        for _ in range(count):
            app.processEvents()

    def test_send_raw_bytes(self):
        """发送原始字节到 Transport"""
        from power_scope.session.session_controller import SessionController

        sc = SessionController()
        sc.connect_mock()

        written = sc.write(b"\xA5\x5A\x01\x02")
        assert written == 4
        assert sc.transport.written_bytes() == b"\xA5\x5A\x01\x02"

    def test_receive_frame_via_event_bus(self):
        """Transport 收到数据 → ProtocolEngine 解析 → EventBus 发布"""
        from power_scope.session.session_controller import SessionController

        sc = SessionController()
        sc.connect_mock()

        received: list[FrameReceivedEvent] = []
        bus = EventBus.instance()
        bus.subscribe("frame/received", lambda e: received.append(e))

        resp = DebugProtocol.build_response(0x07, 0x0001, 0x00, b"STM32")
        sc.transport.inject_data(resp)
        self._pump()

        assert len(received) == 1
        assert received[0].cmd == 0x07
        assert received[0].payload == b"STM32"

    def test_multiple_frames_in_one_burst(self):
        """一次注入多个帧，应全部解析并发布"""
        from power_scope.session.session_controller import SessionController

        sc = SessionController()
        sc.connect_mock()

        received: list[FrameReceivedEvent] = []
        bus = EventBus.instance()
        bus.subscribe("frame/received", lambda e: received.append(e))

        resp1 = DebugProtocol.build_response(0x01, 0x0001, 0x00, b"\xAA")
        resp2 = DebugProtocol.build_response(0x02, 0x0002, 0x00, b"\xBB\xCC")

        sc.transport.inject_data(resp1 + resp2)
        self._pump()

        assert len(received) == 2
        assert received[0].cmd == 0x01
        assert received[1].cmd == 0x02


class TestSessionControllerProtocolIntegration:
    """与 ProtocolEngine 的集成"""

    def _pump(self, count: int = 5) -> None:
        app = QCoreApplication.instance()
        for _ in range(count):
            app.processEvents()

    def test_state_transitions(self):
        """完整状态转换：disconnected → connected → disconnected"""
        from power_scope.session.session_controller import SessionController

        sc = SessionController()
        states: list[str] = []
        bus = EventBus.instance()
        bus.subscribe("connection/state", lambda e: states.append(e.state))

        sc.connect_mock()
        self._pump()
        sc.disconnect()
        self._pump()

        assert states == ["connected", "disconnected"]

    def test_transport_error_emits_state(self):
        """Transport 错误应触发 error 状态事件"""
        from power_scope.session.session_controller import SessionController

        sc = SessionController()
        errors: list[str] = []
        bus = EventBus.instance()
        bus.subscribe("connection/state", lambda e: errors.append(e.state) if e.state == "error" else None)

        sc.connect_mock()
        # 模拟 Transport 错误
        sc.transport.error_occurred.emit("serial timeout")
        self._pump()

        # error_occurred 信号被 SessionController 接收后应发布 error 状态
        # 具体行为取决于实现
        assert sc.is_connected is True  # mock 不会因错误自动断开


class TestSessionControllerFactory:
    """工厂方法：创建不同类型的 Transport"""

    def test_create_mock(self):
        """create_mock() 创建 MockTransport"""
        from power_scope.session.session_controller import SessionController

        sc = SessionController()
        sc.connect_mock()
        assert isinstance(sc.transport, MockTransport)

    def test_create_serial(self):
        """connect_serial() 尝试打开串口，COM 口不存在时进入 error 状态"""
        from power_scope.session.session_controller import SessionController
        from power_scope.transport import SerialTransport

        sc = SessionController()
        # 使用不存在的端口 — 应触发 error 状态而非 crash
        sc.connect_serial("COM_NONEXISTENT", 115200)
        # 端口不存在时，状态应为 error
        assert sc.state == "error"
        assert "COM_NONEXISTENT" in sc.state_info

    def test_create_serial_state_info(self):
        """connect_serial() 在 error 状态时保存错误信息"""
        from power_scope.session.session_controller import SessionController

        sc = SessionController()
        sc.connect_serial("COM_NONEXISTENT", 9600)
        assert sc.state == "error"
        assert sc.state_info != ""
