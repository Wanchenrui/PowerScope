"""test_serial_unplug.py — USB 串口热拔插健壮性（无需真实硬件）

覆盖「拔掉串口上位机即退出」的修复点：
  1. SerialTransport 写失败：错误每次连接只上报一次（节流），仍抛给调用方
  2. SerialTransport 读线程失败：同样只上报一次
  3. close() 幂等，可重复调用
  4. SessionController：串口致命错误 → error 终态 + 主动关闭端口，
     不再停留在假「已连接」状态
  5. MainWindow：error 事件不再弹模态 QMessageBox（模态嵌套事件循环是
     弹窗级联 → 栈溢出退出的根因）；已建立过串口连接时启动自动重连，
     工具栏按钮变为「取消重连」且可取消
"""
from __future__ import annotations

import threading
import time

import pytest
from PySide6.QtCore import QCoreApplication

from power_scope.core.event_bus import EventBus, ConnectionStateEvent
from power_scope.transport import SerialTransport


def _pump(count: int = 10, sleep_s: float = 0.005) -> None:
    app = QCoreApplication.instance()
    for _ in range(count):
        app.processEvents()
        time.sleep(sleep_s)


class _FakeSerial:
    """最小 pyserial.Serial 假对象：支持可控的读/写失败注入"""

    instances: list["_FakeSerial"] = []

    def __init__(self, port=None, baudrate=115200, **_kw):
        self.port = port
        self.baudrate = baudrate
        self.is_open = True
        self.written = bytearray()
        self.fail_write = False
        self.fail_read = False
        self.close_calls = 0
        self._cancel = threading.Event()
        _FakeSerial.instances.append(self)

    def read(self, _n=1):
        if self.fail_read:
            raise OSError("ClearCommError failed (PermissionError(13, '拒绝访问。', None, 5))")
        self._cancel.wait(0.02)  # 模拟阻塞读等待数据
        return b""

    def write(self, data):
        if self.fail_write:
            raise OSError("WriteFile failed (PermissionError(13, '拒绝访问。', None, 5))")
        self.written.extend(data)
        return len(data)

    def cancel_read(self):
        self._cancel.set()

    def close(self):
        self.close_calls += 1
        self.is_open = False


@pytest.fixture(autouse=True)
def _fresh_fakes():
    _FakeSerial.instances.clear()
    yield
    _FakeSerial.instances.clear()


class TestSerialTransportFault:
    def test_write_failure_reported_once(self, qapp, monkeypatch):
        import serial
        monkeypatch.setattr(serial, "Serial", _FakeSerial)
        t = SerialTransport("COM_FAKE")
        errors: list[str] = []
        t.error_occurred.connect(errors.append)
        t.open()
        fake = _FakeSerial.instances[-1]
        fake.fail_write = True

        with pytest.raises(Exception):
            t.write(b"AA")
        with pytest.raises(Exception):
            t.write(b"BB")
        _pump()

        assert len(errors) == 1  # 节流：每次连接只上报一次
        assert t.is_open is True  # transport 不自闭，由上层决定断开
        t.close()
        assert fake.close_calls == 1
        assert t.is_open is False

    def test_read_failure_reported_once(self, qapp, monkeypatch):
        import serial
        monkeypatch.setattr(serial, "Serial", _FakeSerial)
        t = SerialTransport("COM_FAKE")
        errors: list[str] = []
        t.error_occurred.connect(errors.append)
        t.open()
        _FakeSerial.instances[-1].fail_read = True

        deadline = time.time() + 3
        while not errors and time.time() < deadline:
            _pump(2)
        t.close()

        assert len(errors) == 1

    def test_close_idempotent(self, qapp, monkeypatch):
        import serial
        monkeypatch.setattr(serial, "Serial", _FakeSerial)
        t = SerialTransport("COM_FAKE")
        t.open()
        t.close()
        t.close()  # 重复关闭不应崩溃
        assert t.is_open is False


