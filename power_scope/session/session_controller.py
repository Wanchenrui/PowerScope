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

from dataclasses import replace
from PySide6.QtCore import QObject, Signal
from ..core.contracts import DeviceIdentity, Capabilities

from ..core.event_bus import EventBus, ConnectionStateEvent
from ..core.protocol_engine import ProtocolEngine
from ..transport import ITransport, MockTransport, SerialTransport


class SessionController(QObject):
    """会话控制器 — 连接状态管理与数据流转

    信号:
        data_sent(bytes):      原始发送数据（供 UI 显示）
        data_received(bytes):  原始接收数据（供 UI 显示）
    """
    epoch_changed = Signal(int, str)
    identity_changed = Signal(object)
    data_sent = Signal(bytes)
    data_received = Signal(bytes)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._transport: ITransport | None = None
        self._protocol_engine = ProtocolEngine()
        self._state: str = "disconnected"
        self._state_info: str = ""
        self.epoch = 0
        self.identity = DeviceIdentity()
        self.capabilities = Capabilities()
        self.ready = False
        self._exclusive = None
        self._debug_service = None
        self._requests = set()

    def bind_debug(self, service):
        if self._debug_service is not None and self._debug_service is not service:
            raise RuntimeError("Session already owns a DebugService")
        self._debug_service = service

    def invalidate(self, reason: str):
        self.epoch += 1
        self.ready = False
        self.identity = DeviceIdentity()
        self.capabilities = Capabilities()
        self._protocol_engine.reset()
        self._requests.clear()
        self.epoch_changed.emit(self.epoch, reason)
        self.identity_changed.emit(self.identity)

    def set_artifact_verification(self, epoch, build_id, manifest_sha256, verified):
        if epoch != self.epoch or build_id != self.identity.build_id:
            raise ValueError("Stale epoch or mismatched build ID")
        if not isinstance(build_id, bytes) or len(build_id) != 32 or not any(build_id):
            raise ValueError("Invalid build ID")
        if not verified:
            self.invalidate("artifact verification revoked")
            return
        if not isinstance(manifest_sha256, str) or len(manifest_sha256) != 64:
            raise ValueError("Invalid manifest hash")
        bytes.fromhex(manifest_sha256)
        self.identity = replace(self.identity, manifest_sha256=manifest_sha256,
                                artifacts_verified=True)
        self.identity_changed.emit(self.identity)

    def negotiate(self):
        if self._debug_service is None or not self.is_connected:
            return
        epoch = self.epoch
        def complete(resp):
            if epoch != self.epoch or resp.get("status") != 0:
                return
            info = self._debug_service.parse_device_info(resp["payload"])
            if not info:
                return
            identity = info["identity"]
            if self.identity.build_id and self.identity.build_id != identity.build_id:
                self.invalidate("device identity changed")
                return
            self.identity = identity
            self.capabilities = info["capabilities"]
            self.ready = True
            self.identity_changed.emit(identity)
        self._debug_service.get_info(complete)

    def begin_request(self, kind, key):
        if self._exclusive is not None:
            raise RuntimeError("Session is exclusively owned")
        if any(owner != kind for owner, _ in self._requests):
            raise RuntimeError("Another protocol transaction is pending")
        self._requests.add((kind, key))

    def end_request(self, kind, key):
        self._requests.discard((kind, key))

    def device_restarted(self):
        self.invalidate("device restarted")
        self.negotiate()

    def acquire_exclusive(self, kind):
        if kind not in ("raw", "upgrade") or self._exclusive is not None:
            raise RuntimeError("Exclusive session unavailable")
        token = object()
        self._exclusive = token
        self.invalidate(kind + " started")
        return token

    def release_exclusive(self, token):
        if token is not self._exclusive or token is None:
            raise RuntimeError("Invalid exclusive token")
        self._exclusive = None
        self.invalidate("exclusive session finished")
        self.negotiate()

    def write_service(self, kind, data, token=None):
        if self._exclusive is not None and token is not self._exclusive:
            raise RuntimeError("Session is exclusively owned")
        if kind not in ("debug", "msg", "raw", "upgrade"):
            raise ValueError("Unknown service")
        if kind in ("raw", "upgrade") and (token is None or token is not self._exclusive):
            raise RuntimeError("Exclusive token required")
        return self._write_transport(data)


    # ------------------------------------------------------------------
    # 属性
    # ------------------------------------------------------------------

    @property
    def exclusive(self) -> bool:
        return self._exclusive is not None

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
            if self._state != "error":
                self._set_state("connected", info=f"{port} @ {baudrate}")
                if not self._requests:
                    self.negotiate()
        except Exception as e:
            self._set_state("error", info=f"无法打开 {port}: {e}")

    def disconnect(self) -> None:
        """断开当前连接"""
        self._disconnect_current()
        self._set_state("disconnected")

    # ------------------------------------------------------------------
    # 数据收发
    # ------------------------------------------------------------------

    def write(self, data: bytes, *, token=None) -> int:
        """Legacy raw entry: real transports require an exclusive token."""
        if self._transport_type() == "serial" and (token is None or token is not self._exclusive):
            raise RuntimeError("RAW requires an exclusive session token")
        if self._exclusive is not None and token is not self._exclusive:
            raise RuntimeError("Session is exclusively owned")
        return self._write_transport(data)

    def _write_transport(self, data: bytes) -> int:
        if self._transport is None:
            raise RuntimeError("Transport not connected")
        if not self.is_connected:
            raise RuntimeError("Transport not connected")
        try:
            if not self._transport.is_open:
                raise RuntimeError("Transport unexpectedly closed")
            written = self._transport.write(data)
            if written != len(data):
                raise OSError(f"Incomplete transport write: {written}/{len(data)} bytes")
        except Exception as exc:
            self.invalidate("transport write error")
            self._set_state("error", info=str(exc))
            raise
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
        self._state = "disconnected"
        self.invalidate("disconnect")
        if self._transport is not None:
            try:
                self._transport.close()
            except Exception as exc:
                self._set_state("error", info=f"Transport close failed: {exc}")
                raise
            self._transport.ready_read.disconnect(self._on_ready_read)
            self._transport.error_occurred.disconnect(self._on_transport_error)
            self._transport = None

    def _on_ready_read(self, data: bytes) -> None:
        """Transport 收到数据 → emit data_received + ProtocolEngine 解析"""
        if self.sender() is not self._transport or not self.is_connected:
            return
        self.data_received.emit(data)
        self._protocol_engine.feed(data)

    def _on_transport_error(self, msg: str) -> None:
        """Only the active transport can fail this session."""
        if self.sender() is not self._transport or self._state not in ("connected", "connecting"):
            return
        self.invalidate("transport error")
        self._set_state("error", info=msg)

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
