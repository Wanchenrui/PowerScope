"""UI 截图回归工具 — 三主题 × 关键页面，输出 PNG。

用法:
    python tools/ui_shots.py <out_dir> [profile_yaml]

说明:
    offscreen 平台 + QT_QPA_FONTDIR=C:\\Windows\\Fonts 保证 CJK 正常渲染。
    每个 tab 截一张，另附整窗一张。无显示器的 CI 环境同样可用。
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
os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.fonts=false")

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def shot(widget, path):
    widget.repaint()
    QApplication.processEvents()
    pix = widget.grab()
    pix.save(path)
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
    from power_scope.ui.theme import THEMES

    profile = load_profile(profile_path)
    win = PowerMainWindow(profile)
    win.resize(1440, 900)
    win.show()
    QApplication.processEvents()

    tabs = [win._tabs.tabText(i) for i in range(win._tabs.count())]

    # 整窗（当前 profile 主题）
    shot(win, os.path.join(out_dir, f"window_{profile.theme}.png"))

    for theme in THEMES:
        win._on_theme_change(theme)
        QApplication.processEvents()
        shot(win, os.path.join(out_dir, f"window_{theme}.png"))
        for i, name in enumerate(tabs):
            win._tabs.setCurrentIndex(i)
            QApplication.processEvents()
            shot(win._tabs.currentWidget(),
                os.path.join(out_dir, f"{theme}_{i:02d}_{name}.png"))

    # 回到 profile 默认主题
    win._on_theme_change(profile.theme)
    print("\n".join(sorted(os.listdir(out_dir))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
