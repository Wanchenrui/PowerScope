"""Dedicated inverter dashboard for live MSG/debug telemetry."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
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

from .widgets.gauge import LedIndicator


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


class PowerDashboardView(QWidget):
    """Three functional sections: telemetry, controls, and active alarms."""

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
        self._widgets = {}  # MainWindow/theme compatibility.
        self._build_ui()
        self.set_connected(False)
        from ..core.event_bus import EventBus
        EventBus.instance().subscribe("var/updated", self._on_var_updated)

    def _build_ui(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        grid = QGridLayout(container)
        grid.setSpacing(12)

        grid.addWidget(self._metric_card(
            "PV 侧", ("pv_voltage", "pv_current_a", "pv_current_b")), 0, 0)
        grid.addWidget(self._metric_card(
            "电网侧",
            ("grid_voltage", "grid_current", "grid_frequency", "active_power",
             "reactive_power", "power_factor")), 0, 1)
        grid.addWidget(self._metric_card(
            "温度采样", ("temperature_1", "temperature_2", "temperature_3")), 0, 2)
        grid.addWidget(self._state_card(), 1, 0)
        grid.addWidget(self._control_card(), 1, 1)
        grid.addWidget(self._alarm_card(), 1, 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 2)
        grid.setColumnStretch(2, 1)
        grid.setRowStretch(0, 1)
        grid.setRowStretch(1, 1)
        scroll.setWidget(container)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(scroll)

    @staticmethod
    def _card(title: str):
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        title_label = QLabel(title)
        title_label.setObjectName("title")
        layout.addWidget(title_label)
        return card, layout

    def _metric_card(self, title: str, names: tuple[str, ...]):
        card, layout = self._card(title)
        form = QGridLayout()
        for row, name in enumerate(names):
            label, unit, _precision = METRICS[name]
            name_label = QLabel(label)
            name_label.setObjectName("dim")
            value_label = QLabel("---")
            value_label.setObjectName("value")
            value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            unit_label = QLabel(unit)
            unit_label.setObjectName("unit")
            form.addWidget(name_label, row, 0)
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
            value.setObjectName("value")
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
            ("开机", 0x2001, 1, "btn_success"),
            ("关机", 0x2001, 0, "btn_danger"),
            ("并网模式", 0x2002, 0, "btn_primary"),
            ("离网模式", 0x2002, 1, "btn_warning"),
        )
        buttons = QGridLayout()
        for index, (label, command, value, object_name) in enumerate(controls):
            button = QPushButton(label)
            button.setObjectName(object_name)
            button.setMinimumHeight(38)
            button.clicked.connect(
                lambda _checked=False, cmd=command, word=value, text=label:
                self.control_requested.emit(cmd, [word], text))
            buttons.addWidget(button, index // 2, index % 2)
            self._control_buttons.append(button)
        layout.addLayout(buttons)
        snapshot = QPushButton("导出状态捕获快照")
        snapshot.setMinimumHeight(38)
        snapshot.clicked.connect(self.snapshot_requested.emit)
        layout.addWidget(snapshot)
        layout.addStretch()
        return card

    def _alarm_card(self):
        card, layout = self._card("实时告警")
        status_row = QHBoxLayout()
        self._alarm_led = LedIndicator("#f7768e", "#9ece6a")
        self._alarm_state = QLabel("无告警")
        self._alarm_state.setStyleSheet("color:#9ece6a;font-weight:bold;")
        status_row.addWidget(self._alarm_led)
        status_row.addWidget(self._alarm_state)
        status_row.addStretch()
        layout.addLayout(status_row)
        self._alarm_list = QListWidget()
        self._alarm_list.addItem("当前无告警")
        layout.addWidget(self._alarm_list, 1)
        return card

    def set_connected(self, connected: bool):
        for button in self._control_buttons:
            button.setEnabled(bool(connected))

    def _on_var_updated(self, event):
        value = getattr(event, "phys_value", getattr(event, "raw_value", 0))
        self._values[event.name] = value
        if event.name in self._value_labels:
            _label, _unit, precision = METRICS[event.name]
            try:
                text = f"{float(value):.{precision}f}"
            except (TypeError, ValueError):
                text = str(value)
            self._value_labels[event.name].setText(text)
        elif event.name in self._state_labels:
            self._state_labels[event.name].setText(self._format_state(event.name, value))
        if event.name.startswith("alarm_group_"):
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

    def _update_alarm_display(self):
        alarms = self.active_alarm_names()
        self._alarm_led.set_on(bool(alarms))
        self._alarm_list.clear()
        if alarms:
            self._alarm_state.setText(f"存在告警（{len(alarms)}）")
            self._alarm_state.setStyleSheet("color:#f7768e;font-weight:bold;")
            self._alarm_list.addItems(alarms)
        else:
            self._alarm_state.setText("无告警")
            self._alarm_state.setStyleSheet("color:#9ece6a;font-weight:bold;")
            self._alarm_list.addItem("当前无告警")

    def rebuild(self):
        """The fixed inverter layout does not depend on profile dashboard widgets."""

    def cleanup(self):
        from ..core.event_bus import EventBus
        EventBus.instance().unsubscribe("var/updated", self._on_var_updated)
