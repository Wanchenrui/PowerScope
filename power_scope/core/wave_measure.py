"""wave_measure.py — 波形光标测量与阶跃指标计算（P0-5 的纯逻辑层）

示波器视图的双光标测量 + 自动指标标注的计算内核，不依赖 Qt / pyqtgraph，
可独立单测；scope_view.py 只负责把 RealtimePlotWidget 的窗口数据喂进来。

指标定义（与 core/step_response.analyze_step 同一套口径）：
  - rise:      10% → 90% 上升时间（按区间内 min→max 归一化）
  - settle:    进入以末段稳态为中心的 ±tolerance% 误差带且不再离开
  - overshoot: 峰值相对稳态值的超调百分比
  - steady:    末段 10% 样本均值
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CursorReadout:
    """单个光标的读数。"""

    t: float
    value: float
    found: bool = True      # 光标落在数据范围内


@dataclass
class Measurement:
    """光标区间的自动测量结果。"""

    channel: str = ""
    t0: float = 0.0
    t1: float = 0.0
    dt: float = 0.0
    v0: float = 0.0
    v1: float = 0.0
    dv: float = 0.0
    min_value: float = 0.0
    max_value: float = 0.0
    steady: float = 0.0
    rise_ms: float = 0.0
    settle_ms: float = 0.0
    overshoot_pct: float = 0.0
    valid: bool = False
    info: str = ""

    def as_dict(self) -> dict:
        return {
            "channel": self.channel,
            "t0": self.t0, "t1": self.t1, "dt": self.dt,
            "v0": self.v0, "v1": self.v1, "dv": self.dv,
            "min_value": self.min_value, "max_value": self.max_value,
            "steady": self.steady,
            "rise_ms": self.rise_ms,
            "settle_ms": self.settle_ms,
            "overshoot_pct": self.overshoot_pct,
        }


def interp_at(times: list[float], values: list[float], x: float) -> float | None:
    """线性插值取 x 处的 y；x 超出数据范围返回 None。"""
    if not times or not values or len(times) != len(values):
        return None
    if x < times[0] or x > times[-1]:
        return None
    lo, hi = 0, len(times) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if times[mid] <= x:
            lo = mid
        else:
            hi = mid
    t0, t1 = times[lo], times[hi]
    v0, v1 = values[lo], values[hi]
    if t1 == t0:
        return v0
    return v0 + (v1 - v0) * (x - t0) / (t1 - t0)


def cursor_readout(times: list[float], values: list[float],
                   x: float) -> CursorReadout:
    """单光标读数（超出范围时贴到端点并标记 found=False）。"""
    y = interp_at(times, values, x)
    if y is not None:
        return CursorReadout(t=x, value=y, found=True)
    if not times:
        return CursorReadout(t=x, value=0.0, found=False)
    if x < times[0]:
        return CursorReadout(t=times[0], value=values[0], found=False)
    return CursorReadout(t=times[-1], value=values[-1], found=False)


def slice_window(times: list[float], values: list[float],
                 t0: float, t1: float) -> tuple[list[float], list[float]]:
    """截取 [t0, t1] 闭区间内的样本（含端点插值）。"""
    if not times or t1 < t0 or t1 < times[0] or t0 > times[-1]:
        return [], []
    ts: list[float] = []
    vs: list[float] = []
    y0 = interp_at(times, values, t0)
    if y0 is not None:
        ts.append(t0)
        vs.append(y0)
    for t, v in zip(times, values):
        if t0 <= t <= t1:
            ts.append(t)
            vs.append(v)
    y1 = interp_at(times, values, t1)
    if y1 is not None and (not ts or ts[-1] < t1):
        ts.append(t1)
        vs.append(y1)
    return ts, vs


def _crossing(vs: list[float], ts: list[float], level: float,
              rising: bool) -> float | None:
    """找曲线穿越 level 的时刻（升沿/降沿）。"""
    for i in range(1, len(vs)):
        a, b = vs[i - 1], vs[i]
        if rising and a < level <= b:
            if b == a:
                return ts[i]
            return ts[i - 1] + (level - a) * (ts[i] - ts[i - 1]) / (b - a)
        if not rising and a > level >= b:
            if b == a:
                return ts[i]
            return ts[i - 1] + (level - a) * (ts[i] - ts[i - 1]) / (b - a)
    return None


def measure(times: list[float], values: list[float], t0: float, t1: float,
            channel: str = "", tolerance_pct: float = 2.0) -> Measurement:
    """对 [t0, t1] 区间做上升/调节/超调测量。

    样本 <4 或区间无变化时 valid=False 并通过 info 说明原因。
    """
    ts, vs = slice_window(times, values, t0, t1)
    m = Measurement(channel=channel, t0=t0, t1=t1)
    if len(ts) < 4:
        m.info = f"区间样本不足（{len(ts)} 个）"
        return m
    m.dt = ts[-1] - ts[0]
    m.v0, m.v1 = vs[0], vs[-1]
    m.dv = vs[-1] - vs[0]
    m.min_value, m.max_value = min(vs), max(vs)
    tail_n = max(2, len(vs) // 10)
    m.steady = sum(vs[-tail_n:]) / tail_n
    span = m.max_value - m.min_value
    if span <= 1e-12:
        m.info = "区间内无显著变化"
        return m
    m.valid = True

    lo10 = m.min_value + 0.10 * span
    hi90 = m.min_value + 0.90 * span
    rising = m.dv > 0
    t10 = _crossing(vs, ts, lo10, rising)
    t90 = _crossing(vs, ts, hi90, rising)
    if t10 is not None and t90 is not None and t90 > t10:
        m.rise_ms = (t90 - t10) * 1000.0

    band = abs(m.steady) * tolerance_pct / 100.0
    if band <= 1e-12:
        band = span * tolerance_pct / 100.0
    settle_t: float | None = None
    for i in range(len(vs) - 1, -1, -1):
        if abs(vs[i] - m.steady) > band:
            settle_t = ts[i + 1] if i + 1 < len(ts) else None
            break
    if settle_t is not None and settle_t > ts[0]:
        m.settle_ms = (settle_t - ts[0]) * 1000.0

    if m.steady != 0:
        peak = m.max_value if rising else m.min_value
        if rising:
            m.overshoot_pct = max(0.0, (peak - m.steady) / abs(m.steady) * 100.0)
        else:
            m.overshoot_pct = max(0.0, (m.steady - peak) / abs(m.steady) * 100.0)
    return m


def format_summary(m: Measurement) -> str:
    """把 Measurement 格式化为一行人读摘要。"""
    if not m.valid:
        return f"测量无效: {m.info or '数据不足'}"
    return (f"{m.channel}: 上升 {m.rise_ms:.1f}ms | 调节 {m.settle_ms:.1f}ms | "
            f"超调 {m.overshoot_pct:.2f}% | 稳态 {m.steady:.4g} "
            f"(Δt={m.dt * 1000:.1f}ms, ΔV={m.dv:.4g})")


def readouts_summary(a: CursorReadout, b: CursorReadout) -> str:
    """双光标读数摘要（X/Y/Δ）。"""
    dt = b.t - a.t
    dv = b.value - a.value
    return (f"A: t={a.t:.4f}s y={a.value:.4g}   "
            f"B: t={b.t:.4f}s y={b.value:.4g}   "
            f"Δt={dt:.4f}s Δy={dv:.4g}")
