"""Temporary stop-and-wait serial firmware upgrade UI."""
from __future__ import annotations

import struct
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class SerialUpgradeController(QObject):
    """Controller for the firmware's existing temporary upgrade protocol."""

    status_changed = Signal(str)
    progress_changed = Signal(int, int)
    started = Signal()
    finished = Signal(bool, str)

    TRIGGER = bytes((0x1B, 0x55, 0x50, 0x47, 0x0A))
    READY = 0x55
    ACK = 0x79
    NACK = 0x1F
    DONE = 0x44
    BLOCK_SIZE = 256
    MAX_IMAGE_SIZE = 512 * 1024

    def __init__(self, session=None, writer=None, parent=None):
        super().__init__(parent)
        self._session = session
        self._writer = writer or (session.write if session is not None else None)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._on_timeout)
        self._state = "idle"
        self._image = b""
        self._offset = 0
        self._sent_count = 0
        self._erase_started = False
        if session is not None and hasattr(session, "data_received"):
            session.data_received.connect(self.feed)

    @property
    def active(self) -> bool:
        return self._state != "idle"

    @staticmethod
    def validate_image(path: str) -> bytes:
        image_path = Path(path)
        if image_path.suffix.lower() != ".bin":
            raise ValueError("升级文件必须是 .bin")
        image = image_path.read_bytes()
        SerialUpgradeController.validate_image_bytes(image)
        return image

    @staticmethod
    def validate_image_bytes(image: bytes):
        size = len(image)
        if size < 8 or size > SerialUpgradeController.MAX_IMAGE_SIZE:
            raise ValueError("文件大小必须在 8 字节到 512 KiB 之间")
        initial_stack, reset_vector = struct.unpack_from("<II", image)
        if not 0x20000000 <= initial_stack < 0x20200000:
            raise ValueError(
                f"不是有效的 NS800RT5039 向量表：SP=0x{initial_stack:08X}")
        if (reset_vector & 1) == 0 or not 0x08000001 <= reset_vector < 0x08080000:
            raise ValueError(
                f"不是有效的 NS800RT5039 向量表：Reset=0x{reset_vector:08X}")

    def begin(self, path: str):
        self.begin_bytes(self.validate_image(path))

    def begin_bytes(self, image: bytes):
        if self.active:
            raise RuntimeError("串口升级正在进行")
        if self._writer is None:
            raise RuntimeError("没有可用的串口发送通道")
        self.validate_image_bytes(image)
        self._image = bytes(image)
        self._offset = 0
        self._sent_count = 0
        self._erase_started = False
        self._state = "wait_ready"
        self.started.emit()
        self.status_changed.emit("正在请求进入升级模式…")
        self.progress_changed.emit(0, len(self._image))
        try:
            self._writer(self.TRIGGER)
        except Exception as exc:
            self._fail(f"发送升级触发命令失败：{exc}")
            return
        self._arm_timeout(10_000)

    def feed(self, data: bytes):
        if not self.active:
            return
        for value in bytes(data):
            if not self.active:
                break
            expected = self._expected_reply()
            if value == self.NACK:
                self._fail(f"设备在“{self._stage_name()}”阶段返回失败")
                break
            if value != expected:
                # Before upgrade mode owns the UART, a trailing debug byte can
                # still arrive.  Ignore unrelated bytes and wait for the one-byte reply.
                continue
            self._handle_expected_reply()

    def _expected_reply(self) -> int:
        return {
            "wait_ready": self.READY,
            "wait_size_ack": self.ACK,
            "wait_erase_ack": self.ACK,
            "wait_block_ack": self.ACK,
            "wait_done": self.DONE,
        }[self._state]

    def _stage_name(self) -> str:
        return {
            "wait_ready": "进入升级模式（设备必须停机且处于空闲态）",
            "wait_size_ack": "校验文件大小",
            "wait_erase_ack": "擦除 Flash",
            "wait_block_ack": f"写入偏移 0x{self._offset:X}",
            "wait_done": "完成并复位",
        }.get(self._state, self._state)

    def _handle_expected_reply(self):
        self._timer.stop()
        if self._state == "wait_ready":
            self._state = "wait_size_ack"
            self.status_changed.emit("设备已进入升级模式，正在校验文件大小…")
            self._writer(struct.pack("<I", len(self._image)))
            self._arm_timeout(10_000)
        elif self._state == "wait_size_ack":
            self._state = "wait_erase_ack"
            self._erase_started = True
            self.status_changed.emit("正在擦除 Flash，请勿断电或断开串口…")
            self._arm_timeout(60_000)
        elif self._state == "wait_erase_ack":
            self.status_changed.emit("Flash 擦除完成，正在写入固件…")
            self._send_next_block()
        elif self._state == "wait_block_ack":
            self._offset += self._sent_count
            self.progress_changed.emit(self._offset, len(self._image))
            if self._offset < len(self._image):
                self._send_next_block()
            else:
                self._state = "wait_done"
                self.status_changed.emit("固件写入完成，等待设备校验并复位…")
                self._arm_timeout(10_000)
        elif self._state == "wait_done":
            self._complete()

    def _send_next_block(self):
        self._sent_count = min(self.BLOCK_SIZE, len(self._image) - self._offset)
        block = self._image[self._offset:self._offset + self._sent_count]
        self._state = "wait_block_ack"
        try:
            self._writer(block)
        except Exception as exc:
            self._fail(f"写入偏移 0x{self._offset:X} 失败：{exc}")
            return
        self._arm_timeout(10_000)

    def _arm_timeout(self, milliseconds: int):
        self._timer.start(milliseconds)

    def _on_timeout(self):
        self._fail(f"设备在“{self._stage_name()}”阶段响应超时")

    def abort_for_disconnect(self):
        if self.active:
            self._fail("串口连接已断开")

    def _complete(self):
        self._timer.stop()
        self._state = "idle"
        self.status_changed.emit("升级成功，设备已复位")
        self.finished.emit(True, "升级成功，设备已复位")

    def _fail(self, message: str):
        self._timer.stop()
        erase_started = self._erase_started
        self._state = "idle"
        if erase_started:
            message += "；Flash 已开始擦除，如无法重试请用调试器重新烧录"
        self.status_changed.emit(message)
        self.finished.emit(False, message)


