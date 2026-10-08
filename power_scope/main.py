"""PowerScope 应用入口"""
import json
import sys
import os
from PySide6.QtWidgets import QApplication, QMessageBox
from .config.device_profile import load_profile, list_profiles
from .ui.power_main_window import PowerMainWindow


def _get_resource_dir():
    """获取资源目录 (支持 PyInstaller 打包环境)"""
    if getattr(sys, 'frozen', False):
        # PyInstaller 打包后: 资源在 _MEIPASS 或 exe 同级目录
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _select_profile_path(profiles, argv):
    """显式参数优先；否则 NS800RT > 通用微逆 > 首个配置。"""
    if len(argv) > 1 and os.path.exists(argv[1]):
        return argv[1]
    for _ptype, path in profiles:
        if "ns800rt" in path.lower():
            return path
    for _ptype, path in profiles:
        lowered = path.lower()
        if "microinverter" in lowered or "micro" in lowered:
            return path
    return profiles[0][1]

def _app_icon_path():
    """应用图标文件路径（优先打包内资源，其次仓库内 icons/app.png）。"""
    candidates = []
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", None) or os.path.dirname(sys.executable)
        candidates.append(os.path.join(base, "power_scope", "ui", "icons", "app.png"))
    here = os.path.dirname(os.path.abspath(__file__))
    candidates.append(os.path.join(here, "ui", "icons", "app.png"))
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def _app_icon():
    """应用图标：优先打包内资源，其次仓库内 power_scope/ui/icons/app.png。

    没有窗口图标时标题栏/任务栏/Alt+Tab 显示默认 Python 图标，
    是「半成品感」最直接的来源。
    """
    import os
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QStyle

    path = _app_icon_path()
    if path:
        return QIcon(path)
    # 兜底：用 Fusion 内置图标，至少不是默认 Python 图标
    style = QApplication.style()
    return style.standardIcon(QStyle.SP_ComputerIcon) if style else QIcon()


def _cffi_ok() -> bool:
    """C 核心库是否可用（frozen 环境下验证 power_core.dll 是否被打包进来）。"""
    try:
        from .core.cffi_loader import CRC16
        return bool(CRC16.calc(b"123456789"))
    except Exception:
        return False


