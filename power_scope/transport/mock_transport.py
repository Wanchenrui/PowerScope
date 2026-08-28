"""mock_transport.py — 模拟 Transport 实现

纯内存模拟，用于：
  1. 单元测试（无需真实串口硬件）
  2. 演示/演示模式（Mock MCU 响应）

使用 inject_data() 模拟接收，write() 记录发送。
"""
from __future__ import annotations

from typing import Callable
from PySide6.QtCore import QObject, Signal

from .base import ITransport


class MockTransport(ITransport):
    """模拟 Transport — 内存中的收发通道

    使用方式:
        t = MockTransport()
        t.open()
        t.write(b"hello")          # 记录发送
        t.inject_data(b"world")    # 模拟收到数据
    """

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._open = False
        self._tx_buffer: bytearray = bytearray()

    # ------------------------------------------------------------------
    # ITransport 实现
    # ------------------------------------------------------------------

    def open(self) -> None:
        """打开模拟连接"""
        if not self._open:
            self._open = True
            self.state_changed.emit(True)

    def close(self) -> None:
        """关闭模拟连接"""
        if self._open:
            self._open = False
            self.state_changed.emit(False)

    def write(self, data: bytes) -> int:
        """发送数据（仅记录到内部缓冲区）"""
        if not self._open:
            raise RuntimeError("Transport not open")
        self._tx_buffer.extend(data)
        return len(data)

    @property
    def is_open(self) -> bool:
        return self._open

    @property
    def port(self) -> str:
        return "mock"

    # ------------------------------------------------------------------
    # 测试辅助
    # ------------------------------------------------------------------

    def inject_data(self, data: bytes) -> None:
        """模拟收到数据 — 触发 ready_read 信号"""
        if not self._open:
            raise RuntimeError("Transport not open")
        self.ready_read.emit(data)

    def written_bytes(self) -> bytes:
        """获取已发送的数据（用于测试断言）"""
        return bytes(self._tx_buffer)

    def clear_tx(self) -> None:
        """清空发送记录"""
        self._tx_buffer.clear()
