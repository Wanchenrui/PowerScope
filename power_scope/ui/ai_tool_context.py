"""ai_tool_context.py — AICopilotView 的 ToolContext 实现。

桥接主窗口的实时数据（EventBus var/updated 缓存）、安全护栏（Guardrails）、
参数下发（DebugService）。写操作只有在 UI 人工点「确认下发」时经此 apply_pending
才真正写入 —— 与 LLM 之间隔着一道人工确认。
"""
from __future__ import annotations
from ..core.event_bus import EventBus


class MainWindowToolContext:
    def __init__(self, main_window):
        self.mw = main_window
        self._cache = {}   # name -> phys_value
        EventBus.instance().subscribe("var/updated", self._on_var)

    def _on_var(self, ev):
        try:
            self._cache[ev.name] = ev.phys_value
        except Exception:
            pass

    # --- 只读工具 ---
    def read_variable(self, name):
        return self._cache.get(name)

    def waveform_stats(self, name):
        if name and name in self._cache:
            return {name: {"last": self._cache[name]}}
        return {k: {"last": v} for k, v in list(self._cache.items())[:16]}

    def fault_codes(self):
        out = []
        for k, v in self._cache.items():
            if ("fault" in k.lower() or "err" in k.lower()) and v:
                out.append({"var": k, "value": v})
        return out

    def current_metrics(self):
        tv = getattr(self.mw, "_tune_view", None)
        m = {}
        if tv is None:
            return m
        try:
            if hasattr(tv, "_manual_overshoot"):
                m["overshoot"] = tv._manual_overshoot.value()
            if hasattr(tv, "_manual_rise_time"):
                m["rise_time"] = tv._manual_rise_time.value()
            if hasattr(tv, "_manual_settling_time"):
                m["settling_time"] = tv._manual_settling_time.value()
            if hasattr(tv, "_kp_input"):
                m["current_kp"] = tv._kp_input.value()
            if hasattr(tv, "_ki_input"):
                m["current_ki"] = tv._ki_input.value()
            if hasattr(tv, "_kd_input"):
                m["current_kd"] = tv._kd_input.value()
        except Exception:
            pass
        return m

    # --- 安全校验（不写入） ---
    def validate_param(self, name, value):
        g = getattr(self.mw, "_guardrails", None)
        if g is None:
            return (False, value, "拒绝写入: 缺少校验器")
        try:
            r = g.validate(name, value)
            return (r.allowed, r.clamped_value, r.message)
        except Exception as e:  # noqa: BLE001
            return (False, value, f"拒绝写入: 护栏异常: {e}")

    # --- 人工确认后真正下发 ---
    def apply_pending(self, act):
        if act.kind == "param_write":
            allowed, val, reason = self.validate_param(act.name, act.value)
            if not allowed:
                return reason
            writer = getattr(self.mw, "_write_var_to_device", None)
            if writer is None:
                return "拒绝写入: 缺少设备写入入口"
            var = self.mw._profile.find_var(act.name)
            if not writer(var, val):
                return f"拒绝写入 {act.name}: 未获得设备写入权限或下发失败"
            session = getattr(self.mw, "_session", None)
            if session is not None and session._transport_type() == "mock":
                return f"模拟写入 {act.name} = {val}（未向真实设备发送）"
            return f"已提交 {act.name} = {val}，等待设备确认"
        return f"阶跃测试 {act.name} 请在调参页触发（受 step_max 限幅）"

    def close(self):
        try:
            EventBus.instance().unsubscribe("var/updated", self._on_var)
        except Exception:
            pass
