"""test_llm_toolcall_loop.py — function-calling 循环逻辑（monkeypatch HTTP）"""
import json
import pytest
from power_scope.llm.llm_engine import LLMEngine, LLMConfig
from power_scope.llm.tools import ToolExecutor


class FakeCtx:
    def read_variable(self, name): return 400.0 if name == "Vdc" else None
    def waveform_stats(self, name): return {}
    def fault_codes(self): return []
    def current_metrics(self): return {"overshoot": 18.0, "kp": 0.85}
    def validate_param(self, name, value): return (True, min(value, 5.0), "OK")


def test_tool_loop_executes_then_finalizes(monkeypatch):
    eng = LLMEngine(LLMConfig(provider="deepseek", api_key="x", model="deepseek-chat",
                              base_url="https://api.deepseek.com/v1/chat/completions"))
    ex = ToolExecutor(FakeCtx())
    eng.set_tool_executor(ex)

    # 第一次返回 tool_calls，第二次返回最终答复
    calls = {"n": 0}
    def fake_post(payload):
        calls["n"] += 1
        # 断言携带了 tools
        assert "tools" in payload
        if calls["n"] == 1:
            return {"choices": [{"message": {
                "content": None,
                "tool_calls": [{
                    "id": "c1",
                    "function": {"name": "read_variable",
                                 "arguments": json.dumps({"name": "Vdc"})},
                }],
            }}]}
        return {"choices": [{"message": {
            "content": "当前 Vdc=400V，建议新参数 Kp: 1.0，Ki: 130，风险 低。"}}]}
    monkeypatch.setattr(eng, "_post_openai", fake_post)

    resp = eng._call_with_tools()
    assert calls["n"] == 2                      # 一轮工具 + 一轮最终
    assert any(t["name"] == "read_variable" for t in resp.tool_trace)
    assert resp.tool_trace[0]["result"]["value"] == 400.0
    assert "Kp" in resp.text
    assert resp.params_suggested.get("Kp") == 1.0   # _parse_response 抽参


def test_tool_loop_respects_max_rounds(monkeypatch):
    eng = LLMEngine(LLMConfig(provider="deepseek", api_key="x",
                              base_url="https://api.deepseek.com/v1/chat/completions"))
    eng.set_tool_executor(ToolExecutor(FakeCtx()))
    # 永远返回 tool_calls → 触发上限保护
    def always_tool(payload):
        return {"choices": [{"message": {"content": None, "tool_calls": [{
            "id": "c", "function": {"name": "get_current_metrics", "arguments": "{}"}}]}}]}
    monkeypatch.setattr(eng, "_post_openai", always_tool)
    resp = eng._call_with_tools(max_rounds=3)
    assert "轮数超过上限" in resp.text
    assert len(resp.tool_trace) == 3
