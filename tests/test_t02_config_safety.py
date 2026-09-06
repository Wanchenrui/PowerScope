from types import SimpleNamespace

import pytest

from power_scope.config.device_profile import DeviceProfile, VarBinding
from power_scope.core.guardrails import Guardrails
from power_scope.ui.ai_tool_context import MainWindowToolContext


def profile():
    return DeviceProfile('test', 'custom', '1', variables=[
        VarBinding('inv_curr_freq_kp', 'kp', min_val=-10000, max_val=0),
        VarBinding('run_state', 'state'),
    ])


def test_negative_range_round_trip(tmp_path):
    path = tmp_path / 'profile.yaml'
    profile().to_yaml(path)
    var = DeviceProfile.from_yaml(path).find_var('inv_curr_freq_kp')
    assert (var.min_val, var.max_val) == (-10000, 0)


def test_legacy_range_keys(tmp_path):
    path = tmp_path / 'legacy.yaml'
    path.write_text('variables:\n- name: kp\n  min_val: -10000\n  max_val: 0\n')
    var = DeviceProfile.from_yaml(path).find_var('kp')
    assert (var.min_val, var.max_val) == (-10000, 0)


@pytest.mark.parametrize('name,value', [('unknown', 1), ('run_state', float('nan')),
    ('run_state', float('inf')), ('run_state', -float('inf')), ('run_state', 255)])
def test_invalid_commands_rejected_without_rewriting(name, value):
    result = Guardrails(profile()).validate(name, value)
    assert result.allowed is False
    if value == value:
        assert result.clamped_value == value


@pytest.mark.parametrize('guard', [None, SimpleNamespace(validate=lambda *args: 1/0)])
def test_validator_unavailable_rejects(guard):
    ctx = object.__new__(MainWindowToolContext)
    ctx.mw = SimpleNamespace(_guardrails=guard)
    assert ctx.validate_param('run_state', 1)[0] is False


@pytest.mark.parametrize('device_type', ['storage', 'custom', 'hybrid'])
def test_non_c01_profile_unchanged(device_type):
    from power_scope.ui.power_main_window import PowerMainWindow
    p = profile()
    p.device_type = device_type
    PowerMainWindow._prepare_profile(p)
    assert [v.name for v in p.variables] == ['inv_curr_freq_kp', 'run_state']


def test_user_elf_preserved(monkeypatch):
    from power_scope.ui import power_main_window as module
    p = profile()
    p.device_type = 'microinverter'
    p.adapter = 'c01'
    p.elf_file = 'user.elf'
    module.PowerMainWindow._prepare_profile(p)
    assert p.elf_file == 'user.elf'


@pytest.mark.parametrize('device_type,adapter', [('storage', ''), ('custom', ''), ('microinverter', '')])
def test_generic_windows_have_no_c01_services(qapp, device_type, adapter):
    from power_scope.ui.power_main_window import PowerMainWindow
    p = profile()
    p.device_type, p.adapter = device_type, adapter
    window = PowerMainWindow(p)
    try:
        assert not hasattr(window, '_msg_poller')
        assert not hasattr(window, '_msg_view')
        assert not hasattr(window, '_upgrade_view')
    finally:
        window._cleanup()
        window.deleteLater()


def test_real_control_paths_denied_and_reading_preserved(qapp, monkeypatch):
    from unittest.mock import Mock
    from power_scope.ui.power_main_window import PowerMainWindow
    p = profile()
    p.device_type, p.adapter = 'microinverter', 'c01'
    w = PowerMainWindow(p)
    try:
        # No hardware needed: a transport spy makes any accidental send observable.
        tx = Mock(side_effect=len)
        w._session._state = "connected"
        w._session._transport = SimpleNamespace(write=tx, is_open=True)
        monkeypatch.setattr(w._session, '_transport_type', lambda: 'serial')
        w._var_view.set_connected(True)
        w._tune_view.set_connected(True)
        w._serial_view.set_connected(True)
        w._var_view._on_write_var()
        w._var_view._on_write_verify()
        w._tune_view._on_apply()
        w._tune_view._write_params_verified({'Kp': 1})
        w._tune_view._launch_active_step(None, None, 0, 0, 1, 1)
        w._serial_view._on_send()
        w._msg_view._send_write()
        w._send_dashboard_control(1, [1], 'start')
        w._begin_upgrade('firmware.bin')
        w._on_reset()
        w._on_param_write('run_state', 255)
        assert w._write_var_to_device(p.find_var('run_state'), 1) is False
        assert tx.call_count == 0
        # A known legacy read capability is required after T04 negotiation.
        from power_scope.core.contracts import Capabilities
        w._session.capabilities = Capabilities(
            supported_commands=frozenset((1, 7)), read_memory_bytes=181)
        w._debug.read_memory(0x20000000, 4)
        assert tx.call_count == 1
    finally:
        w._session._transport = None
        w._cleanup()
        w.deleteLater()


