"""
test_main_window.py — MainWindow 集成 SessionController 测试

验证 MainWindow：
  1. 创建 SessionController 并传入各视图
  2. 连接/断开 委托给 SessionController
  3. 通过 EventBus 的 connection/state 事件统一更新状态
  4. DashboardView 通过 EventBus 的 var/updated 事件刷新

TDD 流程:
  1. RED: 测试先写，运行应失败
  2. GREEN: 实现让测试通过
  3. REFACTOR: 清理冗余状态
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from PySide6.QtWidgets import QApplication

from power_scope.core.event_bus import EventBus, ConnectionStateEvent, VarUpdatedEvent
from power_scope.config.device_profile import DeviceProfile


@pytest.fixture(scope="module", autouse=True)
def _ensure_qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture(autouse=True)
def reset_bus():
    EventBus._instance = None  # 强制创建新实例，确保 _core 在 QApplication 线程中
    bus = EventBus.instance()
    bus._reset_for_test()
    app = QApplication.instance()
    if app is not None:
        for _ in range(5):
            app.processEvents()
    yield


@pytest.fixture
def profile():
    """创建一个测试用设备配置"""
    return DeviceProfile(
        name="测试微逆",
        device_type="microinverter",
        version="1.0.0",
        variables=[],
        control_buttons=[],
        status_indicators=[],
        dashboard=[]
    )


class TestMainWindowSessionController:
    """MainWindow 与 SessionController 集成"""

    def _pump(self, count: int = 20) -> None:
        app = QApplication.instance()
        for _ in range(count):
            app.processEvents()

    def _create_window(self, profile):
        from power_scope.ui.main_window import MainWindow
        window = MainWindow(profile)
        window._serial_view._sim_check.setChecked(True)
        return window

    def test_window_has_session_controller(self, profile):
        """MainWindow 创建时自动创建 SessionController"""
        mw = self._create_window(profile)
        assert mw._session is not None
        assert mw._session.is_connected is False

    def test_connect_delegates_to_session_controller(self, profile):
        """点击连接 → 委托给 SessionController"""
        mw = self._create_window(profile)
        assert mw._session.is_connected is False
        
        mw._on_connect()
        self._pump(50)
        
        assert mw._session.is_connected is True
        assert mw._connect_btn.text().strip() == "断开设备", f"Button text: {mw._connect_btn.text()!r}"

    def test_disconnect_delegates_to_session_controller(self, profile):
        """点击断开 → 委托给 SessionController"""
        mw = self._create_window(profile)
        mw._on_connect()
        self._pump()
        assert mw._session.is_connected is True

        mw._on_disconnect()
        self._pump()

        assert mw._session.is_connected is False
        assert mw._connect_btn.text().strip() == "连接设备"

    def test_serial_view_has_session_controller(self, profile):
        """SerialMonitorView 接收了 SessionController"""
        mw = self._create_window(profile)
        assert mw._serial_view._session is mw._session

    def test_var_view_receives_connected_state(self, profile):
        """VariableInspectorView 通过 EventBus 接收连接状态"""
        mw = self._create_window(profile)

        # 连接
        mw._on_connect()
        self._pump()

        # VariableInspectorView 应已通过 EventBus 收到 connected 状态
        assert mw._var_view._connected is True

    def test_dashboard_updates_via_event_bus(self, profile):
        """DashboardView 通过 var/updated 事件刷新"""
        from power_scope.config.device_profile import VarBinding, DashboardWidget

        var = VarBinding(
            name="Vdc_bus", elf_symbol="gVdc_bus", display_name="母线电压",
            unit="V", scale=0.01, offset=0, min_val=0, max_val=1000, precision=2,
            color="#f7768e", update_rate=1
        )
        profile.variables = [var]
        profile.dashboard = [DashboardWidget(
            id="info", type="info_panel", title="电压",
            x=0, y=0, w=4, h=3,
            config={"variables": ["Vdc_bus"]}
        )]

        mw = self._create_window(profile)
        mw._on_connect()
        self._pump()

        # 发布变量更新事件
        EventBus.instance().publish("var/updated", VarUpdatedEvent(
            name="Vdc_bus", raw_value=0, phys_value=380.5, unit="V", timestamp=1.0))
        self._pump()

        # Dashboard 应已更新 (info_panel 包含 Vdc_bus)
        assert "info" in mw._dashboard._widgets
        info_widget = mw._dashboard._widgets["info"]
        # 检查 Vdc_bus 的值是否已更新（不再是 "---"）
        vl, _ = info_widget._labels["Vdc_bus"]
        assert vl.text() != "---"

    def test_connection_state_event_unifies_views(self, profile):
        """连接状态变更通过 EventBus 统一所有视图"""
        mw = self._create_window(profile)
        assert mw._var_view._connected is False

        mw._on_connect()
        self._pump()

        # 所有视图的状态应统一
        assert mw._serial_view._connected is True
        assert mw._var_view._connected is True
        assert mw._tune_view._connected is True

        mw._on_disconnect()
        self._pump()

        assert mw._serial_view._connected is False
        assert mw._var_view._connected is False
        assert mw._tune_view._connected is False

    def test_sim_mode_publishes_var_events(self, profile):
        """模拟模式下定时发布 var/updated 事件"""
        from power_scope.config.device_profile import VarBinding
        profile.variables = [
            VarBinding(name="Vdc_bus", elf_symbol="gVdc_bus", display_name="母线电压",
                       unit="V", scale=0.01, offset=0, min_val=0, max_val=1000, precision=2,
                       color="#f7768e", update_rate=1)
        ]
        mw = self._create_window(profile)
        received = []
        EventBus.instance().subscribe("var/updated", lambda e: received.append(e))

        mw._on_connect()
        self._pump()

        # 触发一次模拟 tick
        mw._on_sim_tick()
        self._pump(20)

        # 应收到至少一个 var/updated 事件
        assert len(received) > 0

    def test_no_redundant_connected_state(self, profile):
        """MainWindow 不应维护独立的 _connected 状态"""
        mw = self._create_window(profile)
        # 连接状态应来自 SessionController，而非冗余的 _connected
        assert not hasattr(mw, '_connected') or mw._session.state == mw._connected

