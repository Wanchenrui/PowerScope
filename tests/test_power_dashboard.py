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
