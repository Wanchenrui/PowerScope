from types import SimpleNamespace

from power_scope.ui.power_dashboard_view import PowerDashboardView


def test_dashboard_lists_each_active_alarm_and_unknown_bits(qapp):
    dashboard = PowerDashboardView()
    dashboard._on_var_updated(SimpleNamespace(
        name="alarm_group_2", raw_value=0b101, phys_value=0b101))
    dashboard._on_var_updated(SimpleNamespace(
        name="alarm_group_9", raw_value=1, phys_value=1))

    assert dashboard.active_alarm_names() == [
        "电网掉电",
        "电网过压",
        "未知告警（组 9，位 0）",
    ]
    assert dashboard._alarm_state.text() == "存在告警（3）"
    dashboard.cleanup()


def test_dashboard_displays_named_temperature_samples(qapp):
    dashboard = PowerDashboardView()
    readings = {
        "mos_temperature": (45.1, "45.1"),
        "pv1_terminal_temperature": (37.2, "37.2"),
        "pv2_terminal_temperature": (38.3, "38.3"),
        "mcu_junction_temperature": (52.4, "52.4"),
    }
    for name, (value, text) in readings.items():
        dashboard._on_var_updated(SimpleNamespace(
            name=name, raw_value=value, phys_value=value))
        assert dashboard._value_labels[name].text() == text

    dashboard._on_var_updated(SimpleNamespace(
        name="mcu_junction_temperature", raw_value=float("nan"),
        phys_value=float("nan")))
    assert dashboard._value_labels["mcu_junction_temperature"].text() == "---"
    assert dashboard.snapshot_values()["mcu_junction_temperature"] is None
    dashboard.cleanup()
