"""Independent transport lifecycle regression checks using real Qt queuing."""
from threading import Thread
from types import SimpleNamespace

import pytest

from power_scope.session.session_controller import SessionController


def test_review_old_transport_queued_data_and_error_do_not_enter_new_session(qapp):
    session = SessionController()
    received = []
    session.data_received.connect(received.append)
    session.connect_mock()
    old = session.transport
    # The main thread does not pump Qt until after replacing the transport.
    producer = Thread(target=lambda: (
        old.ready_read.emit(b"old-session"),
        old.error_occurred.emit("old-session failure")))
    producer.start()
    producer.join(timeout=2)
    assert not producer.is_alive()
    try:
        session.connect_mock()
        qapp.processEvents()
        assert b"old-session" not in received
        assert session.state == "connected"
        assert "old-session failure" not in session.state_info
    finally:
        session.disconnect()


def test_review_short_write_never_emits_complete_data_sent(qapp, monkeypatch):
    session = SessionController()
    sent = []
    session.data_sent.connect(sent.append)
    session.connect_mock()
    monkeypatch.setattr(session.transport, "write", lambda data: len(data) - 1)
    try:
        with pytest.raises(Exception):
            session.write(b"whole-command")
        assert sent == []
        assert not session.is_connected
    finally:
        session.disconnect()


def test_review_handle_close_failure_retains_ownership_until_retry(qapp):
    from power_scope.transport.serial_transport import SerialTransport
    attempts = []
    def close_handle():
        attempts.append("close")
        if len(attempts) == 1:
            raise OSError("driver close failed")
    handle = SimpleNamespace(is_open=True, close=close_handle)
    reader = SimpleNamespace(stop=lambda: None, wait=lambda timeout: True)
    transport = SerialTransport("review")
    transport._serial, transport._reader_thread = handle, reader
    states = []
    transport.state_changed.connect(states.append)
    with pytest.raises(RuntimeError, match="close failed"):
        transport.close()
    assert transport._serial is handle and transport._reader_thread is reader
    assert not transport.is_open
    assert states == []
    transport.close()
    assert transport._serial is None and transport._reader_thread is None
    assert states == [False]


def test_review_serial_open_always_sets_finite_write_timeout(qapp, monkeypatch):
    import math
    import serial
    from power_scope.transport.serial_transport import SerialTransport
    options = {}
    handle = SimpleNamespace(is_open=False, close=lambda: None)
    def open_port(**kwargs):
        options.update(kwargs)
        return handle
    monkeypatch.setattr(serial, "Serial", open_port)
    transport = SerialTransport("review")
    try:
        transport.open()
        timeout = options.get("write_timeout")
        assert timeout is not None and math.isfinite(timeout) and timeout > 0
    finally:
        transport.close()
