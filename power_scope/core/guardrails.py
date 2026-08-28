"""guardrails.py — 安全护栏

参数写入的安全检查与回退机制:
- 限幅 (Clamp): 确保值在 [min_val, max_val] 范围内
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
from dataclasses import dataclass
from typing import Optional


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
        """验证写入请求，返回修正后的值和操作说明

        Args:
            var_name: 变量名
            raw_value: 请求写入的原始值
            max_rate: 可选，单次最大变化幅度（默认无限制）
            max_violation_ratio: 超过上限多少倍时拒绝写入（默认 5 倍）

        Returns:
            GuardrailsResult — allowed=False 表示写入被拒绝
        """
        var = None
        if self._profile is not None:
            var = self._profile.find_var(var_name)

        original = raw_value
        clamped = raw_value
        messages: list[str] = []
        previous = self._last_values.get(var_name)

        # 1. 限幅 Clamp
        if var is not None:
            min_v = getattr(var, "min_val", float("-inf"))
            max_v = getattr(var, "max_val", float("inf"))

            # 检查是否严重越界 — 超过量程倍率限制时拒绝写入
            # 使用 (max_v - min_v) 作为量程宽度来评估越界程度
            range_width = max_v - min_v if max_v != float("inf") and min_v != float("-inf") else 1.0
            if clamped > max_v + range_width * max_violation_ratio:
                return GuardrailsResult(
                    allowed=False,
                    clamped_value=max_v,
                    message=f"拒绝写入: 请求值 {original} 超过上限 {max_v} + {range_width * max_violation_ratio:.0f}",
                    original_value=original,
                    previous_value=previous,
                )
            if clamped < min_v - range_width * max_violation_ratio:
                return GuardrailsResult(
                    allowed=False,
                    clamped_value=min_v,
                    message=f"拒绝写入: 请求值 {original} 远低于下限 {min_v}",
                    original_value=original,
                    previous_value=previous,
                )

            # 常规限幅（在容差范围内）
            if clamped < min_v:
                clamped = min_v
                messages.append(f"下限幅: {original} -> {min_v}")
            elif clamped > max_v:
                clamped = max_v
                messages.append(f"上限幅: {original} -> {max_v}")

        # 2. 增幅限制 Rate Limit
        rate_limit = max_rate if max_rate is not None else self._default_max_rate
        if previous is not None and rate_limit != float("inf"):
            delta = abs(clamped - previous)
            if delta > rate_limit:
                direction = 1 if clamped > previous else -1
                clamped = previous + direction * rate_limit
                messages.append(f"增幅限制: {delta:.3f} -> {rate_limit:.3f}")

        msg = "; ".join(messages) if messages else "OK"
        return GuardrailsResult(
            allowed=True,
            clamped_value=clamped,
            message=msg,
            original_value=original,
            previous_value=previous,
        )

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
