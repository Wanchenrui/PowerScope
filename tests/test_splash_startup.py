"""test_splash_startup.py — 真实启动路径冒烟（含加载界面）

--selftest 绕过 main() 的启动加载界面，所以 tab_icons 这类仅被 splash
引用的模块曾在打包后首次启动才暴露 ImportError。本测试直接驱动 main()
的真实启动路径（offscreen + 定时自动退出），断言：
  1. 加载界面成功创建并推进步骤
  2. 主窗口成功显示（splash 随之关闭）
  3. 全部页签就绪
"""
from __future__ import annotations

import sys

import pytest


@pytest.fixture
def startup_env(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("QT_QPA_FONTDIR", "C:\\Windows\\Fonts")
    monkeypatch.setenv("QT_LOGGING_RULES", "qt.qpa.fonts=false")
    monkeypatch.setenv("POWERSCOPE_DATA_DIR", str(tmp_path / "data"))
    # 清掉可能传入的 pytest 参数，避免 _select_profile_path 误判
    monkeypatch.setattr(sys, "argv", [sys.argv[0]])


def test_startup_shows_splash_then_main_window(qapp, startup_env):
    from PySide6.QtCore import QTimer

    created = {}
    from power_scope.ui import splash as splash_module

    original_init = splash_module.SplashScreen.__init__

    def spy_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        created["splash"] = self

    splash_module.SplashScreen.__init__ = spy_init

    # 启动后 1.5s 自动关窗退出，避免 app.exec() 挂死测试
    def schedule_quit():
        QTimer.singleShot(1500, qapp.quit)

    QTimer.singleShot(50, schedule_quit)

    from power_scope.main import main
    try:
        main()
    finally:
        splash_module.SplashScreen.__init__ = original_init

    # splash 走过完整步骤
    splash = created.get("splash")
    assert splash is not None, "启动路径未创建加载界面"
    assert splash._bar.value() >= 90
    # 主窗口已构建（offscreen 平台 isVisible() 恒 False，按类型 + 页签断言）
    from power_scope.ui.power_main_window import PowerMainWindow
    win = next((w for w in qapp.topLevelWidgets()
                if isinstance(w, PowerMainWindow)), None)
    assert win is not None, "启动路径未构建主窗口"
    assert win._tabs.count() >= 9, f"页签数异常: {win._tabs.count()}"
    assert win._palette_btn is not None, "工具栏命令面板按钮未接线"


def test_splash_widget_progresses(qapp):
    from power_scope.ui.splash import SplashScreen, STARTUP_STEPS
    splash = SplashScreen()
    splash.show()
    for index in range(len(STARTUP_STEPS)):
        splash.advance(index)
    assert splash._bar.value() == 100
    assert splash._status.text() == STARTUP_STEPS[-1][0]
    splash.close()
