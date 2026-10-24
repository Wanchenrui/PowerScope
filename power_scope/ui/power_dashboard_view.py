"""Dedicated inverter dashboard for live MSG/debug telemetry."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .theme import ui_color
from .widgets.gauge import LedIndicator
from .widgets.icons import icon
from .widgets.primitives import PageHeader, StatusBadge, repolish


ALARM_BITS = {
    (0, 0): "PV A 过压",
    (0, 1): "PV B 过压",
    (1, 0): "PV B 反接",
    (1, 1): "PV B 过流",
    (2, 0): "电网掉电",
    (2, 1): "电网欠压",
    (2, 2): "电网过压",
    (2, 3): "电网欠频",
    (2, 4): "电网过频",
    (2, 5): "直流注入过大",
    (2, 6): "绝缘阻抗异常",
    (3, 0): "辅助电源异常",
    (3, 1): "EEPROM 异常",
    (3, 2): "模拟采样异常",
    (3, 3): "硬件保护",
    (3, 5): "MOS 过温",
    (3, 7): "软硬件版本异常",
    (3, 14): "直流端子过温",
    (4, 0): "PV A 反接",
    (4, 1): "PV A 过流",
    (4, 2): "电网过流",
    (4, 3): "PV A 瞬时过流",
    (4, 4): "PV A 瞬时过压",
    (4, 5): "电网瞬时过流",
    (5, 0): "PV A 欠压",
    (5, 1): "PV B 欠压",
    (6, 0): "MPPT A 过流",
    (6, 1): "MPPT B 过流",
    (6, 2): "母线过压",
    (7, 0): "电网一级过压",
    (7, 1): "电网二级过压",
    (7, 2): "电网一级欠压",
    (7, 3): "电网二级欠压",
    (7, 4): "电网一级过频",
    (7, 5): "电网二级过频",
    (7, 6): "电网一级欠频",
    (7, 7): "电网二级欠频",
    (7, 8): "电网 10 分钟过压",
    (7, 9): "电网峰值过压",
    (7, 10): "电网突变",
    (7, 11): "电网频率变化率异常",
    (8, 0): "输出过流",
    (8, 2): "PV A 瞬时欠压",
    (8, 3): "PV 启动电压低",
    (8, 4): "PV 输入功率不足",
}


METRICS = {
    "pv_voltage": ("PV 电压", "V", 2),
    "pv_current_a": ("PV A 电流", "A", 2),
    "pv_current_b": ("PV B 电流", "A", 2),
    "grid_voltage": ("电网电压", "V", 1),
    "grid_current": ("电网电流", "A", 2),
    "grid_frequency": ("电网频率", "Hz", 3),
    "active_power": ("有功功率", "W", 0),
    "reactive_power": ("无功功率", "var", 0),
    "power_factor": ("功率因数", "", 3),
    "temperature_1": ("温度 1", "℃", 1),
    "temperature_2": ("温度 2", "℃", 1),
    "temperature_3": ("温度 3", "℃", 1),
}

_FLUSH_INTERVAL_MS = 33  # ~30 fps 合帧窗口，合并高频 var/updated 突发


class PowerDashboardView(QWidget):
    """Telemetry hero card, metric cards, controls, and active alarms."""

    control_requested = Signal(int, object, str)
    snapshot_requested = Signal()

    MAIN_STATES = {0: "初始化", 1: "空闲", 2: "启动", 3: "运行", 4: "关机"}
    RUN_MODES = {0: "并网模式", 1: "离网模式", 2: "开环模式"}
    INVERTER_STATES = {
        0: "等待", 1: "并网", 2: "关机", 3: "故障关机", 4: "离网", 5: "开环",
    }
    COMMAND_STATES = {0: "关机", 1: "开机"}

    def __init__(self, profile=None, parent=None):
        super().__init__(parent)
        self._profile = profile
        self._values = {}
        self._value_labels = {}
        self._state_labels = {}
        self._control_buttons = []
        self._icon_buttons = []  # (button, icon_name, color_role) for theme refresh
        self._widgets = {}  # MainWindow/theme compatibility.
        self._dirty_names = set()
        self._alarm_dirty = False
        self._alarm_names = []
        self._flush_timer = QTimer(self)
        self._flush_timer.setSingleShot(True)
        self._flush_timer.setInterval(_FLUSH_INTERVAL_MS)
        self._flush_timer.timeout.connect(self._flush_updates)
        self._build_ui()
        self.set_connected(False)
        from ..core.event_bus import EventBus
        EventBus.instance().subscribe("var/updated", self._on_var_updated)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(12)

        header = PageHeader("运行概览", "MSG 遥测 · 调试流 · 告警监测")
        self._header_badge = StatusBadge()
        self._header_badge.set_status("只读监视", "neutral")
        header.add_widget(self._header_badge)
        root.addWidget(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        column = QVBoxLayout(container)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(12)

        column.addWidget(self._hero_card())

        grid = QGridLayout()
        grid.setSpacing(12)
        grid.addWidget(self._metric_card(
            "PV 侧", ("pv_voltage", "pv_current_a", "pv_current_b")), 0, 0)
        grid.addWidget(self._metric_card(
            "电网侧", ("grid_voltage", "grid_current", "grid_frequency")), 0, 1)
        grid.addWidget(self._metric_card(
            "温度采样", ("temperature_1", "temperature_2", "temperature_3")), 0, 2)
        grid.addWidget(self._state_card(), 1, 0)
        grid.addWidget(self._control_card(), 1, 1)
        grid.addWidget(self._alarm_card(), 1, 2)
        for column_index in range(3):
            grid.setColumnStretch(column_index, 1)
        column.addLayout(grid)
        column.addStretch()

        scroll.setWidget(container)
        root.addWidget(scroll, 1)

    @staticmethod
    def _card(title: str):
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)
        title_label = QLabel(title)
        title_label.setObjectName("section_title")
        layout.addWidget(title_label)
        return card, layout

    def _hero_card(self):
        card = QFrame()
        card.setObjectName("hero_card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)

        caption = QLabel(METRICS["active_power"][0])
        caption.setObjectName("metric_caption")
        layout.addWidget(caption)

        value_row = QHBoxLayout()
        value_row.setSpacing(8)
        value = QLabel("---")
        value.setObjectName("hero_value")
        unit = QLabel(METRICS["active_power"][1])
        unit.setObjectName("unit")
        value_row.addWidget(value, 0, Qt.AlignBottom)
        value_row.addWidget(unit, 0, Qt.AlignBottom)
        value_row.addStretch(1)
        layout.addLayout(value_row)
        self._value_labels["active_power"] = value

        secondary = QGridLayout()
        secondary.setSpacing(8)
        for column, name in enumerate(("reactive_power", "power_factor")):
            metric_caption, metric_unit, _precision = METRICS[name]
            cell = QVBoxLayout()
            cell.setSpacing(2)
            cell_caption = QLabel(metric_caption)
            cell_caption.setObjectName("metric_caption")
            cell_row = QHBoxLayout()
            cell_row.setSpacing(6)
            cell_value = QLabel("---")
            cell_value.setObjectName("metric_value")
            cell_unit = QLabel(metric_unit)
            cell_unit.setObjectName("unit")
            cell_row.addWidget(cell_value, 0, Qt.AlignBottom)
            cell_row.addWidget(cell_unit, 0, Qt.AlignBottom)
            cell_row.addStretch(1)
            cell.addWidget(cell_caption)
            cell.addLayout(cell_row)
            secondary.addLayout(cell, 0, column)
            self._value_labels[name] = cell_value
        layout.addLayout(secondary)
        return card

    def _metric_card(self, title: str, names: tuple[str, ...]):
        card, layout = self._card(title)
        form = QGridLayout()
        form.setSpacing(6)
        for row, name in enumerate(names):
            caption, unit, _precision = METRICS[name]
            caption_label = QLabel(caption)
            caption_label.setObjectName("metric_caption")
            value_label = QLabel("---")
            value_label.setObjectName("metric_value")
            value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            unit_label = QLabel(unit)
            unit_label.setObjectName("unit")
            form.addWidget(caption_label, row, 0)
            form.addWidget(value_label, row, 1)
            form.addWidget(unit_label, row, 2)
            self._value_labels[name] = value_label
        form.setColumnStretch(1, 1)
        layout.addLayout(form)
        layout.addStretch()
        return card

    def _state_card(self):
        card, layout = self._card("运行状态")
        form = QGridLayout()
        form.setSpacing(6)
        rows = (
            ("fsm_main_state", "主状态机"),
            ("fsm_sub_state", "子状态机"),
            ("inverter_state", "逆变器状态"),
            ("command_state", "指令状态"),
            ("run_mode", "运行模式"),
        )
        for row, (name, label) in enumerate(rows):
            key = QLabel(label)
            key.setObjectName("dim")
            value = QLabel("---")
            value.setObjectName("state_value")
            value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            form.addWidget(key, row, 0)
            form.addWidget(value, row, 1)
            self._state_labels[name] = value
        form.setColumnStretch(1, 1)
        layout.addLayout(form)
        layout.addStretch()
        return card

    def _control_card(self):
        card, layout = self._card("设备控制")
        controls = (
            ("开机", 0x2001, 1, "btn_success", "play", "success"),
            ("关机", 0x2001, 0, "btn_danger", "stop", "danger"),
            ("并网模式", 0x2002, 0, "btn_primary", "connect", "on_primary"),
            ("离网模式", 0x2002, 1, "btn_warning", "disconnect", "warning"),
        )
        buttons = QGridLayout()
        buttons.setSpacing(8)
        for index, (label, command, value, object_name,
                    icon_name, color_role) in enumerate(controls):
            button = QPushButton(label)
            button.setObjectName(object_name)
            button.setIcon(icon(icon_name, ui_color(color_role), 18))
            button.setMinimumHeight(38)
            button.clicked.connect(
                lambda _checked=False, cmd=command, word=value, text=label:
                self.control_requested.emit(cmd, [word], text))
            buttons.addWidget(button, index // 2, index % 2)
            self._control_buttons.append(button)
            self._icon_buttons.append((button, icon_name, color_role))
        layout.addLayout(buttons)
        snapshot = QPushButton("导出状态捕获快照")
        snapshot.setIcon(icon("snapshot", ui_color("primary"), 18))
        snapshot.setMinimumHeight(38)
        snapshot.clicked.connect(self.snapshot_requested.emit)
        layout.addWidget(snapshot)
        self._icon_buttons.append((snapshot, "snapshot", "primary"))
        hint = QLabel("控制指令仅在连接真实串口且通过安全确认后可用")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch()
        return card

    def _alarm_card(self):
        card, layout = self._card("实时告警")
        status_row = QHBoxLayout()
        self._alarm_led = LedIndicator(ui_color("danger"), ui_color("success"))
        self._alarm_state = QLabel("无告警")
        alarm_font = self._alarm_state.font()
        alarm_font.setBold(True)
        self._alarm_state.setFont(alarm_font)
        self._alarm_state.setProperty("role", "ok")
        status_row.addWidget(self._alarm_led)
        status_row.addWidget(self._alarm_state)
        status_row.addStretch()
        layout.addLayout(status_row)
        self._alarm_list = QListWidget()
        self._alarm_list.setObjectName("alarm_list")
        self._alarm_list.addItem("当前无告警")
        layout.addWidget(self._alarm_list, 1)
        return card

    def set_connected(self, connected: bool):
        for button in self._control_buttons:
            button.setEnabled(bool(connected))

    def _on_var_updated(self, event):
        value = getattr(event, "phys_value", getattr(event, "raw_value", 0))
        self._values[event.name] = value
        self._dirty_names.add(event.name)
        if event.name.startswith("alarm_group_"):
            self._alarm_dirty = True
        if not self._flush_timer.isActive():
            self._flush_timer.start()

    def _flush_updates(self):
        """Coalesced refresh: apply the latest cached value per dirty name."""
        self._flush_timer.stop()
        dirty_names = self._dirty_names
        alarm_dirty = self._alarm_dirty
        self._dirty_names = set()
        self._alarm_dirty = False
        for name in dirty_names:
            if name in self._value_labels:
                _label, _unit, precision = METRICS[name]
                value = self._values.get(name)
                try:
                    text = f"{float(value):.{precision}f}"
                except (TypeError, ValueError):
                    text = str(value)
                label = self._value_labels[name]
                if label.text() != text:
                    label.setText(text)
            elif name in self._state_labels:
                text = self._format_state(name, self._values.get(name))
                label = self._state_labels[name]
                if label.text() != text:
                    label.setText(text)
        if alarm_dirty:
            self._update_alarm_display()

    def _format_state(self, name: str, value) -> str:
        try:
            number = int(value)
        except (TypeError, ValueError):
            return str(value)
        if name == "fsm_main_state":
            return f"{self.MAIN_STATES.get(number, '未知')} ({number})"
        if name == "fsm_sub_state":
            return f"{number} / 0x{number:04X}"
        if name == "inverter_state":
            return self.INVERTER_STATES.get(number, f"未知 ({number})")
        if name == "command_state":
            return self.COMMAND_STATES.get(number, f"未知 ({number})")
        if name == "run_mode":
            return self.RUN_MODES.get(number, f"未知 ({number})")
        return str(number)

    def active_alarm_names(self) -> list[str]:
        active = []
        for group in range(10):
            try:
                value = int(self._values.get(f"alarm_group_{group}", 0)) & 0xFFFF
            except (TypeError, ValueError):
                value = 0
            for bit in range(16):
                if value & (1 << bit):
                    active.append(ALARM_BITS.get(
                        (group, bit), f"未知告警（组 {group}，位 {bit}）"))
        return active

    def snapshot_values(self) -> dict:
        return dict(self._values)

    def _set_alarm_role(self, role: str):
        if self._alarm_state.property("role") != role:
            self._alarm_state.setProperty("role", role)
            repolish(self._alarm_state)

    def _update_alarm_display(self):
        alarms = self.active_alarm_names()
        if alarms == self._alarm_names:
            return
        self._alarm_names = list(alarms)
        has_alarms = bool(alarms)
        self._alarm_led.set_on(has_alarms)
        self._alarm_list.clear()
        if has_alarms:
            self._alarm_state.setText(f"存在告警（{len(alarms)}）")
            self._set_alarm_role("err")
            self._alarm_list.addItems(alarms)
        else:
            self._alarm_state.setText("无告警")
            self._set_alarm_role("ok")
            self._alarm_list.addItem("当前无告警")

    def apply_theme(self, theme_name=None):
        self._alarm_led.color_on = ui_color("danger", theme_name)
        self._alarm_led.color_off = ui_color("success", theme_name)
        self._alarm_led.update()
        self._header_badge.refresh_theme()
        for button, icon_name, color_role in self._icon_buttons:
            button.setIcon(icon(icon_name, ui_color(color_role, theme_name), 18))

    def rebuild(self):
        """The fixed inverter layout does not depend on profile dashboard widgets."""

    def cleanup(self):
        self._flush_timer.stop()
        from ..core.event_bus import EventBus
        EventBus.instance().unsubscribe("var/updated", self._on_var_updated)
