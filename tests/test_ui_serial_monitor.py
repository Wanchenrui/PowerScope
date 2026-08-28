"""
test_ui_serial_monitor.py — SerialMonitorView 解耦测试

验证 SerialMonitorView 通过 SessionController 委托所有串口操作：
  1. 连接/断开 委托给 SessionController
  2. 发送数据 委托给 SessionController.write()
  3. 接收数据 通过 SessionController.data_received 信号显示
  4. 模拟响应 通过 MockTransport.inject_data()

TDD 流程:
  1. RED: 测试先写，运行应失败（SerialMonitorView 未使用 SessionController）
  2. GREEN: 重构 SerialMonitorView 让测试通过
  3. REFACTOR: 清理遗留串口逻辑
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from PySide6.QtWidgets import QApplication

from power_scope.session.session_controller import SessionController
from power_scope.core.cffi_loader import DebugProtocol


@pytest.fixture(scope="module", autouse=True)
def _ensure_qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


class TestSerialMonitorViewWithSessionController:
    """SerialMonitorView 使用 SessionController 的集成测试"""

    def _pump(self, count: int = 5) -> None:
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        for _ in range(count):
            app.processEvents()

    def _create_view(self, session=None):
        from power_scope.ui.serial_monitor_view import SerialMonitorView
        if session is None:
            session = SessionController()
        view = SerialMonitorView(session_controller=session)
        view._sim_check.setChecked(True)  # 现有会话测试显式选择模拟模式
        return view

    def test_real_serial_mode_is_default(self):
        """真机联调版本启动时不能悄悄落入模拟 MCU。"""
        from power_scope.ui.serial_monitor_view import SerialMonitorView
        view = SerialMonitorView(session_controller=SessionController())
        assert view._sim_check.isChecked() is False
        view.close()
    def test_view_accepts_session_controller(self):
        """SerialMonitorView 可以接受 SessionController 参数"""
        sc = SessionController()
        view = self._create_view(sc)
        assert view is not None

    def test_connect_mock_via_session_controller(self):
        """点击连接 → SessionController.connect_mock() 被调用"""
        sc = SessionController()
        view = self._create_view(sc)
        assert sc.is_connected is False

        view._connect_btn.click()
        self._pump()

        assert sc.is_connected is True
        assert view._connect_btn.text() == "断开"

    def test_disconnect_via_session_controller(self):
        """点击断开 → SessionController.disconnect() 被调用"""
        sc = SessionController()
        view = self._create_view(sc)
        view._connect_btn.click()
        self._pump()
        assert sc.is_connected is True

        view._connect_btn.click()
        self._pump()
        assert sc.is_connected is False
        assert view._connect_btn.text() == "连接"

    def test_send_data_delegates_to_session_controller(self):
        """发送数据 → 通过 SessionController.write()"""
        sc = SessionController()
        view = self._create_view(sc)
        view._connect_btn.click()
        self._pump()

        view._send_input.setText("A5 5A 01 02 03 04")
        view._hex_tx_check.setChecked(True)
        view._on_send()

        assert sc.transport.written_bytes() == b"\xA5\x5A\x01\x02\x03\x04"

    def test_receive_data_displays_in_ui(self):
        """收到数据 → UI 显示区更新"""
        sc = SessionController()
        view = self._create_view(sc)
        view._connect_btn.click()
        self._pump()

        resp = DebugProtocol.build_response(0x07, 0x0001, 0x00, b"STM32")
        sc.transport.inject_data(resp)
        self._pump()

        display_text = view._display.toPlainText()
        assert "RX" in display_text
        assert "A5" in display_text

    def test_send_data_displays_tx_in_ui(self):
        """发送数据 → UI 显示 TX"""
        sc = SessionController()
        view = self._create_view(sc)
        view._connect_btn.click()
        self._pump()

        view._send_input.setText("A5 5A 01 02")
        view._hex_tx_check.setChecked(True)
        view._on_send()
        self._pump()

        display_text = view._display.toPlainText()
        assert "TX" in display_text

    def test_connection_state_updates_ui(self):
        """连接状态变更 → UI 更新"""
        sc = SessionController()
        view = self._create_view(sc)

        assert view._connect_btn.text() == "连接"
        view._connect_btn.click()
        self._pump()

        assert view._connect_btn.text() == "断开"

    def test_clear_display(self):
        """清空按钮清除显示区"""
        sc = SessionController()
        view = self._create_view(sc)
        view._connect_btn.click()
        self._pump()

        sc.transport.inject_data(b"\x01\x02\x03")
        self._pump()
        assert "01" in view._display.toPlainText()

        view._clear_display()
        # 清空后可能残留日志文本，但原始数据应已清除
        assert "01" not in view._display.toPlainText()

    def test_backward_compatibility_without_session_controller(self):
        """不传 SessionController 时仍能创建（向后兼容）"""
        from power_scope.ui.serial_monitor_view import SerialMonitorView
        view = SerialMonitorView()  # 不带参数
        assert view is not None
        assert view._connected is False

