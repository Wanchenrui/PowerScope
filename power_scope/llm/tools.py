"""tools.py — LLM 可调用工具集 + 安全桥接。

工具 schema 遵循 OpenAI/DeepSeek function-calling 规范。安全红线：
  - 只读工具（读变量/波形统计/故障码/当前指标）直接执行返回；
  - 写类工具（写参数/触发阶跃）**只提议不执行**：经 Guardrails 校验后记入
    pending 待确认队列，返回 status="pending_confirm"，由 UI 人工确认后才真正下发。
LLM 无法越过安全链直接写 MCU。

ToolContext 是数据/安全访问的鸭子类型接口，真实实现桥接 DebugService/
Guardrails/SafetyController，测试可注入 Fake。
"""
from __future__ import annotations
import json
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol


# ────────────────────────────────────────────────────────────────
# OpenAI/DeepSeek function-calling 工具 schema
# ────────────────────────────────────────────────────────────────

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "read_variable",
            "description": "读取一个已绑定变量的当前物理量值（如 Vdc、Id、频率）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "变量名（profile 中的绑定名）"}
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_waveform_stats",
            "description": "获取某通道近窗口波形的统计（min/max/mean/std/最新值）。name 省略则返回全部通道。",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_fault_codes",
            "description": "读取当前故障码列表（十六进制）及其含义。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_current_metrics",
            "description": "获取当前控制环路的实测性能指标（超调/上升时间/调节时间/稳态误差/当前PID）。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_param_write",
            "description": "提议把某控制参数改为新值（不会立即写入，需工程师在界面确认；返回安全护栏校验结果）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "参数名，如 Kp/Ki/Kd 或变量名"},
                    "value": {"type": "number", "description": "建议的新值"},
                },
                "required": ["name", "value"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_step_test",
            "description": "提议对某环路施加阶跃测试（不会立即触发，需工程师确认，且受 step_max 限幅）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "loop": {"type": "string", "description": "环路 id/label"},
                    "amplitude": {"type": "number", "description": "阶跃幅值"},
                },
                "required": ["loop"],
            },
        },
    },
]

READONLY_TOOLS = {"read_variable", "get_waveform_stats", "get_fault_codes", "get_current_metrics"}
WRITE_TOOLS = {"propose_param_write", "propose_step_test"}


class ToolContext(Protocol):
    """工具执行所需的数据/安全访问接口（鸭子类型）。"""
    def read_variable(self, name: str) -> Optional[float]: ...
    def waveform_stats(self, name: Optional[str]) -> dict: ...
    def fault_codes(self) -> list: ...
    def current_metrics(self) -> dict: ...
    def validate_param(self, name: str, value: float) -> tuple: ...  # (allowed, clamped, msg)


@dataclass
class PendingAction:
    """一个待人工确认的写/触发提议。"""
    kind: str                 # "param_write" | "step_test"
    name: str
    value: float = 0.0
    clamped: Optional[float] = None
    allowed: bool = True
    message: str = "OK"


class ToolExecutor:
    """把 LLM 的工具调用分派到 ToolContext；写类工具只提议不执行。"""

    def __init__(self, context: ToolContext):
        self.ctx = context
        self.pending: list[PendingAction] = []

    def execute(self, name: str, arguments: Any) -> dict:
        """执行一个工具调用。arguments 可为 dict 或 JSON 字符串。返回 JSON 可序列化 dict。"""
        args = arguments
        if isinstance(arguments, str):
            try:
                args = json.loads(arguments) if arguments.strip() else {}
            except json.JSONDecodeError:
                return {"error": f"参数不是合法 JSON: {arguments!r}"}
        args = args or {}

        try:
            if name == "read_variable":
                v = self.ctx.read_variable(args["name"])
                return {"name": args["name"], "value": v,
                        "available": v is not None}
            if name == "get_waveform_stats":
                return {"stats": self.ctx.waveform_stats(args.get("name"))}
            if name == "get_fault_codes":
                return {"fault_codes": self.ctx.fault_codes()}
            if name == "get_current_metrics":
                return {"metrics": self.ctx.current_metrics()}
            if name == "propose_param_write":
                allowed, clamped, msg = self.ctx.validate_param(
                    args["name"], float(args["value"]))
                act = PendingAction(kind="param_write", name=args["name"],
                                    value=float(args["value"]), clamped=clamped,
                                    allowed=allowed, message=msg)
                self.pending.append(act)
                return {"status": "pending_confirm", "allowed": allowed,
                        "clamped": clamped, "message": msg,
                        "note": "已提交待工程师确认，未写入 MCU。"}
            if name == "propose_step_test":
                act = PendingAction(kind="step_test", name=args["loop"],
                                    value=float(args.get("amplitude", 0.0)))
                self.pending.append(act)
                return {"status": "pending_confirm",
                        "note": "阶跃测试已提交待确认，受 step_max 限幅，未触发。"}
            return {"error": f"未知工具: {name}"}
        except KeyError as e:
            return {"error": f"缺少必要参数: {e}"}
        except Exception as e:  # noqa: BLE001
            return {"error": f"工具执行异常: {e}"}

    def clear_pending(self):
        self.pending.clear()
