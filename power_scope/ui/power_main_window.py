"""C01 inverter integration layered on the existing PowerScope window."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QFileDialog, QLabel, QMessageBox

from ..config.device_profile import VarBinding
from ..core.msg_service import MsgService, MsgTelemetryPoller
from .main_window import MainWindow
from .msg_command_view import MsgCommandView
from .power_dashboard_view import PowerDashboardView
from .serial_upgrade_view import SerialUpgradeView


CURRENT_FIRMWARE_ELF = (
    "D:/codexworkspace/C01/testproject5039/"
    "C01_2in1_20260821_ongridStable/Debug/"
    "C01_2in1_20260821_ongridStable.elf"
)
CURRENT_FIRMWARE_ELF_NAME = "C01_2in1_20260821_ongridStable.elf"


def _find_current_firmware_elf() -> str:
    if hasattr(sys, "_MEIPASS"):
        bundled = os.path.join(
            sys._MEIPASS, "firmware", CURRENT_FIRMWARE_ELF_NAME)
        if os.path.exists(bundled):
            return bundled
    return CURRENT_FIRMWARE_ELF if os.path.exists(CURRENT_FIRMWARE_ELF) else ""


class PowerMainWindow(MainWindow):
    """Adds MSG, temporary upgrade, and the fixed C01 dashboard."""

    def __init__(self, profile):
        self._prepare_profile(profile)
        super().__init__(profile)

        self._msg_service = MsgService(session=self._session, parent=self)
        self._msg_poller = MsgTelemetryPoller(self._msg_service, parent=self)
        self._msg_view = MsgCommandView(self._msg_service)
        self._upgrade_view = SerialUpgradeView(self._session)
        self._install_power_views()
        self._msg_latency_label = QLabel("MSG P99: --")
        self.statusBar().addPermanentWidget(self._msg_latency_label)
        from ..core.event_bus import EventBus
        EventBus.instance().subscribe("msg/latency", self._on_msg_latency)
        self._upgrade_view.start_requested.connect(self._begin_upgrade)
        self._upgrade_view.finished.connect(self._on_upgrade_finished)

        connected = self._session.is_connected
        self._dashboard.set_connected(connected)
        self._msg_view.set_connected(connected)
        self._upgrade_view.set_connected(connected)
        if profile.elf_file and os.path.exists(profile.elf_file):
            self._msg_view.load_elf(profile.elf_file)

    @staticmethod
    def _prepare_profile(profile):
        firmware_elf = _find_current_firmware_elf()
        if firmware_elf:
            profile.elf_file = firmware_elf

        definitions = (
            # Temperatures are the three debug-stream variables requested by
            # the dashboard.  All other dashboard values come from MSG.
            ("temperature_1", "g_adObjF.temp", "温度 1", "℃", 200),
            ("temperature_2", "g_adObjF.temp2", "温度 2", "℃", 200),
            ("temperature_3", "g_adObjF.temp3", "温度 3", "℃", 200),
            ("pv_voltage", "", "PV 电压", "V", 0),
            ("pv_current_a", "", "PV A 电流", "A", 0),
            ("pv_current_b", "", "PV B 电流", "A", 0),
            ("grid_voltage", "", "电网电压", "V", 0),
            ("grid_current", "", "电网电流", "A", 0),
            ("grid_frequency", "", "电网频率", "Hz", 0),
            ("active_power", "", "有功功率", "W", 0),
            ("reactive_power", "", "无功功率", "var", 0),
            ("power_factor", "", "功率因数", "", 0),
            ("fsm_main_state", "", "主状态机", "", 0),
            ("fsm_sub_state", "", "子状态机", "", 0),
            ("run_mode", "", "运行模式", "", 0),
            ("command_state", "", "指令状态", "", 0),
            ("inverter_state", "", "逆变器状态", "", 0),
        )
        existing = {variable.name for variable in profile.variables}
        for name, symbol, display, unit, update_rate in definitions:
            if name not in existing:
                profile.variables.append(VarBinding(
                    name=name,
                    elf_symbol=symbol,
                    display_name=display,
                    unit=unit,
                    update_rate=update_rate,
                ))
                existing.add(name)
        for index in range(10):
            name = f"alarm_group_{index}"
            if name not in existing:
                profile.variables.append(VarBinding(
                    name=name,
                    elf_symbol="",
                    display_name=f"告警组 {index}",
                    update_rate=0,
                ))
                existing.add(name)

    def _install_power_views(self):
        from ..core.event_bus import EventBus

        old_dashboard = self._dashboard
        old_index = self._tabs.indexOf(old_dashboard)
        try:
            EventBus.instance().unsubscribe("var/updated", old_dashboard._on_var_updated)
        except Exception:
            pass
        self._tabs.removeTab(old_index)
        old_dashboard.deleteLater()

        self._dashboard = PowerDashboardView(self._profile)
        self._dashboard.control_requested.connect(self._send_dashboard_control)
        self._dashboard.snapshot_requested.connect(self._export_snapshot)
        self._tabs.insertTab(old_index, self._dashboard, "仪表盘")
        self._tabs.setCurrentIndex(old_index)

        msg_index = self._tabs.addTab(self._msg_view, "MSG命令")
        upgrade_index = self._tabs.addTab(self._upgrade_view, "串口升级")
        self._nav_bar.set_glyph(msg_index, "⌁")
        self._nav_bar.set_glyph(upgrade_index, "⇧")

    def _on_msg_latency(self, stats):
        self._msg_latency_label.setText(
            f"MSG P99: {stats['p99_ms']:.1f} ms | "
            f"N={stats['sample_count']} | 超时={stats['timeout_count']}")

    def _on_connection_state(self, event):
        super()._on_connection_state(event)
        msg_view = getattr(self, "_msg_view", None)
        if msg_view is None:
            return
        serial_connected = event.state == "connected" and event.transport_type == "serial"
        self._dashboard.set_connected(serial_connected)
        self._msg_view.set_connected(serial_connected)
        self._upgrade_view.set_connected(serial_connected)
        if serial_connected and not self._upgrade_view.active:
            self._msg_service.reset_latency_stats()
            self._msg_latency_label.setText("MSG P99: 采集中")
            self._msg_poller.start()
        elif event.state in ("disconnected", "error"):
            self._msg_poller.stop()
            self._msg_service.clear_pending()

    def _on_elf_loaded(self, event):
        super()._on_elf_loaded(event)
        msg_view = getattr(self, "_msg_view", None)
        if msg_view is not None:
            msg_view.load_elf(event.path)

    def _send_dashboard_control(self, command: int, words, label: str):
        if not self._session.is_connected or self._session._transport_type() != "serial":
            self._info("提示", f"请先连接真实串口后再执行：{label}")
            return

        def on_response(response):
            if response.get("ok"):
                self._log_status(f"✓ {label} MSG 指令已确认")
            else:
                self._log_status(
                    f"✗ {label} MSG 指令失败：{response.get('kind', 'unknown')}")

        try:
            self._msg_service.request_write(command, words, on_response)
            self._log_status(
                f"→ 已发送 {label}: 0x{command:04X} / "
                + " ".join(f"0x{word:04X}" for word in words))
        except Exception as exc:
            QMessageBox.warning(self, "MSG 指令发送失败", str(exc))

    def _snapshot_payload(self) -> dict:
        values = self._dashboard.snapshot_values()
        return {
            "captured_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "device_profile": self._profile.name,
            "connection": {
                "state": self._session.state,
                "info": self._session.state_info,
            },
            "values": values,
            "active_alarms": self._dashboard.active_alarm_names(),
            "msg_latency": self._msg_service.latency_stats(),
            "last_wave_recorder": (
                self._last_wave_capture.get("diagnostics", {})
                if self._last_wave_capture else {}),
            "last_wave_live": dict(self._last_wave_live_diagnostics),
        }

    def _export_snapshot(self):
        default_name = f"power_snapshot_{datetime.now():%Y%m%d_%H%M%S}.json"
        path, _ = QFileDialog.getSaveFileName(
            self, "导出状态捕获快照", default_name, "JSON 文件 (*.json)")
        if not path:
            return
        if not path.lower().endswith(".json"):
            path += ".json"
        try:
            with open(path, "w", encoding="utf-8") as stream:
                json.dump(self._snapshot_payload(), stream, ensure_ascii=False, indent=2)
            self._log_status(f"✓ 状态快照已导出：{path}")
        except Exception as exc:
            QMessageBox.warning(self, "快照导出失败", str(exc))

    def _begin_upgrade(self, path: str):
        if not self._session.is_connected or self._session._transport_type() != "serial":
            self._info("提示", "请先连接真实串口")
            return
        self._msg_poller.stop()
        self._msg_service.clear_pending()
        self._stop_streaming()
        self._debug.clear_pending()
        self._log_status("→ 已停止 MSG 轮询和调试采样，准备进入串口升级")

        def begin_after_uart_quiet():
            try:
                self._upgrade_view.begin(path)
            except Exception as exc:
                QMessageBox.warning(self, "无法开始升级", str(exc))

        QTimer.singleShot(250, begin_after_uart_quiet)

    def _on_upgrade_finished(self, ok: bool, message: str):
        if not ok:
            self._log_status(f"✗ 串口升级失败：{message}")
            return
        self._log_status("✓ 串口升级成功，等待设备复位后恢复监控")

        def resume_monitoring():
            if not self._session.is_connected:
                return
            self._msg_poller.start()
            if self._symbols:
                self._start_streaming()

        QTimer.singleShot(3_000, resume_monitoring)

    def _cleanup(self):
        try:
            from ..core.event_bus import EventBus
            EventBus.instance().unsubscribe("msg/latency", self._on_msg_latency)
        except Exception:
            pass
        poller = getattr(self, "_msg_poller", None)
        if poller is not None:
            poller.stop()
        service = getattr(self, "_msg_service", None)
        if service is not None:
            service.clear_pending()
        dashboard = getattr(self, "_dashboard", None)
        if dashboard is not None and hasattr(dashboard, "cleanup"):
            dashboard.cleanup()
        super()._cleanup()