def selftest(out_png: str = "selftest.png") -> int:
    """无头冒烟测试：构造窗口 → 切遍全部 tab → 截图 → 写 JSON 摘要 → 退出。

    供打包后验证与 CI 使用::

        PowerScope.exe --selftest out.png

    环境变量 QT_QPA_PLATFORM=offscreen 时无需显示器。返回 0 表示通过。

    注意：本路径绕过了 main() 的启动加载界面（splash），所以加载界面的
    冒烟由 test_splash_startup.py（真实启动路径 + splash 断言）覆盖。
    """
    import json
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("QT_QPA_FONTDIR", "C:\\Windows\\Fonts")

    app = _ensure_qapp()
    app.setApplicationName("PowerScope")
    app.setOrganizationName("PowerScope")
    app.setStyle("Fusion")
    app.setWindowIcon(_app_icon())

    profiles = list_profiles()
    if not profiles:
        print("[selftest][FAIL] 未找到任何设备配置文件")
        return 2
    profile_path = _select_profile_path(profiles, [sys.argv[0]])
    try:
        profile = load_profile(profile_path)
    except Exception as exc:
        print(f"[selftest][FAIL] 配置加载失败: {exc}")
        return 2

    from .ui.theme import build_palette
    app.setPalette(build_palette(profile.theme))

    from .ui.power_main_window import PowerMainWindow
    win = PowerMainWindow(profile)
    win.resize(1440, 900)
    win.show()
    app.processEvents()

    summary = {
        "frozen": bool(getattr(sys, "frozen", False)),
        "profile": profile.name,
        "theme": profile.theme,
        "tabs": [win._tabs.tabText(i) for i in range(win._tabs.count())],
        "variables": len(profile.variables),
        "c_core_dll_ok": _cffi_ok(),
        "shots": [],
    }
    # 冒烟断言：全部页签（含 P1-10 会话回放）都在
    for expected in ("仪表盘", "波形", "串口监控", "变量查看", "调参",
                     "AI助手", "MSG命令", "串口升级", "会话回放"):
        if expected not in summary["tabs"]:
            print(f"[selftest][FAIL] 缺少页签: {expected}")
            return 3

    stem = os.path.splitext(out_png)[0]
    for i in range(win._tabs.count()):
        win._tabs.setCurrentIndex(i)
        app.processEvents()
        path = f"{stem}_{i:02d}.png"
        win._tabs.currentWidget().grab().save(path)
        summary["shots"].append(os.path.basename(path))
    win.grab().save(out_png)

    print("[selftest] " + json.dumps(summary, ensure_ascii=False))
    with open(stem + ".json", "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)
    return 0


def _ensure_qapp(argv=None):
    """复用已存在的 QApplication（嵌入/测试环境），否则创建。"""
    app = QApplication.instance()
    if app is None:
        app = QApplication(argv if argv is not None else sys.argv)
        app.setStyle("Fusion")
    return app


def startup_smoke(seconds: float = 2.0) -> int:
    """真实启动路径冒烟：加载界面 → 主窗口 → N 秒后自动退出。

    --selftest 绕过 main() 的启动流程（含 splash），打包后首次启动的
    ImportError 正是这样漏掉的。本入口驱动完整启动路径（splash → 配置 →
    主题 → 主窗口 → 事件循环），offscreen 下可无人值守运行。

        PowerScope.exe --startup-smoke 2.0
    """
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("QT_QPA_FONTDIR", "C:\\Windows\\Fonts")
    os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.fonts=false")

    app = _ensure_qapp()
    app.setApplicationName("PowerScope")
    app.setOrganizationName("PowerScope")
    app.setWindowIcon(_app_icon())
    app.setStyle("Fusion")

    profiles = list_profiles()
    if not profiles:
        print("[startup-smoke][FAIL] 未找到任何设备配置文件")
        return 2
    profile_path = _select_profile_path(profiles, [sys.argv[0]])
    profile = load_profile(profile_path)

    from .ui.splash import SplashScreen
    splash = SplashScreen(app_icon_path=_app_icon_path())
    splash.show()
    app.processEvents()

    from .ui.theme import build_palette
    app.setPalette(build_palette(profile.theme))
    splash.message("正在构建调试界面…")
    app.processEvents()

    from .ui.power_main_window import PowerMainWindow
    window = PowerMainWindow(profile)
    window.show()
    splash.advance(5)
    app.processEvents()
    splash.finish(window)

    from PySide6.QtCore import QTimer
    QTimer.singleShot(int(seconds * 1000), app.quit)
    app.exec()

    tabs = [window._tabs.tabText(i) for i in range(window._tabs.count())]
    summary = {
        "startup_smoke": True,
        "frozen": bool(getattr(sys, "frozen", False)),
        "profile": profile.name,
        "tabs": tabs,
        "tabs_ok": len(tabs) >= 9,
        "c_core_dll_ok": _cffi_ok(),
    }
    print("[startup-smoke] " + json.dumps(summary, ensure_ascii=False))
    window.close()
    return 0 if summary["tabs_ok"] and summary["c_core_dll_ok"] else 3


def main():
    if len(sys.argv) > 2 and sys.argv[1] == "--selftest":
        return selftest(sys.argv[2])
    if len(sys.argv) > 2 and sys.argv[1] == "--startup-smoke":
        try:
            return startup_smoke(float(sys.argv[2]))
        except ValueError:
            return startup_smoke()

    app = _ensure_qapp()
    app.setApplicationName("PowerScope")
    app.setOrganizationName("PowerScope")
    app.setWindowIcon(_app_icon())
    # Fusion 基样式：消除 windowsvista/windows11 原生风格差异，渲染跨机器一致
    app.setStyle("Fusion")

    # 启动加载界面（splash）：冷启动 1~3s 的等待变成可感知的进度
    from .ui.splash import SplashScreen
    splash = SplashScreen(app_icon_path=_app_icon_path())
    splash.show()
    app.processEvents()

    # 列出可用设备配置
    profiles = list_profiles()
    if not profiles:
        splash.close()
        QMessageBox.critical(None, "错误", "未找到任何设备配置文件。\n请将 .yaml 放入 profiles/ 目录")
        sys.exit(1)

    # 默认加载真机联调配置；命令行显式路径仍具有最高优先级
    profile_path = _select_profile_path(profiles, sys.argv)

    try:
        profile = load_profile(profile_path)
    except Exception as e:
        splash.close()
        QMessageBox.critical(None, "配置加载失败", f"无法加载设备配置:\n{e}")
        sys.exit(1)
    splash.advance(1)

    # 用户显式切换过的主题优先于 profile 默认值（theme_explicit 用于区分
    # 「从未设置」与「用户选了 dark」，否则默认 dark 会覆盖 profile 的 solar）
    from .core.settings import AppSettings
    _settings = AppSettings()
    if _settings.theme_explicit() and _settings.theme() in ("dark", "light", "solar"):
        profile.theme = _settings.theme()

    # 应用级调色板对齐主题：补齐 QSS 未覆盖的原生绘制通道（箭头 glyph/禁用文字/原生对话框）
    from .ui.theme import build_palette
    app.setPalette(build_palette(profile.theme))
    splash.message("正在构建调试界面（仪表盘/波形/串口/调参/回放）…")
    app.processEvents()

    window = PowerMainWindow(profile)
    window.show()
    splash.advance(5)
    app.processEvents()
    splash.finish(window)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

