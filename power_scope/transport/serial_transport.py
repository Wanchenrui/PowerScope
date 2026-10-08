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
        # 初始即运行态。不能在 run() 里置 True：若 stop() 先于线程实际启动
        # 到达，run() 的赋值会覆盖停止请求，线程将永远循环（close() 的
        # wait() 超时 → QThread 运行中被析构 → 进程 abort）
        self._running = True

    def run(self) -> None:
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
        # 每次 open() 只允许向上报告一次错误（USB 拔出会同时打爆读/写两侧，
        # 节流后由上层统一走一次断开清理，阻断错误风暴 → 模态弹窗级联）
        self._error_reported = False
        # close() 时 wait() 超时仍未退出的读线程，保留引用直至自然结束，
        # 避免 QThread 运行中被析构触发 qFatal abort
        self._zombie_readers: list[SerialReaderThread] = []

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
        self._error_reported = False
        self._reader_thread = SerialReaderThread(self._serial, parent=self)
        self._reader_thread.data_ready.connect(self._on_data_ready)
        self._reader_thread.error_occurred.connect(self._report_error)
        self._reader_thread.start()
        self.state_changed.emit(True)

    def close(self) -> None:
        """关闭串口连接并停止读取线程（幂等，可重复调用）"""
        reader = self._reader_thread
        self._reader_thread = None
        if reader is not None:
            reader.stop()
            if not reader.wait(3000):
                # 极端情况：驱动未响应 cancel_read()。保留引用直至 finished，
                # 防止 QThread 仍在运行时失去引用被销毁导致进程 abort。
                self._zombie_readers.append(reader)
                reader.finished.connect(lambda r=reader: self._discard_zombie(r))
                reader.finished.connect(reader.deleteLater)
        serial_inst = self._serial
        self._serial = None
        if serial_inst is not None:
            try:
                serial_inst.close()
            except Exception:
                pass
        self.state_changed.emit(False)

    def write(self, data: bytes) -> int:
        """向串口发送数据

        写失败几乎总是致命的（USB 拔出/端口失效）：向上一层报告一次
        （节流，见 _report_error），随后照常抛给调用方处理。
        """
        if not self.is_open:
            raise RuntimeError("Transport not open")
        try:
            return self._serial.write(data)
        except Exception as e:
            self._report_error(str(e))
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

    def _report_error(self, msg: str) -> None:
        """错误上报节流：每次 open() 只上报第一次错误。

        USB 拔出时读线程与写路径会同时失败，若每次都 emit，
        上层每 80ms 轮询会产生每秒十余个错误事件（弹窗级联的根源）。
        """
        if self._error_reported:
            return
        self._error_reported = True
        self.error_occurred.emit(msg)

    def _discard_zombie(self, reader: SerialReaderThread) -> None:
        try:
            self._zombie_readers.remove(reader)
        except Exception:
            pass
