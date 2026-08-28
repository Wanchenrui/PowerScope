"""test_inspector_write_verify.py — 变量查看器「写入并校验」UI 路径"""
from __future__ import annotations

import pytest


@pytest.fixture
def inspector(qapp):
    from power_scope.ui.variable_inspector_view import VariableInspectorView
    return VariableInspectorView(profile=None)


class FakeDebug:
    def __init__(self, ok=True):
        self._ok = ok
        self.calls = []

    def write_and_verify(self, address, data, size, callback=None):
        self.calls.append((address, bytes(data), size))
        if callback is not None:
            callback(self._ok, bytes(data) if self._ok else b"")


class TestInspectorWriteVerify:
    def _setup(self, inspector, ok=True):
        from PySide6.QtWidgets import QMessageBox
        dbg = FakeDebug(ok=ok)
        inspector.set_debug_service(dbg)
        inspector.set_connected(True)
        inspector.add_watch_address("g_uart_debug_scratch", "uint32_t", "0x20001F30")
        inspector._watch_table.setCurrentCell(0, 0)
        inspector._write_input.setText("305419896")   # 0x12345678
        return dbg

    def test_verify_ok_updates_value(self, inspector, monkeypatch):
        from PySide6.QtWidgets import QMessageBox
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
        dbg = self._setup(inspector, ok=True)
        inspector._on_write_verify()
        assert dbg.calls == [(0x20001F30, b"\x78\x56\x34\x12", 4)]
        assert inspector._watch_table.item(0, 3).text() == "305419896"

    def test_verify_fail_marks_row(self, inspector, monkeypatch):
        from PySide6.QtWidgets import QMessageBox
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
        self._setup(inspector, ok=False)
        inspector._on_write_verify()
        # 失败不写入“正确值”文本（保持占位），仅标红，不抛异常
        assert inspector._watch_table.item(0, 3).text() in ("---", "")

    def test_cancel_does_nothing(self, inspector, monkeypatch):
        from PySide6.QtWidgets import QMessageBox
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.No)
        dbg = self._setup(inspector, ok=True)
        inspector._on_write_verify()
        assert dbg.calls == []