def test_profile_change_invalidates_symbols_and_values(qapp):
    from power_scope.ui.main_window import MainWindow
    w = MainWindow(profile())
    try:
        old_safety = w._safety
        w._debug.register_sample_layout(0, [])
        w._symbols['old'] = object()
        w._ai_ctx._cache['old'] = 123
        w._stream.monitor_channels['old'] = object()
        new = profile()
        new.tuning = {'loops': [{'id': 'new', 'label': 'new'}]}
        w.apply_profile(new)
        assert w._safety is not old_safety
        assert not w._debug.has_layout(0)
        assert not w._symbols
        assert not w._ai_ctx._cache
        assert not w._stream.monitor_channels
        assert w._debug._profile is new
        assert w._tune_view._guardrails._profile is new
        assert w._tune_view._loop_defs == new.tuning['loops']
        other = profile()
        other.device_type = 'storage'
        with pytest.raises(ValueError, match='跨设备'):
            w.apply_profile(other)
        assert w._profile is new
    finally:
        w._cleanup()
        w.deleteLater()


def test_ai_denial_never_appears_as_success(qapp):
    from power_scope.ui.ai_copilot_view import AICopilotView
    view = AICopilotView()
    messages = []
    view.status.connect(messages.append)
    view._ctx = SimpleNamespace(apply_pending=lambda act: '拒绝写入: 没有权限')
    view._confirm(SimpleNamespace(name='run_state'))
    assert messages == ['拒绝写入: 没有权限']
    view.deleteLater()


@pytest.mark.parametrize('trigger', ['revert', 'timeout', 'write_callback'])
def test_safety_rechecks_permission_after_transport_changes(qapp, trigger):
    from power_scope.core.safety_controller import SafetyController, AnomalyCriteria
    from power_scope.core.debug_service import SampleChannel
    from unittest.mock import Mock
    permitted = [True]
    saved_callbacks = []
    debug = SimpleNamespace(
        write_and_verify=Mock(side_effect=lambda *args, callback: saved_callbacks.append(callback)),
        device_control=Mock())
    channel = SampleChannel('run_state', 0x20000000, 4, 'float')
    clock = [0.0]
    ctrl = SafetyController(debug, Guardrails(profile()),
        AnomalyCriteria(limits={'temperature': (0, 100)}, comms_timeout_s=1),
        clock=lambda: clock[0], control_check=lambda: '' if permitted[0] else '控制受限')
    messages = []
    ctrl.event.connect(lambda level, message: messages.append(message))
    try:
        assert ctrl.begin([('run_state', channel, 1, 0)])
        if trigger != 'write_callback':
            saved_callbacks.pop()(True, b'')
            assert ctrl.state == ctrl.MONITORING
        permitted[0] = False  # Mock session is replaced by an unverified real device.
        if trigger == 'revert':
            ctrl.revert()
        elif trigger == 'timeout':
            clock[0] = 2
            ctrl.on_tick()
        else:
            saved_callbacks.pop()(False, b'')
        assert debug.write_and_verify.call_count == 1
        assert debug.device_control.call_count == 0
        assert ctrl.state == 'CONTROL_BLOCKED'
        assert '设备状态未确认' in messages[-1]
        assert '已停机' not in messages[-1] and '已回退' not in messages[-1]
    finally:
        ctrl.close()