class SerialUpgradeView(QWidget):
    """UI wrapper. MainWindow stops debug/MSG traffic before calling ``begin``."""

    start_requested = Signal(str)
    started = Signal()
    finished = Signal(bool, str)

    def __init__(self, session, parent=None):
        super().__init__(parent)
        self._connected = False
        self._controller = SerialUpgradeController(session=session, parent=self)
        self._controller.status_changed.connect(self._on_status)
        self._controller.progress_changed.connect(self._on_progress)
        self._controller.started.connect(self._on_started)
        self._controller.finished.connect(self._on_finished)
        self._build_ui()

    @property
    def active(self) -> bool:
        return self._controller.active

    def _build_ui(self):
        root = QVBoxLayout(self)
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        title = QLabel("临时串口升级")
        title.setObjectName("title")
        layout.addWidget(title)
        warning = QLabel(
            "仅支持当前固件已有的临时升级协议。开始前设备必须停机并处于主状态机 Idle；"
            "升级过程中请勿断电、关闭程序或拔出串口。")
        warning.setWordWrap(True)
        warning.setStyleSheet("color:#e0af68;")
        layout.addWidget(warning)

        file_row = QHBoxLayout()
        self._path = QLineEdit()
        self._path.setPlaceholderText("选择 NS800RT5039 原始 .bin 文件")
        browse = QPushButton("选择文件")
        browse.clicked.connect(self._browse)
        file_row.addWidget(self._path, 1)
        file_row.addWidget(browse)
        layout.addLayout(file_row)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        layout.addWidget(self._progress)
        self._status = QLabel("等待连接设备")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)
        self._start = QPushButton("开始串口升级")
        self._start.setObjectName("btn_danger")
        self._start.setEnabled(False)
        self._start.clicked.connect(self._request_start)
        layout.addWidget(self._start)
        root.addWidget(card)
        root.addStretch()

    def set_connected(self, connected: bool):
        self._connected = bool(connected)
        self._start.setEnabled(self._connected and not self.active)
        if not connected:
            self._controller.abort_for_disconnect()
            if not self.active:
                self._status.setText("等待连接设备")

    def begin(self, path: str):
        self._controller.begin(path)

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择升级固件", "", "固件二进制 (*.bin);;所有文件 (*)")
        if path:
            self._path.setText(path)

    def _request_start(self):
        path = self._path.text().strip()
        try:
            SerialUpgradeController.validate_image(path)
        except Exception as exc:
            QMessageBox.warning(self, "升级文件无效", str(exc))
            return
        answer = QMessageBox.question(
            self,
            "确认串口升级",
            "确认设备已关机并处于 Idle？\n\n开始擦除后不可取消。",
            QMessageBox.Yes | QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            self.start_requested.emit(path)

    def _on_started(self):
        self._start.setEnabled(False)
        self.started.emit()

    def _on_finished(self, ok: bool, message: str):
        self._start.setEnabled(self._connected)
        self.finished.emit(ok, message)

    def _on_status(self, message: str):
        self._status.setText(message)

    def _on_progress(self, completed: int, total: int):
        percent = int(completed * 100 / total) if total else 0
        self._progress.setValue(percent)
