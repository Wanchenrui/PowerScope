"""serial_transport.py — 真实串口 Transport 实现 (QThread 阻塞读取)

基于 pyserial + QThread 阻塞 read()，替代 QTimer 轮询。
优势:
- 无 CPU 空转（无需 50ms 轮询 in_waiting）
- 高波特率（921600+）下不丢帧
- 数据到达即时响应，无需等待 poll 间隔
"""
from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from .base import ITransport


class SerialReaderThread(QThread):
    """独立读取线程 — 阻塞 read() 减少 CPU 占用

    当串口有数据到达时立即通过 data_ready 信号发送到主线程。
    线程退出时通过 cancel_read() 唤醒阻塞的 read()。
    """

    data_ready = Signal(bytes)
    error_occurred = Signal(str)

    def __init__(self, serial_instance, chunk_size: int = 1024, parent=None) -> None:
        super().__init__(parent)
        self._serial = serial_instance
        self._chunk_size = chunk_size
        self._running = False

    def run(self) -> None:
        self._running = True
        while self._running and self._serial.is_open:
            try:
                data = self._serial.read(self._chunk_size)
                if data and self._running:
                    self.data_ready.emit(data)
            except Exception as e:
                if self._running:
                    self.error_occurred.emit(str(e))
                break

    def stop(self) -> None:
        """请求线程停止并唤醒阻塞的 read()"""
        self._running = False
        if self._serial and hasattr(self._serial, "cancel_read"):
            try:
                self._serial.cancel_read()
            except Exception:
                pass


class SerialTransport(ITransport):
    """串口 Transport — 封装 pyserial.Serial (QThread 阻塞读取)

    使用方式:
        t = SerialTransport("COM3", baudrate=115200)
        t.open()
        t.write(b"hello")
        # ready_read 信号在收到数据时自动触发
    """

    def __init__(
        self,
        port: str,
        baudrate: int = 115200,
        bytesize: int = 8,
        parity: str = "N",
        stopbits: float = 1,
        timeout: float = 0.1,
        poll_interval_ms: int = 50,  # 向后兼容，已忽略
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._port = port
        self._baudrate = baudrate
        self._bytesize = bytesize
        self._parity = parity
        self._stopbits = stopbits
        self._timeout = timeout
        self._serial = None  # type: ignore
        self._reader_thread: SerialReaderThread | None = None

    # ------------------------------------------------------------------
    # ITransport 实现
    # ------------------------------------------------------------------

    def open(self) -> None:
        """打开串口连接并启动读取线程"""
        import serial
        self._serial = serial.Serial(
            port=self._port,
            baudrate=self._baudrate,
            bytesize=self._bytesize,
            parity=self._parity,
            stopbits=self._stopbits,
            timeout=self._timeout,
        )
        self._reader_thread = SerialReaderThread(self._serial, parent=self)
        self._reader_thread.data_ready.connect(self._on_data_ready)
        self._reader_thread.error_occurred.connect(self.error_occurred.emit)
        self._reader_thread.start()
        self.state_changed.emit(True)

    def close(self) -> None:
        """关闭串口连接并停止读取线程"""
        if self._reader_thread:
            self._reader_thread.stop()
            self._reader_thread.wait(2000)
            self._reader_thread = None
        if self._serial:
            self._serial.close()
            self._serial = None
        self.state_changed.emit(False)

    def write(self, data: bytes) -> int:
        """向串口发送数据"""
        if not self.is_open:
            raise RuntimeError("Transport not open")
        try:
            return self._serial.write(data)
        except Exception as e:
            self.error_occurred.emit(str(e))
            raise

    @property
    def is_open(self) -> bool:
        return self._serial is not None and self._serial.is_open

    @property
    def port(self) -> str:
        return self._port

    # ------------------------------------------------------------------
    # 额外属性
    # ------------------------------------------------------------------

    @property
    def baudrate(self) -> int:
        return self._baudrate

    @property
    def bytesize(self) -> int:
        return self._bytesize

    @property
    def parity(self) -> str:
        return self._parity

    @property
    def stopbits(self) -> float:
        return self._stopbits

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _on_data_ready(self, data: bytes) -> None:
        """读取线程数据到达 → 转发到 ready_read 信号"""
        self.ready_read.emit(data)
