"""test_ai_copilot.py — AI 副驾驶面板 + ToolContext 桥接（GUI 轻量）"""
import pytest
from power_scope.llm.tools import ToolExecutor, PendingAction


def test_copilot_view_constructs(qapp):
    from power_scope.ui.ai_copilot_view import AICopilotView
    v = AICopilotView()
    assert v._engine is not None
    class Ctx:
        def read_variable(self, n): return None
        def waveform_stats(self, n): return {}
        def fault_codes(self): return []
        def current_metrics(self): return {"overshoot": 18.0}
        def validate_param(self, n, v): return (True, v, "OK")
    v.set_tool_context(Ctx())
    assert v._executor is not None
    v.deleteLater()


def test_copilot_pending_confirm_flow(qapp):
    """确认 pending 写操作会调用 ctx.apply_pending，且从队列移除。"""
    from power_scope.ui.ai_copilot_view import AICopilotView
    applied = []
    class Ctx:
        def read_variable(self, n): return None
        def waveform_stats(self, n): return {}
        def fault_codes(self): return []
        def current_metrics(self): return {}
        def validate_param(self, n, v): return (True, min(v, 5.0), "OK")
        def apply_pending(self, act): applied.append(act); return f"wrote {act.name}"
    v = AICopilotView()
    v.set_tool_context(Ctx())
    v._executor.execute("propose_param_write", {"name": "Kp", "value": 9.0})
    assert len(v._executor.pending) == 1
    v._render_pending()
    v._confirm(v._executor.pending[0])
    assert len(applied) == 1 and applied[0].name == "Kp"
    assert v._executor.pending == []
    v.deleteLater()


def test_tool_context_bridge(qapp):
    """MainWindowToolContext 缓存变量、护栏校验、波形统计。"""
    from power_scope.ui.ai_tool_context import MainWindowToolContext
    from power_scope.core.event_bus import VarUpdatedEvent

    class FakeGuard:
        class R:
            allowed = True; clamped_value = 3.0; message = "OK"
        def validate(self, n, v): return self.R()
        def record(self, n, v): pass

    class FakeMW:
        _guardrails = FakeGuard()
        _tune_view = None

    ctx = MainWindowToolContext(FakeMW())
    try:
        ctx._on_var(VarUpdatedEvent(name="Vdc", raw_value=400, phys_value=400.0,
                                    unit="V", timestamp=0.0, source="test"))
        assert ctx.read_variable("Vdc") == 400.0
        allowed, clamped, msg = ctx.validate_param("Kp", 9.0)
        assert allowed and clamped == 3.0
        assert ctx.waveform_stats("Vdc")["Vdc"]["last"] == 400.0
    finally:
        ctx.close()


def test_tool_context_apply_pending_writes(qapp):
    """apply_pending 对 param_write 调用 _write_var_to_device 并记录。"""
    from power_scope.ui.ai_tool_context import MainWindowToolContext
    writes = []
    class FakeProfile:
        def find_var(self, n): return {"name": n}
    class FakeMW:
        _guardrails = None
        _tune_view = None
        _profile = FakeProfile()
        def _write_var_to_device(self, var, val): writes.append((var, val))
    ctx = MainWindowToolContext(FakeMW())
    try:
        msg = ctx.apply_pending(PendingAction(kind="param_write", name="Kp",
                                              value=1.0, clamped=1.0))
        assert writes and writes[0][1] == 1.0 and "Kp" in msg
    finally:
        ctx.close()
