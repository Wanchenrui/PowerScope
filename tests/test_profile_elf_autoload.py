"""profile 指定 ELF 的非交互自动加载。"""
from power_scope.config.device_profile import load_profile
from power_scope.core.event_bus import EventBus
from power_scope.ui.variable_inspector_view import VariableInspectorView
from tests.conftest import pump_events


def test_load_profile_elf_updates_inspector_and_publishes(qapp):
    profile = load_profile("power_scope/profiles/ns800rt_smoke.yaml")
    view = VariableInspectorView(profile)
    events = []
    EventBus.instance().subscribe("elf/loaded", events.append)

    assert view.load_elf(profile.elf_file, show_error=False) is True
    pump_events()

    assert view._elf_parser is not None
    assert len(view._all_variables) >= 150
    assert events and events[-1].path == profile.elf_file
    view.close()


def test_missing_profile_elf_fails_without_modal_dialog(qapp):
    view = VariableInspectorView()
    assert view.load_elf("Z:/missing/firmware.elf", show_error=False) is False
    assert view._elf_parser is None
    view.close()
