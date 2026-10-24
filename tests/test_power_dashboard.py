from types import SimpleNamespace

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QLabel, QListWidget

from power_scope.ui.power_dashboard_view import METRICS, PowerDashboardView


def _event(name, value):
    return SimpleNamespace(name=name, raw_value=value, phys_value=value)


def test_dashboard_lists_each_active_alarm_and_unknown_bits(qapp):
    dashboard = PowerDashboardView()
    dashboard._on_var_updated(_event("alarm_group_2", 0b101))
    dashboard._on_var_updated(_event("alarm_group_9", 1))
    dashboard._flush_updates()

    assert dashboard.active_alarm_names() == [
        "电网掉电",
        "电网过压",
        "未知告警（组 9，位 0）",
    ]
    assert dashboard._alarm_state.text() == "存在告警（3）"
    assert dashboard._alarm_list.count() == 3
    dashboard.cleanup()


def _count_list_rebuilds(monkeypatch):
    """Patch QListWidget.clear/addItems to count rebuilds while keeping real behavior."""
    clears = []
    add_batches = []
    original_clear = QListWidget.clear
    original_add_items = QListWidget.addItems

    def counting_clear(self):
        clears.append(1)
        original_clear(self)

    def counting_add_items(self, items):
        add_batches.append(list(items))
        original_add_items(self, items)

    monkeypatch.setattr(QListWidget, "clear", counting_clear)
    monkeypatch.setattr(QListWidget, "addItems", counting_add_items)
    return clears, add_batches


def test_alarm_batch_rebuilds_list_once(qapp, monkeypatch):
    dashboard = PowerDashboardView()
    clears, add_batches = _count_list_rebuilds(monkeypatch)

    dashboard._on_var_updated(_event("alarm_group_0", 0b1))
    dashboard._on_var_updated(_event("alarm_group_2", 0b101))
    dashboard._on_var_updated(_event("alarm_group_9", 0b1))
    dashboard._flush_updates()

    assert len(clears) == 1
    assert add_batches == [[
        "PV A 过压",
        "电网掉电",
        "电网过压",
        "未知告警（组 9，位 0）",
    ]]
    dashboard.cleanup()


def test_duplicate_alarm_update_does_not_rebuild_list(qapp, monkeypatch):
    dashboard = PowerDashboardView()
    clears, add_batches = _count_list_rebuilds(monkeypatch)

    dashboard._on_var_updated(_event("alarm_group_2", 0b101))
    dashboard._flush_updates()
    assert len(clears) == 1

    dashboard._on_var_updated(_event("alarm_group_2", 0b101))
    dashboard._flush_updates()
    assert len(clears) == 1
    assert len(add_batches) == 1

    dashboard._on_var_updated(_event("alarm_group_2", 0))
    dashboard._flush_updates()
    assert len(clears) == 2
    assert dashboard._alarm_state.text() == "无告警"
    assert dashboard._alarm_list.count() == 1
    assert dashboard._alarm_list.item(0).text() == "当前无告警"
    dashboard.cleanup()


def test_flush_updates_metric_and_state_labels(qapp):
    dashboard = PowerDashboardView()
    assert set(METRICS) == set(dashboard._value_labels)
    dashboard._on_var_updated(_event("active_power", 1234.0))
    dashboard._on_var_updated(_event("grid_frequency", 50.012))
    dashboard._on_var_updated(_event("fsm_main_state", 3))
    dashboard._on_var_updated(_event("inverter_state", 1))
    dashboard._flush_updates()

    assert dashboard._value_labels["active_power"].text() == "1234"
    assert dashboard._value_labels["grid_frequency"].text() == "50.012"
    assert dashboard._state_labels["fsm_main_state"].text() == "运行 (3)"
    assert dashboard._state_labels["inverter_state"].text() == "并网"
    assert dashboard.snapshot_values()["active_power"] == 1234.0
    dashboard.cleanup()


def test_flush_skips_set_text_when_unchanged(qapp, monkeypatch):
    dashboard = PowerDashboardView()
    calls = []
    original_set_text = QLabel.setText

    def counting_set_text(self, text):
        calls.append(text)
        original_set_text(self, text)

    monkeypatch.setattr(QLabel, "setText", counting_set_text)
    dashboard._on_var_updated(_event("active_power", 100.0))
    dashboard._flush_updates()
    assert calls == ["100"]

    dashboard._on_var_updated(_event("active_power", 100.0))
    dashboard._flush_updates()
    assert calls == ["100"]
    dashboard.cleanup()


def test_var_updates_flush_via_single_shot_timer(qapp):
    dashboard = PowerDashboardView()
    dashboard._on_var_updated(_event("active_power", 42.0))
    assert dashboard._flush_timer.isActive()

    loop = QEventLoop()
    watchdog = QTimer()
    watchdog.setSingleShot(True)
    watchdog.timeout.connect(loop.quit)
    watchdog.start(1000)
    dashboard._flush_timer.timeout.connect(loop.quit)
    loop.exec()
    watchdog.stop()

    assert dashboard._value_labels["active_power"].text() == "42"
    assert not dashboard._flush_timer.isActive()
    dashboard.cleanup()


def test_cleanup_stops_flush_timer_and_unsubscribes(qapp):
    from power_scope.core.event_bus import EventBus

    dashboard = PowerDashboardView()
    bus = EventBus.instance()
    assert dashboard._on_var_updated in bus._subscribers["var/updated"]
    dashboard._on_var_updated(_event("active_power", 1.0))
    assert dashboard._flush_timer.isActive()

    dashboard.cleanup()

    assert not dashboard._flush_timer.isActive()
    assert dashboard._on_var_updated not in bus._subscribers["var/updated"]
