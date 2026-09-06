"""Independent G0 review counterexamples; production code remains owner-managed."""
from types import SimpleNamespace

from power_scope.config.device_profile import DeviceProfile, VarBinding
from power_scope.core.guardrails import Guardrails
from power_scope.ui.ai_tool_context import MainWindowToolContext


def test_review_small_out_of_range_request_is_rejected_not_clamped():
    profile = DeviceProfile("review", "custom", "1", variables=[
        VarBinding("negative_gain", "cfg.kp", min_val=-10, max_val=-1)])
    result = Guardrails(profile).validate("negative_gain", -0.99)
    assert result.allowed is False
    assert result.original_value == result.clamped_value == -0.99


def test_review_pending_ai_proposal_revalidates_original_value_at_apply():
    # Approval of a displayed/clamped proposal cannot preserve old permissions.
    profile = DeviceProfile("review", "custom", "1", variables=[
        VarBinding("gain", "cfg.kp", min_val=0, max_val=1)])
    writes = []
    context = object.__new__(MainWindowToolContext)
    context.mw = SimpleNamespace(
        _profile=profile, _guardrails=Guardrails(profile),
        _write_var_to_device=lambda *args: writes.append(args) or True)
    action = SimpleNamespace(kind="param_write", name="gain", value=2, clamped=1)
    outcome = context.apply_pending(action)
    assert writes == []
    assert "拒绝" in outcome


def test_review_safety_late_callback_cannot_write_after_permission_revoked(qapp):
    from power_scope.core.safety_controller import SafetyController
    profile = DeviceProfile("review", "custom", "1", variables=[
        VarBinding("gain", "cfg.kp", min_val=0, max_val=10)])
    allowed = [True]
    callbacks, sends, events = [], [], []
    def write(address, data, length, callback):
        sends.append(address)
        callbacks.append(callback)
    service = SimpleNamespace(write_and_verify=write,
        device_control=lambda state: sends.append("stop"))
    safety = SafetyController(service, Guardrails(profile),
        control_check=lambda: "" if allowed[0] else "review revoked")
    safety.event.connect(lambda level, message: events.append(message))
    channel = SimpleNamespace(address=0x20000000, type_name="float", size=4)
    try:
        assert safety.begin([("gain", channel, 2, 1), ("gain", channel, 3, 1)])
        assert sends == [0x20000000]
        allowed[0] = False
        callbacks[0](False, b"")  # failure normally requests rollback
        assert sends == [0x20000000]
        assert safety.state == "CONTROL_BLOCKED"
        assert any("未确认" in event for event in events)
        assert not any("已停机" in event or "已回退" in event for event in events)
    finally:
        safety.close()


def test_review_safety_without_capability_check_never_sends(qapp):
    from power_scope.core.safety_controller import SafetyController
    sends = []
    service = SimpleNamespace(read_memory=lambda *a, **k: sends.append("read"),
        write_and_verify=lambda *a, **k: sends.append("write"))
    safety = SafetyController(service, Guardrails())
    try:
        assert not safety.begin([("gain", SimpleNamespace(), 1)])
        assert sends == []
    finally:
        safety.close()
