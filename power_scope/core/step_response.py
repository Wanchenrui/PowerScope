"""step_response.py — 阶跃响应指标提取 (Task 2)

把一段反馈采样 [(t_seconds, value)] + 阶跃施加时刻/幅值，提取经典阶跃响应指标：
超调量、上升时间(10-90%)、调节时间(±tol)、稳态误差，并用两点法(28.3%/63.2%)
辨识等效一阶纯滞后(FOPDT) K/T/L，供 tuning_engine 的 Cohen-Coon/IMC/ZN 使用。

纯函数、无 Qt、无硬件依赖 —— 可完全单元测试。MCU 无 TRIGGER_STEP，阶跃由 PC 主动
WRITE_MEM 施加；本模块只负责"分析已采集的响应"。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class StepMetrics:
    """阶跃响应分析结果。valid=False 时其余字段无意义，info 说明原因。"""
    valid: bool = False
    info: str = ""
    y0: float = 0.0
    y_final: float = 0.0
    delta: float = 0.0
    overshoot_pct: float = 0.0
    rise_time_ms: float = 0.0
    settling_time_ms: float = 0.0
    peak_time_ms: float = 0.0
    steady_error_pct: float = 0.0
    K: float = 0.0
    T: float = 0.0
    L: float = 0.0

    def to_system_metrics(self):
        """转换为 tuning_engine.SystemMetrics（FOPDT + 直接指标），无效值回退到默认。"""
        from .tuning_engine import SystemMetrics
        return SystemMetrics(
            overshoot=self.overshoot_pct,
            rise_time_ms=self.rise_time_ms,
            settling_time_ms=self.settling_time_ms,
            steady_error=self.steady_error_pct,
            K=self.K if self.K > 0 else 1.0,
            T=self.T if self.T > 0 else 0.025,
            L=self.L if self.L > 0 else 0.005,
            identified=(self.valid and self.K > 0 and self.T > 0),
        )


def _interp_cross(norm, level):
    """norm=[(t, 归一化升序值)]：返回首次达到 level 的时间(线性插值)，未达到返回 None。"""
    prev_t, prev_v = norm[0]
    for i in range(1, len(norm)):
        t, v = norm[i]
        if v >= level:
            if v == prev_v:
                return t
            return prev_t + (level - prev_v) / (v - prev_v) * (t - prev_t)
        prev_t, prev_v = t, v
    return None


def analyze_step(samples, t_step, input_step=None, settle_tol=0.02,
                 final_frac=0.1, baseline=None) -> StepMetrics:
    """分析阶跃响应。

    Args:
        samples: [(t_seconds, value)] 反馈采样（含阶跃前的稳态段更佳）。
        t_step: 阶跃施加时刻 (s)；之前的样本用于估初值 y0。
        input_step: 命令阶跃幅值（参考值变化量）。给定时计算稳态误差与 FOPDT 增益 K。
        settle_tol: 调节时间判据带宽（相对终值的比例，默认 2%）。
        final_frac: 取阶跃后末尾该比例的样本均值作为稳态终值 y_final。
    """
    pts = sorted(((float(t), float(v)) for t, v in samples), key=lambda p: p[0])
    if len(pts) < 5:
        return StepMetrics(info="采样点过少")

    pre = [v for t, v in pts if t < t_step]
    post = [(t, v) for t, v in pts if t >= t_step]
    if len(post) < 5:
        return StepMetrics(info="阶跃后采样过少")

    y0 = (float(baseline) if baseline is not None
          else (sum(pre) / len(pre) if pre else post[0][1]))
    tail_n = max(1, int(len(post) * final_frac))
    y_final = sum(v for _, v in post[-tail_n:]) / tail_n
    delta = y_final - y0

    spread = max(v for _, v in post) - min(v for _, v in post)
    if abs(delta) < max(1e-9, 0.05 * spread):
        return StepMetrics(info="未检测到有效阶跃响应", y0=y0, y_final=y_final)

    sign = 1.0 if delta >= 0 else -1.0
    final_n = abs(delta)
    norm = [(t, (v - y0) * sign) for t, v in post]   # 归一化为始终上升

    peak = max(v for _, v in norm)
    overshoot = max(0.0, (peak - final_n) / final_n * 100.0)
    peak_t = max(norm, key=lambda p: p[1])[0]
    peak_ms = max(0.0, (peak_t - t_step) * 1000.0)

    t10 = _interp_cross(norm, 0.1 * final_n)
    t90 = _interp_cross(norm, 0.9 * final_n)
    rise_ms = ((t90 - t10) * 1000.0
               if t10 is not None and t90 is not None and t90 >= t10 else 0.0)

    band = settle_tol * final_n
    settle_t = norm[0][0]
    for t, v in norm:
        if abs(v - final_n) > band:
            settle_t = t                              # 最后一次离开带 → 其后即进入
    settling_ms = max(0.0, (settle_t - t_step) * 1000.0)

    steady_err = ((abs(input_step) - final_n) / abs(input_step) * 100.0
                  if input_step else 0.0)

    # 两点法 FOPDT (Smith): T=1.5*(t63-t28)，L=t63(相对阶跃) - T
    t28 = _interp_cross(norm, 0.283 * final_n)
    t63 = _interp_cross(norm, 0.632 * final_n)
    if t28 is not None and t63 is not None and t63 > t28:
        T = 1.5 * (t63 - t28)
        L = max(0.0, (t63 - t_step) - T)
    else:
        T = L = 0.0
    K = abs(delta / input_step) if input_step else abs(delta)

    return StepMetrics(
        valid=True, info="OK", y0=y0, y_final=y_final, delta=delta,
        overshoot_pct=overshoot, rise_time_ms=rise_ms, settling_time_ms=settling_ms,
        peak_time_ms=peak_ms,
        steady_error_pct=steady_err, K=K, T=T, L=L,
    )


@dataclass
class StepLoopConfig:
    """单个控制环路的阶跃测试配置（从 profile.tuning.loops 的原始 dict 解析）。

    setpoint/feedback 为 profile 变量名（与 Kp/Ki/Kd 同样经 _resolve_channel 解析到地址）。
    step_max 是该环路允许的最大阶跃幅值（绝对值）；未配置(<=0)时禁止主动写阶跃，
    只能走"被动采集"或先在 profile 里由硬件负责人填入安全上限。
    """
    loop_id: str = ""
    label: str = ""
    setpoint: str = ""
    feedback: str = ""
    step_default: float = 1.0
    step_max: float = 0.0
    params: dict = field(default_factory=dict)

    @property
    def ready_for_active_step(self) -> bool:
        """主动写阶跃的前置条件：setpoint、feedback、step_max>0 三者齐备。"""
        return bool(self.setpoint and self.feedback and self.step_max > 0)

    def clamp_amplitude(self, amp: float) -> float:
        """把请求幅值钳到 [-step_max, step_max]；step_max<=0 时返回 0（禁止写）。"""
        if self.step_max <= 0:
            return 0.0
        return max(-self.step_max, min(self.step_max, float(amp)))


def parse_step_loop(loop) -> StepLoopConfig:
    """把一个原始 loop dict 解析成 StepLoopConfig，缺省/非法值安全回退。"""
    d = dict(loop or {})

    def _num(key, default):
        v = d.get(key, None)
        if v is None:
            return default
        try:
            return float(v)
        except (TypeError, ValueError):
            return default

    return StepLoopConfig(
        loop_id=str(d.get("id", "")),
        label=str(d.get("label", d.get("id", ""))),
        setpoint=str(d.get("setpoint") or ""),
        feedback=str(d.get("feedback") or ""),
        step_default=_num("step_default", 1.0),
        step_max=max(0.0, _num("step_max", 0.0)),
        params=dict(d.get("params", {}) or {}),
    )