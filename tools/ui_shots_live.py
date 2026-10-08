"""UI 截图回归工具（带数据态）— 连接模拟设备后截关键页面。

与 ui_shots.py 的区别：本脚本会真的连上 mock transport、发几帧调试命令、
往波形里加通道，从而截到「有数据」状态下的界面，用于验证空态切换、
数值显示、日志分色等只在有数据时才可见的部分。

用法:
    python tools/ui_shots_live.py <out_dir> [profile_yaml]
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", "C:\\Windows\\Fonts")

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def shot(widget, path):
    widget.repaint()
    QApplication.processEvents()
    widget.grab().save(path)
    return path


def main():
    out_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "docs", "ui-review")
    profile_path = (sys.argv[2] if len(sys.argv) > 2
                    else os.path.join(ROOT, "power_scope", "profiles", "ns800rt_smoke.yaml"))
    os.makedirs(out_dir, exist_ok=True)

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    from power_scope.config.device_profile import load_profile
    from power_scope.ui.power_main_window import PowerMainWindow

    profile = load_profile(profile_path)
    win = PowerMainWindow(profile)
    win.resize(1440, 900)
    win.show()
    QApplication.processEvents()

    # ── 1) 连上模拟设备，让仪表盘/状态栏有数据 ──────────────────
    win._serial_view._sim_check.setChecked(True)
    win._session.connect_mock()
    for _ in range(40):                     # 跑够模拟定时器几个周期
        QApplication.processEvents()
        QTimer.singleShot(0, lambda: None)
    QApplication.processEvents()

    # ── 2) 发几帧调试命令，让串口日志有内容 ────────────────────
    for label, cmd in win._serial_view.ns800rt_quick_commands():
        win._serial_view._send_quick(cmd)
        QApplication.processEvents()

    # ── 3) 往波形里加通道 ──────────────────────────────────────
    names = [v.name for v in profile.variables if v.elf_symbol][:4]
    win._scope.add_channels_external(names)
    for _ in range(10):
        QApplication.processEvents()

    tabs = [win._tabs.tabText(i) for i in range(win._tabs.count())]
    for i, name in enumerate(tabs):
        win._tabs.setCurrentIndex(i)
        QApplication.processEvents()
        shot(win._tabs.currentWidget(),
             os.path.join(out_dir, f"live_{i:02d}_{name}.png"))
    shot(win, os.path.join(out_dir, "live_window.png"))

    # ── 4) 触发一次 Toast，验证语义底色 + 左色条 + 淡入 ─────────
    from power_scope.ui.widgets.toast import Toast
    Toast.show_message(win, "✗ 串口连接中断: COM4 — 重新接入后将自动重连", "error")
    Toast.show_message(win, "⚠ 安全护栏限幅: Ki=120.0->80.0", "warning")
    Toast.show_message(win, "✓ 已连接 (COM4 @ 115200) — 设备: NS800RT", "success")
    QApplication.processEvents()
    shot(win, os.path.join(out_dir, "live_toast.png"))

    print("\n".join(sorted(os.listdir(out_dir))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