class TestSessionControllerFatalError:
    def test_serial_write_fatal_disconnects(self, qapp, monkeypatch):
        """写路径致命错误 → session 进入 error 终态并真正关闭端口"""
        import serial
        monkeypatch.setattr(serial, "Serial", _FakeSerial)
        from power_scope.session.session_controller import SessionController

        bus = EventBus.instance()
        bus._reset_for_test()
        events: list[ConnectionStateEvent] = []
        bus.subscribe("connection/state", events.append)

        sc = SessionController()
        sc.connect_serial("COM_FAKE", 115200)
        _pump()
        assert sc.is_connected is True

        fake = _FakeSerial.instances[-1]
        fake.fail_write = True
        with pytest.raises(Exception):
            sc.write(b"\x01")
        _pump()

        assert sc.is_connected is False
        assert sc.state == "error"
        assert fake.close_calls >= 1  # 端口被真正关闭

        errors = [e for e in events if e.state == "error"]
        assert len(errors) == 1
        assert errors[0].transport_type == "serial"  # UI 重连判定依赖该字段
        assert "COM_FAKE" in errors[0].info

        # 断开后继续写：抛 RuntimeError，但不再产生新的 error 事件
        with pytest.raises(Exception):
            sc.write(b"\x02")
        _pump()
        assert len([e for e in events if e.state == "error"]) == 1

    def test_mock_error_still_nonfatal(self, qapp):
        """mock transport 错误保持原语义：仅上报，不断开"""
        from power_scope.session.session_controller import SessionController

        sc = SessionController()
        sc.connect_mock()
        sc.transport.error_occurred.emit("simulated glitch")
        _pump()
        assert sc.is_connected is True
        sc.disconnect()


class TestMainWindowUnplug:
    def _mw(self, qapp):
        from power_scope.config.device_profile import DeviceProfile
        from power_scope.ui.main_window import MainWindow
        return MainWindow(DeviceProfile(name="t", device_type="x", version="1"))

    def _fake_serial_connected(self, mw):
        mw._session._transport = SerialTransport("COM_TEST")
        mw._session._connect_signals()
        mw._session._state = "connected"

    def test_error_event_no_modal_and_starts_reconnect(self, qapp, monkeypatch):
        from PySide6.QtWidgets import QMessageBox
        warnings: list = []
        monkeypatch.setattr(QMessageBox, "warning",
                            lambda *a, **k: warnings.append(a))

        mw = self._mw(qapp)
        self._fake_serial_connected(mw)
        mw._on_connection_state(ConnectionStateEvent("connected", "serial", "COM_TEST"))
        assert mw._reconnect_params["port"] == "COM_TEST"

        mw._on_connection_state(
            ConnectionStateEvent("error", "serial", "COM_TEST 连接中断: x"))
        assert warnings == []                      # 不再弹模态窗
        assert mw._reconnect_timer.isActive()      # 自动重连已启动
        assert mw._connect_btn.text().strip() == "取消重连"

        mw._on_connect()                           # 用户取消重连
        assert not mw._reconnect_timer.isActive()
        assert mw._connect_btn.text().strip() == "连接设备"
        mw.close()

    def test_error_without_prior_connection_no_reconnect(self, qapp, monkeypatch):
        from PySide6.QtWidgets import QMessageBox
        monkeypatch.setattr(QMessageBox, "warning",
                            lambda *a, **k: (_ for _ in ()).throw(
                                AssertionError("不应弹模态窗")))
        mw = self._mw(qapp)
        mw._on_connection_state(
            ConnectionStateEvent("error", "serial", "无法打开 COM99: x"))
        assert not mw._reconnect_timer.isActive()
        assert mw._connect_btn.text().strip() == "连接设备"
        mw.close()

    def test_poll_wave_status_write_failure_no_raise(self, qapp):
        """录波轮询写失败不应抛穿槽函数，按录波失败收尾"""
        mw = self._mw(qapp)
        mw._wave_capture = {
            "channels": [], "tap_id": 1, "period_us": 25, "points": 1,
            "row_bytes": 1, "mode": 0, "pretrigger_points": 0,
            "capture_id": 1, "raw": bytearray(), "request_pending": False,
            "auto_upload": False, "next_block_seq": 1, "status": None,
        }
        def _boom(**_k):
            raise RuntimeError("Transport not open")
        mw._debug.get_wave_status = _boom
        mw._poll_wave_status()  # 不应抛出
        assert mw._wave_capture is None
        mw.close()
