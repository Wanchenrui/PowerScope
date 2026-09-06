"""guardrails.py — 安全护栏

参数写入的安全检查与回退机制:
- 范围检查: 超出 [min_val, max_val] 拒绝，保留请求原值
- 增幅限制 (Rate Limit): 限制单次变化幅度
- 回退 (Rollback): 记录历史，支持回退到前值

使用方式:
    gr = Guardrails(profile)
    result = gr.validate("Kp_d", 150.0)
    if result.allowed:
        write(result.clamped_value)
        gr.record("Kp_d", result.clamped_value)
    else:
        rollback_value = gr.rollback("Kp_d")
"""
from __future__ import annotations
import time
import math
from dataclasses import dataclass
from typing import Optional


CONTROL_RESTRICTION = "控制受限: 尚无已验证的设备身份、类型和写权限证据（只读可用）"


def control_restriction(check=None):
    """Temporary G0 UI gate; an absent or failing capability check denies control."""
    if check is None:
        return CONTROL_RESTRICTION
    try:
        reason = check()
        return reason if isinstance(reason, str) else CONTROL_RESTRICTION
    except Exception as exc:
        return f"控制受限: 权限校验异常: {exc}"


@dataclass
class GuardrailsResult:
    """护栏检查结果"""
    allowed: bool               # 是否允许写入
    clamped_value: float        # 限幅/修正后的值
    message: str                # 操作说明（限幅、增幅限制等）
    original_value: float       # 原始请求值
    previous_value: Optional[float] = None  # 前值（用于回退）


class Guardrails:
    """参数写入安全护栏"""

    def __init__(self, profile=None) -> None:
        self._profile = profile
        # var_name -> [(timestamp, value)]
        self._history: dict[str, list[tuple[float, float]]] = {}
        # var_name -> last_value
        self._last_values: dict[str, float] = {}
        self._default_max_rate: float = float("inf")

    # ------------------------------------------------------------------
    # 核心 API
    # ------------------------------------------------------------------

    def validate(
        self,
        var_name: str,
        raw_value: float,
        max_rate: Optional[float] = None,
        max_violation_ratio: float = 5.0,
    ) -> GuardrailsResult:
        """验证请求数值；允许不代表已取得设备写权限

        Args:
            var_name: 变量名
            raw_value: 请求写入的原始值
            max_rate: 可选，单次最大变化幅度（默认无限制）
            max_violation_ratio: 保留旧调用签名，不再用于放行或限幅

        Returns:
            GuardrailsResult — allowed=False 表示写入被拒绝
        """
        # Display ranges are conservative rejection bounds, never write authority.
        # Keep clamped_value for existing callers, but never rewrite a command.
        previous = self._last_values.get(var_name)

        def reject(reason):
            return GuardrailsResult(False, raw_value, f"拒绝写入: {reason}",
                                    raw_value, previous)

        try:
            if not math.isfinite(raw_value):
                return reject("请求值必须是有限数值")
            var = self._profile.find_var(var_name) if self._profile else None
            if var is None:
                return reject(f"未知变量或缺少配置: {var_name}")
            min_v, max_v = var.min_val, var.max_val
            if not math.isfinite(min_v) or not math.isfinite(max_v) or min_v > max_v:
                return reject("配置范围无效")
            if not min_v <= raw_value <= max_v:
                return reject(f"请求值 {raw_value} 超出范围 [{min_v}, {max_v}]")
            rate = max_rate if max_rate is not None else self._default_max_rate
            if math.isnan(rate) or rate < 0:
                return reject("变化幅度限制无效")
            if previous is not None and abs(raw_value - previous) > rate:
                return reject(f"超出单次变化幅度限制 {rate}")
        except Exception as exc:
            return reject(f"校验异常: {exc}")
        return GuardrailsResult(True, raw_value, "OK", raw_value, previous)

    def record(self, var_name: str, value: float) -> None:
        """记录成功写入的值（应在实际发送命令后调用）"""
        self._last_values[var_name] = value
        self._history.setdefault(var_name, []).append((time.time(), value))
        # 限制历史长度，避免内存无限增长
        if len(self._history[var_name]) > 1000:
            self._history[var_name] = self._history[var_name][-500:]

    def rollback(self, var_name: str) -> Optional[float]:
        """回退到上一个值

        Returns:
            前值，如果无历史则返回 None
        """
        history = self._history.get(var_name, [])
        if len(history) >= 2:
            return history[-2][1]
        return None

    def get_history(self, var_name: str) -> list[tuple[float, float]]:
        """获取变量写入历史（深拷贝）"""
        return self._history.get(var_name, []).copy()

    def get_last_value(self, var_name: str) -> Optional[float]:
        """获取上次写入的值"""
        return self._last_values.get(var_name)
