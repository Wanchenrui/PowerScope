"""base.py — Transport 抽象基类

定义所有 Transport 实现必须满足的接口契约。
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class ITransport(QObject):
    """Transport 抽象基类

    信号:
        ready_read(bytes):   收到新数据
        state_changed(bool): 连接状态变更 (True=已连接, False=已断开)
        error_occurred(str): 发生错误 (错误描述字符串)

    注：不继承 abc.ABC 因为与 QObject 的元类冲突，
        使用 NotImplementedError 强制子类实现抽象方法。
    """
    ready_read = Signal(bytes)
    state_changed = Signal(bool)
    error_occurred = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)

    # ------------------------------------------------------------------
    # 抽象接口（子类必须实现）
    # ------------------------------------------------------------------

    def open(self) -> None:
        """打开连接"""
        raise NotImplementedError

    def close(self) -> None:
        """关闭连接"""
        raise NotImplementedError

    def write(self, data: bytes) -> int:
        """发送数据，返回写入字节数"""
        raise NotImplementedError

    @property
    def is_open(self) -> bool:
        """是否已连接"""
        raise NotImplementedError

    @property
    def port(self) -> str:
        """端口/设备标识（如 COM3 或 mock）"""
        raise NotImplementedError

    # ------------------------------------------------------------------
    # 通用辅助
    # ------------------------------------------------------------------

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False
