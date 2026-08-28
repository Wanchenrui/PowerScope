"""session_controller.py — 会话控制器

整合 Transport + ProtocolEngine + EventBus，提供统一的连接/断开/收发接口。

状态机:
    disconnected → connecting → connected ←→ error
                      ↑________↓

使用方式:
    sc = SessionController()
    sc.connect_mock()                    # 模拟模式
    sc.write(DebugProtocol.build_frame(...))
    sc.disconnect()
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from ..core.event_bus import EventBus, ConnectionStateEvent
from ..core.protocol_engine import ProtocolEngine
from ..transport import ITransport, MockTransport, SerialTransport


class SessionController(QObject):
    """会话控制器 — 连接状态管理与数据流转

    信号:
        data_sent(bytes):      原始发送数据（供 UI 显示）
        data_received(bytes):  原始接收数据（供 UI 显示）
    """
    data_sent = Signal(bytes)
    data_received = Signal(bytes)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._transport: ITransport | None = None
        self._protocol_engine = ProtocolEngine()
        self._state: str = "disconnected"
        self._state_info: str = ""

    # ------------------------------------------------------------------
    # 属性
    # ------------------------------------------------------------------

    @property
    def is_connected(self) -> bool:
        return self._state == "connected"

    @property
    def state(self) -> str:
        return self._state

    @property
    def state_info(self) -> str:
        """最近一次状态变更的附加信息"""
        return self._state_info

    @property
    def transport(self) -> ITransport:
        """当前 Transport 实例（测试专用）"""
        if self._transport is None:
            raise RuntimeError("No transport assigned")
        return self._transport

    # ------------------------------------------------------------------
    # 连接管理
    # ------------------------------------------------------------------

    def connect_mock(self) -> None:
        """连接模拟 Transport"""
        self._disconnect_current()
        self._transport = MockTransport(self)
        self._connect_signals()
        self._transport.open()
        self._set_state("connected")

    def connect_serial(
        self,
        port: str,
        baudrate: int = 115200,
        bytesize: int = 8,
        parity: str = "N",
        stopbits: float = 1,
    ) -> None:
        """连接串口 Transport — 尝试打开串口，失败时发布 error 事件

        状态流转: disconnected → connecting → connected (成功) / error (失败)
        """
        self._disconnect_current()
        self._set_state("connecting")

        self._transport = SerialTransport(
            port=port,
            baudrate=baudrate,
            bytesize=bytesize,
            parity=parity,
            stopbits=stopbits,
            parent=self,
        )
        self._connect_signals()

        try:
            self._transport.open()
            self._set_state("connected", info=f"{port} @ {baudrate}")
        except Exception as e:
            self._set_state("error", info=f"无法打开 {port}: {e}")

    def disconnect(self) -> None:
        """断开当前连接"""
        self._disconnect_current()
        self._set_state("disconnected")

    # ------------------------------------------------------------------
    # 数据收发
    # ------------------------------------------------------------------

    def write(self, data: bytes) -> int:
        """发送数据"""
        if self._transport is None:
            raise RuntimeError("Transport not connected")
        written = self._transport.write(data)
        self.data_sent.emit(data)
        return written

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _connect_signals(self) -> None:
        """连接 Transport 信号到 ProtocolEngine"""
        if self._transport is None:
            return
        self._transport.ready_read.connect(self._on_ready_read)
        self._transport.error_occurred.connect(self._on_transport_error)

    def _disconnect_current(self) -> None:
        """断开并清理当前 Transport"""
        if self._transport is not None:
            try:
                self._transport.ready_read.disconnect(self._on_ready_read)
            except Exception:
                pass
            try:
                self._transport.error_occurred.disconnect(self._on_transport_error)
            except Exception:
                pass
            self._transport.close()
            self._transport = None

    def _on_ready_read(self, data: bytes) -> None:
        """Transport 收到数据 → emit data_received + ProtocolEngine 解析"""
        self.data_received.emit(data)
        self._protocol_engine.feed(data)

    def _on_transport_error(self, msg: str) -> None:
        """Transport 错误 → 发布 error 状态（但不断开连接）"""
        EventBus.instance().publish(
            "connection/state",
            ConnectionStateEvent(state="error", transport_type=self._transport_type(), info=msg),
        )

    def _set_state(self, state: str, info: str = "") -> None:
        """更新状态并发布事件"""
        self._state = state
        self._state_info = info
        EventBus.instance().publish(
            "connection/state",
            ConnectionStateEvent(state=state, transport_type=self._transport_type(), info=info),
        )

    def _transport_type(self) -> str:
        if isinstance(self._transport, MockTransport):
            return "mock"
        if isinstance(self._transport, SerialTransport):
            return "serial"
        return "unknown"
