"""serial_transport.py — 真实串口 Transport 实现 (QThread 阻塞读取)

基于 pyserial + QThread 阻塞 read()，替代 QTimer 轮询。
优势:
- 无 CPU 空转（无需 50ms 轮询 in_waiting）
- 高波特率（921600+）下不丢帧
- 数据到达即时响应，无需等待 poll 间隔
"""
from __future__ import annotations

from threading import Event

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
        self._stop_requested = Event()

    def run(self) -> None:
        while not self._stop_requested.is_set() and self._serial.is_open:
            try:
                data = self._serial.read(self._chunk_size)
                if data and not self._stop_requested.is_set():
                    self.data_ready.emit(data)
            except Exception as e:
                if not self._stop_requested.is_set():
                    self.error_occurred.emit(str(e))
                break

    def stop(self) -> None:
        """请求线程停止并唤醒阻塞的 read()"""
        self._stop_requested.set()
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
        self._closing = False

    # ------------------------------------------------------------------
    # ITransport 实现
    # ------------------------------------------------------------------

    def open(self) -> None:
        """打开串口连接并启动读取线程"""
        if self._reader_thread is not None or self._serial is not None:
            self.close()
        self._closing = False
        import serial
        self._serial = serial.Serial(
            port=self._port,
            baudrate=self._baudrate,
            bytesize=self._bytesize,
            parity=self._parity,
            stopbits=self._stopbits,
            timeout=self._timeout,
            write_timeout=1.0,
        )
        try:
            self._reader_thread = SerialReaderThread(self._serial, parent=self)
            self._reader_thread.data_ready.connect(self._on_data_ready)
            self._reader_thread.error_occurred.connect(self._on_reader_error)
            self._reader_thread.start()
        except Exception:
            self.close()
            raise
        self.state_changed.emit(True)

    def close(self) -> None:
        """关闭串口连接并停止读取线程"""
        self._closing = True
        if self._reader_thread is not None:
            self._reader_thread.stop()
        # Closing the handle also wakes platforms/drivers where cancel_read fails.
        close_error = None
        try:
            if self._serial is not None:
                self._serial.close()
        except Exception as exc:
            close_error = exc
        if self._reader_thread is not None and not self._reader_thread.wait(2000):
            # Keep ownership: destroying a running QThread can abort the process.
            raise RuntimeError("Serial reader did not exit within 2000 ms")
        if close_error is not None:
            raise RuntimeError(f"Serial close failed: {close_error}") from close_error
        self._reader_thread = None
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
        return not self._closing and self._serial is not None and self._serial.is_open

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
        if self.sender() is self._reader_thread and not self._closing:
            self.ready_read.emit(data)

    def _on_reader_error(self, message: str) -> None:
        if self.sender() is self._reader_thread and not self._closing:
            self.error_occurred.emit(message)
