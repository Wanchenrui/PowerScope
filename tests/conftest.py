"""conftest.py — 共享 pytest fixtures

为所有 PowerScope 测试提供统一的 QApplication 和 EventBus 初始化。
避免每个测试文件重复定义相同的 fixtures。
"""
from __future__ import annotations

import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

from power_scope.core.event_bus import EventBus
from power_scope.config.device_profile import DeviceProfile, VarBinding


# ═══════════════════════════════════════════════════════════════════════════
# Qt 基础设施
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="session")
def qapp():
    """会话级 QApplication — 整个测试会话共享一个实例"""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app
    # 不调用 app.quit() — 会话级 fixture 可能被其他测试继续使用


# ═══════════════════════════════════════════════════════════════════════════
# EventBus 测试隔离
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture(autouse=True)
def reset_event_bus():
    """每个测试前重置 EventBus 单例，确保测试隔离"""
    EventBus._instance = None
    bus = EventBus.instance()
    bus._reset_for_test()
    # 排空 Qt 事件队列中积压的 QueuedConnection 信号
    app = QApplication.instance()
    if app is not None:
        for _ in range(5):
            app.processEvents()
    yield


def pump_events(count: int = 20) -> None:
    """辅助函数：排空 Qt 事件队列"""
    app = QApplication.instance()
    if app is not None:
        for _ in range(count):
            app.processEvents()


# ═══════════════════════════════════════════════════════════════════════════
# 设备配置 mock
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture
def test_profile() -> DeviceProfile:
    """标准测试用设备配置"""
    return DeviceProfile(
        name="测试微逆",
        device_type="microinverter",
        version="1.0.0",
        variables=[
            VarBinding(
                name="Kp", elf_symbol="gKp", display_name="比例增益",
                unit="", scale=1.0, offset=0,
                min_val=0, max_val=100, precision=2,
            ),
            VarBinding(
                name="Ki", elf_symbol="gKi", display_name="积分增益",
                unit="", scale=1.0, offset=0,
                min_val=0, max_val=10, precision=2,
            ),
            VarBinding(
                name="Vdc", elf_symbol="gVdcBus", display_name="直流母线电压",
                unit="V", scale=0.1, offset=0,
                min_val=0, max_val=600, precision=1,
            ),
        ],
        control_buttons=[],
        status_indicators=[],
        dashboard=[],
    )


@pytest.fixture
def empty_profile() -> DeviceProfile:
    """空配置（无变量）"""
    return DeviceProfile(
        name="空设备",
        device_type="custom",
        version="0.1",
    )


@pytest.fixture(autouse=True)
def _close_top_level_widgets_after_test():
    """测试隔离：每个测试结束后关闭所有顶层窗口，触发 MainWindow.closeEvent 停止定时器，
    避免遗留的模拟数据定时器在后续测试中继续 publish var/updated。"""
    yield
    app = QApplication.instance()
    if app is None:
        return
    for widget in list(app.topLevelWidgets()):
        try:
            widget.close()
        except Exception:
            pass
    for _ in range(3):
        app.processEvents()
