"""test_tuning_write_verify.py — 调参页「写参数即读回确认」"""
from __future__ import annotations

import pytest


@pytest.fixture
def tuning(qapp):
    from power_scope.ui.tuning_view import TuningView
    return TuningView(profile=None)


class FakeDebug:
    def __init__(self, ok=True):
        self._ok = ok
        self.calls = []

    def write_and_verify(self, address, data, size, callback=None):
        self.calls.append((address, bytes(data), size))
        if callback is not None:
            callback(self._ok, bytes(data) if self._ok else b"")


def _resolver_kp_only(name):
    from power_scope.core.debug_service import SampleChannel
    if name == "Kp":
        return SampleChannel(name="Kp", address=0x20000100, size=4, type_name="float")
    return None


class TestTuningWriteVerify:
    def test_apply_writes_and_confirms(self, tuning, monkeypatch):
        from PySide6.QtWidgets import QMessageBox
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
        dbg = FakeDebug(ok=True)
        tuning.set_connected(True)
        tuning.set_debug_service(dbg)
        tuning.set_channel_resolver(_resolver_kp_only)
        tuning._kp_input.setValue(0.85)
        tuning._ki_input.setValue(120.0)
        tuning._kd_input.setValue(0.0)

        tuning._on_apply()

        assert dbg.calls and dbg.calls[0][0] == 0x20000100
        text = tuning._result_text.toPlainText()
        assert "✓ Kp" in text
        assert "未在 ELF 解析到地址" in text     # Ki/Kd 未配置符号

    def test_apply_disconnected_records_only(self, tuning, monkeypatch):
        from PySide6.QtWidgets import QMessageBox
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
        dbg = FakeDebug()
        tuning.set_debug_service(dbg)
        tuning.set_channel_resolver(_resolver_kp_only)
        tuning.set_connected(False)        # 未连接
        tuning._kp_input.setValue(0.85)
        tuning._on_apply()
        # 未连接：_on_apply 早退（"未连接设备"），不应调用 write
        assert dbg.calls == []

    def test_verify_fail_shows_cross(self, tuning, monkeypatch):
        from PySide6.QtWidgets import QMessageBox
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
        dbg = FakeDebug(ok=False)
        tuning.set_connected(True)
        tuning.set_debug_service(dbg)
        tuning.set_channel_resolver(_resolver_kp_only)
        tuning._kp_input.setValue(0.85)
        tuning._on_apply()
        assert "✗ Kp 读回校验失败" in tuning._result_text.toPlainText()
