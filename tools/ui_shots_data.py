"""往 EventBus 直接灌 var/updated，验证空态切换与数值渲染（不依赖定时器）。"""
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
    out_dir = sys.argv[1]
    os.makedirs(out_dir, exist_ok=True)

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    from power_scope.config.device_profile import load_profile
    from power_scope.core.event_bus import EventBus, VarUpdatedEvent
    from power_scope.ui.power_main_window import PowerMainWindow

    profile = load_profile(os.path.join(ROOT, "power_scope", "profiles", "ns800rt_smoke.yaml"))
    win = PowerMainWindow(profile)
    win.resize(1440, 900)
    win.show()
    QApplication.processEvents()

    # ── 灌 60 帧模拟数据 ────────────────────────────────────────
    bus = EventBus.instance()
    t = 0.0
    for i in range(60):
        t += 0.05
        for k, v in enumerate(profile.variables):
            if v.update_rate == 0:
                continue
            base = 220.0 if "volt" in v.name else (10.0 if "current" in v.name else 50.0)
            val = base * (1.0 + 0.05 * ((i % 7) - 3) / 3.0)
            bus.publish("var/updated", VarUpdatedEvent(
                name=v.name, raw_value=val, phys_value=val * v.scale + v.offset,
                unit=v.unit, timestamp=t, source="mock"))
        QApplication.processEvents()

    # 波形加通道
    names = [v.name for v in profile.variables if v.elf_symbol][:4]
    win._scope.add_channels_external(names)
    for i in range(60):
        t += 0.05
        for v in profile.variables:
            if v.elf_symbol and v.name in names:
                bus.publish("var/updated", VarUpdatedEvent(
                    name=v.name, raw_value=220.0, phys_value=220.0 * v.scale,
                    unit=v.unit, timestamp=t, source="mock"))
        QApplication.processEvents()

    # 串口日志：直接塞几帧（新实现是表格模型，行经合并冲刷后落库）
    sv = win._serial_view
    for _ in range(6):
        sv._on_data_received(bytes.fromhex("A55A0107000000003C00") + b"STM32G474")
        sv._on_data_sent(bytes.fromhex("A55A0107000100"))
        sv._on_data_received(bytes.fromhex("A55A010C0001000039"))
        sv._flush_display()
        QApplication.processEvents()

    tabs = [win._tabs.tabText(i) for i in range(win._tabs.count())]
    for i, name in enumerate(tabs):
        win._tabs.setCurrentIndex(i)
        QApplication.processEvents()
        shot(win._tabs.currentWidget(), os.path.join(out_dir, f"data_{i:02d}_{name}.png"))
    shot(win, os.path.join(out_dir, "data_window.png"))
    print("\n".join(sorted(os.listdir(out_dir))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
