"""test_llm_tools.py — LLM 工具集与安全桥接"""
import pytest
from power_scope.llm.tools import (
    ToolExecutor, TOOL_SCHEMAS, READONLY_TOOLS, WRITE_TOOLS, PendingAction,
)


class FakeCtx:
    def __init__(self):
        self.written = []  # 若被写入会记录 — 应始终为空
    def read_variable(self, name):
        return {"Vdc": 400.0, "Id": 10.5}.get(name)
    def waveform_stats(self, name):
        return {"Vdc": {"min": 395, "max": 405, "mean": 400, "std": 2.1, "last": 401}}
    def fault_codes(self):
        return [{"code": "0x0002", "meaning": "过压"}]
    def current_metrics(self):
        return {"overshoot": 18.0, "rise_time_ms": 12.0, "kp": 0.85, "ki": 120.0}
    def validate_param(self, name, value):
        # 模拟护栏：Kp 限到 5
        clamped = min(value, 5.0)
        return (True, clamped, "OK" if clamped == value else f"限幅到 {clamped}")


def test_schemas_shape():
    names = {s["function"]["name"] for s in TOOL_SCHEMAS}
    assert READONLY_TOOLS <= names and WRITE_TOOLS <= names


def test_read_variable():
    ex = ToolExecutor(FakeCtx())
    r = ex.execute("read_variable", {"name": "Vdc"})
    assert r["value"] == 400.0 and r["available"] is True
    r2 = ex.execute("read_variable", {"name": "NoSuch"})
    assert r2["available"] is False


def test_read_variable_json_args():
    ex = ToolExecutor(FakeCtx())
    r = ex.execute("read_variable", '{"name": "Id"}')
    assert r["value"] == 10.5


def test_readonly_tools_no_pending():
    ex = ToolExecutor(FakeCtx())
    ex.execute("get_waveform_stats", {})
    ex.execute("get_fault_codes", {})
    ex.execute("get_current_metrics", {})
    assert ex.pending == []  # 只读工具不产生待确认动作


def test_write_is_only_proposed():
    """写参数只提议、经护栏、不真正写入。"""
    ctx = FakeCtx()
    ex = ToolExecutor(ctx)
    r = ex.execute("propose_param_write", {"name": "Kp", "value": 8.0})
    assert r["status"] == "pending_confirm"
    assert r["clamped"] == 5.0            # 经护栏限幅
    assert len(ex.pending) == 1
    assert isinstance(ex.pending[0], PendingAction)
    assert ex.pending[0].kind == "param_write"
    assert ctx.written == []              # 红线：从未真正写入


def test_step_test_only_proposed():
    ex = ToolExecutor(FakeCtx())
    r = ex.execute("propose_step_test", {"loop": "id_loop", "amplitude": 2.0})
    assert r["status"] == "pending_confirm"
    assert ex.pending[0].kind == "step_test"


def test_bad_json_and_missing_arg():
    ex = ToolExecutor(FakeCtx())
    assert "error" in ex.execute("read_variable", "{not json}")
    assert "error" in ex.execute("read_variable", {})
    assert "error" in ex.execute("unknown_tool", {})
