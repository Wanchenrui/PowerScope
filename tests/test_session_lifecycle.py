"""Session and serial lifecycle boundaries without real hardware."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from power_scope.session.session_controller import SessionController
from power_scope.transport.serial_transport import SerialReaderThread, SerialTransport


def test_transport_error_changes_state_and_blocks_writes(qapp):
    session = SessionController()
    session.connect_mock()
    session.transport.error_occurred.emit('read failed')
    try:
        assert session.state == 'error'
        assert session.state_info == 'read failed'
        with pytest.raises(RuntimeError):
            session.write(b'command')
    finally:
        session.disconnect()


def test_reconnect_discards_partial_protocol_frame(qapp):
    session = SessionController()
    session.connect_mock()
    session.transport.inject_data(bytes.fromhex('a55a0107010000'))
    assert session._protocol_engine._buf
    session.connect_mock()
    try:
        assert not session._protocol_engine._buf
    finally:
        session.disconnect()


def test_write_exception_never_reports_success(qapp, monkeypatch):
    session = SessionController()
    session.connect_mock()
    sent = []
    session.data_sent.connect(sent.append)
    def fail(data):
        raise OSError('write failed')
    monkeypatch.setattr(session.transport, 'write', fail)
    try:
        with pytest.raises(OSError, match='write failed'):
            session.write(b'command')
        assert sent == []
        assert session.state == 'error'
    finally:
        session.disconnect()


def test_stop_before_run_does_not_read(qapp):
    serial = SimpleNamespace(is_open=True, cancel_read=Mock())
    def stop_on_read(size):
        serial.is_open = False
        return b''
    serial.read = Mock(side_effect=stop_on_read)
    thread = SerialReaderThread(serial)
    thread.stop()
    thread.run()
    assert serial.read.call_count == 0


def test_close_wakes_reader_before_waiting(qapp):
    calls = []
    serial = SimpleNamespace(is_open=True, close=lambda: calls.append('close'))
    reader = SimpleNamespace(stop=lambda: calls.append('stop'),
        wait=lambda timeout: calls.append('wait') or True)
    transport = SerialTransport('fake')
    transport._serial, transport._reader_thread = serial, reader
    transport.close()
    assert calls == ['stop', 'close', 'wait']
    assert transport._reader_thread is None


def test_close_timeout_retains_resources_and_blocks_reopen(qapp):
    serial = SimpleNamespace(is_open=False, close=Mock())
    reader = SimpleNamespace(stop=Mock(), wait=Mock(return_value=False))
    transport = SerialTransport('fake')
    transport._serial, transport._reader_thread = serial, reader
    states = []
    transport.state_changed.connect(states.append)
    with pytest.raises(RuntimeError, match='reader'):
        transport.close()
    assert transport._reader_thread is reader
    assert transport._serial is serial
    assert states == []
    with pytest.raises(RuntimeError):
        transport.open()
    reader.wait.return_value = True
    transport.close()


def test_failed_close_preserves_old_transport_and_aborts_new_session(qapp, monkeypatch):
    session = SessionController()
    session.connect_mock()
    old = session.transport
    original_close = old.close
    monkeypatch.setattr(old, 'close', Mock(side_effect=RuntimeError('reader timeout')))
    with pytest.raises(RuntimeError, match='reader timeout'):
        session.connect_mock()
    assert not session.is_connected
    assert session.transport is old
    monkeypatch.setattr(old, 'close', original_close)
    session.disconnect()



def test_cancel_read_failure_still_closes_and_joins_real_reader(qapp, monkeypatch):
    from threading import Event
    import serial
    entered, released = Event(), Event()
    class Port:
        is_open = True
        def read(self, size):
            entered.set()
            released.wait(2)
            return b''
        def cancel_read(self):
            raise OSError('driver does not support cancel')
        def close(self):
            self.is_open = False
            released.set()
    port = Port()
    monkeypatch.setattr(serial, 'Serial', lambda **kwargs: port)
    transport = SerialTransport('fake')
    transport.open()
    reader = transport._reader_thread
    try:
        assert entered.wait(1)
        transport.close()
        assert not reader.isRunning()
        assert not transport.is_open
        assert transport._reader_thread is None
    finally:
        released.set()
        reader.stop()
        assert reader.wait(2000)


def test_thread_start_failure_closes_allocated_serial(qapp, monkeypatch):
    import serial
    port = SimpleNamespace(is_open=True, close=Mock(), cancel_read=Mock())
    monkeypatch.setattr(serial, 'Serial', lambda **kwargs: port)
    def fail_start(self):
        raise RuntimeError('start failed')
    monkeypatch.setattr(SerialReaderThread, 'start', fail_start)
    transport = SerialTransport('fake')
    with pytest.raises(RuntimeError, match='start failed'):
        transport.open()
    assert port.close.call_count == 1
    assert transport._serial is None and transport._reader_thread is None


def test_queued_old_reader_callbacks_ignored_after_replacement(qapp):
    from threading import Thread
    transport = SerialTransport('fake')
    port = SimpleNamespace(is_open=False)
    old = SerialReaderThread(port, parent=transport)
    current = SerialReaderThread(port, parent=transport)
    transport._reader_thread = old
    old.data_ready.connect(transport._on_data_ready)
    old.error_occurred.connect(transport._on_reader_error)
    data, errors = [], []
    transport.ready_read.connect(data.append)
    transport.error_occurred.connect(errors.append)
    producer = Thread(target=lambda: (old.data_ready.emit(b'old'), old.error_occurred.emit('old')))
    producer.start()
    producer.join(1)
    assert not producer.is_alive()
    transport._reader_thread = current
    qapp.processEvents()
    assert data == [] and errors == []
    transport.close()



def test_unexpected_closed_handle_fails_session_on_write(qapp):
    session = SessionController()
    session.connect_mock()
    session.transport.close()
    try:
        with pytest.raises(RuntimeError, match='unexpectedly closed'):
            session.write(b'command')
        assert session.state == 'error'
    finally:
        session.disconnect()



def test_serial_open_configures_bounded_write_timeout(qapp, monkeypatch):
    import serial
    kwargs_seen = {}
    def open_port(**kwargs):
        kwargs_seen.update(kwargs)
        return SimpleNamespace(is_open=False, close=Mock(), cancel_read=Mock())
    monkeypatch.setattr(serial, 'Serial', open_port)
    transport = SerialTransport('fake')
    try:
        transport.open()
        assert 0 < kwargs_seen['write_timeout'] <= 1.0
    finally:
        transport.close()


@pytest.mark.parametrize('close_fails', [False, True])
def test_window_error_state_closes_resources_or_rejects_close(qapp, monkeypatch, close_fails):
    from PySide6.QtGui import QCloseEvent
    from power_scope.config.device_profile import DeviceProfile
    from power_scope.ui.main_window import MainWindow
    window = MainWindow(DeviceProfile('fake', 'custom', '1'))
    session = window._session
    session.connect_mock()
    transport = session.transport
    session._state = 'error'
    original_close = transport.close
    close = Mock(side_effect=RuntimeError('reader timeout') if close_fails else original_close)
    monkeypatch.setattr(transport, 'close', close)
    cleanup = Mock(wraps=window._cleanup)
    monkeypatch.setattr(window, '_cleanup', cleanup)
    event = QCloseEvent()
    try:
        window.closeEvent(event)
        assert close.call_count == 1
        assert event.isAccepted() is (not close_fails)
        assert cleanup.call_count == (0 if close_fails else 1)
        if close_fails:
            assert session.transport is transport
            assert '无法关闭窗口' in window.statusBar().currentMessage()
        else:
            assert session._transport is None
    finally:
        monkeypatch.setattr(transport, 'close', original_close)
        session.disconnect()
        window._cleanup()
        window.deleteLater()
