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
        view.set_control_check(lambda: "" if session._transport_type() == "mock" else "denied")
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



class TestSerialMonitorViewUiPolish:
    """串口监视页视觉/交互升级: 状态徽章、状态标签关键字、图标与统计行"""

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
        view.set_control_check(lambda: "" if session._transport_type() == "mock" else "denied")
        view._sim_check.setChecked(True)
        return view

    # ---- 页头徽章与状态标签 ----

    def test_header_badge_initial_disconnected(self):
        """初始态: 徽章「未连接」neutral，状态标签/按钮与旧版关键字一致"""
        view = self._create_view()
        assert view._status_badge is not None
        assert view._status_badge._text.text() == "未连接"
        assert view._status_badge.property("tone") == "neutral"
        assert "未连接" in view._status_label.text()
        assert view._connect_btn.text() == "连接"
        assert view._connect_btn.objectName() == "btn_success"

    def test_mock_connect_syncs_badge_and_status(self):
        """模拟模式连接 → 徽章 ok、状态标签含「已连接」「模拟模式」、按钮「断开」"""
        view = self._create_view()
        view._connect_btn.click()
        self._pump()

        assert view._connected is True
        assert view._connect_btn.text() == "断开"
        assert view._connect_btn.objectName() == "btn_danger"
        assert "已连接" in view._status_badge._text.text()
        assert view._status_badge.property("tone") == "ok"
        status = view._status_label.text()
        assert "已连接" in status
        assert "模拟模式" in status

    def test_disconnect_restores_badge_and_keywords(self):
        """断开 → 徽章/标签回到未连接，按钮回到「连接」"""
        view = self._create_view()
        view._connect_btn.click()
        self._pump()
        assert view._connect_btn.text() == "断开"

        view._connect_btn.click()
        self._pump()

        assert view._connected is False
        assert view._connect_btn.text() == "连接"
        assert view._connect_btn.objectName() == "btn_success"
        assert view._status_badge._text.text() == "未连接"
        assert view._status_badge.property("tone") == "neutral"
        assert "未连接" in view._status_label.text()

    def test_error_event_syncs_badge_and_status(self):
        """connection/state error 事件 → 徽章 error、状态标签「连接失败」不被覆盖"""
        from power_scope.core.event_bus import EventBus, ConnectionStateEvent
        view = self._create_view()
        EventBus.instance().publish("connection/state", ConnectionStateEvent(
            state="error", transport_type="serial", info="无法打开 COM1"))
        self._pump()

        assert "连接失败" in view._status_label.text()
        assert view._status_badge._text.text() == "连接失败"
        assert view._status_badge.property("tone") == "error"
        # 失败后再次操作入口可用
        assert view._connect_btn.text() == "连接"
        assert view._connect_btn.isEnabled() is True

    def test_connected_event_from_external_connect(self):
        """外部连接（main_window 直调 set_connected / EventBus connected）也同步徽章"""
        from power_scope.core.event_bus import EventBus, ConnectionStateEvent
        view = self._create_view()
        EventBus.instance().publish("connection/state", ConnectionStateEvent(
            state="connected", transport_type="mock", info=""))
        self._pump()

        assert view._connected is True
        assert "已连接" in view._status_badge._text.text()
        assert "模拟模式" in view._status_label.text()

    # ---- 发送限制与收发行为不变 ----

    def test_real_serial_send_restriction_not_relaxed(self):
        """安全确认拒绝（真实串口控制受限语义）时发送被拦截，不放宽限制"""
        from power_scope.ui.serial_monitor_view import SerialMonitorView
        sc = SessionController()
        view = SerialMonitorView(session_controller=sc)
        # 镜像 main_window._control_restriction: 非模拟传输且无安全确认 → 拒绝
        view.set_control_check(lambda: "denied: 真实串口控制需安全确认")
        view._sim_check.setChecked(True)
        view._connect_btn.click()
        self._pump()

        view._send_input.setText("A5 5A 01 02")
        view._on_send()
        self._pump()

        assert sc.transport.written_bytes() == b""
        assert "denied" in view._display.toPlainText()

    def test_send_receive_behavior_unchanged(self):
        """升级后原有收发链路不变: 发送委托 write、注入数据上屏、计数正确"""
        sc = SessionController()
        view = self._create_view(sc)
        view._connect_btn.click()
        self._pump()

        view._send_input.setText("A5 5A 01 02")
        view._on_send()
        self._pump()
        assert sc.transport.written_bytes() == b"\xA5\x5A\x01\x02"
        assert view._tx_count == 4
        assert "TX" in view._display.toPlainText()

        sc.transport.inject_data(b"\x01\x02\x03")
        self._pump()
        assert view._rx_count == 3
        assert "RX" in view._display.toPlainText()
        assert view._rx_label.text() == "RX: 3 字节"

    # ---- 布局与主题 ----

    def test_quick_commands_wrapped_in_grid(self):
        """快捷命令按 4 列网格排列，避免两行挤压发送卡片"""
        from PySide6.QtWidgets import QGridLayout
        view = self._create_view()
        commands = view.ns800rt_quick_commands()
        grids = [g for g in view.findChildren(QGridLayout) if g is not view.layout()]
        quick_grid = next(
            g for g in grids
            if g.columnCount() == 4 and g.count() == len(commands))
        assert quick_grid.rowCount() * 4 >= len(commands)
        # 每个快捷按钮都带非空矢量图标
        from PySide6.QtWidgets import QPushButton
        texts = {label for label, _cmd in commands}
        buttons = [b for b in view.findChildren(QPushButton) if b.text() in texts]
        assert len(buttons) == len(commands)
        for btn in buttons:
            assert btn.icon() is not None and not btn.icon().isNull()

    def test_stats_labels_same_row_equal_width(self):
        """RX/TX 统计同一行且等宽（等宽字体 + 相同最小宽度）"""
        view = self._create_view()
        view.resize(800, 600)
        view.show()
        self._pump()
        assert view._rx_label.objectName() == "stat_value"
        assert view._tx_label.objectName() == "stat_value"
        assert view._rx_label.minimumWidth() == view._tx_label.minimumWidth()
        assert view._rx_label.geometry().y() == view._tx_label.geometry().y()

    def test_buttons_have_vector_icons(self):
        """连接/发送/刷新/清空按钮均带非空图标"""
        view = self._create_view()
        assert not view._connect_btn.icon().isNull()
        for button, _name, _role in view._icon_buttons:
            assert not button.icon().isNull(), f"{button.text()} 缺少图标"

    def test_apply_theme_refreshes_icons_and_badge(self):
        """apply_theme 切换主题后徽章与图标按新主题刷新"""
        view = self._create_view()
        before = view._status_badge._dot.styleSheet()
        view._connect_btn.click()
        self._pump()
        icon_before = view._connect_btn.icon()

        view.apply_theme("light")
        self._pump()

        assert view._status_badge._dot.styleSheet() != before
        assert view._status_badge.property("tone") == "ok"
        assert not view._connect_btn.icon().isNull()
        assert view._connect_btn.icon().pixmap(16, 16) is not None

    def test_receive_area_keeps_vertical_space(self):
        """接收卡片占据剩余垂直空间（比发送/配置卡片高）"""
        view = self._create_view()
        view.resize(800, 600)
        view.show()
        self._pump()
        display_card = view._display.parentWidget()
        assert display_card.objectName() == "card"
        assert view._display.minimumHeight() >= 200
        assert view._display.document().maximumBlockCount() == 5000
