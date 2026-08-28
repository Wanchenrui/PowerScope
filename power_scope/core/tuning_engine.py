"""tuning_engine.py — PID 调参策略引擎

策略模式封装：
- ZieglerNicholsTuner: 临界比例法
- CohenCoonTuner: 反应曲线法
- IMCTuner: 内模控制法
- FrequencyResponseTuner: 频率响应法

使用方式:
    engine = TuningEngine()
    engine.register("Ziegler-Nichols", ZieglerNicholsTuner())
    result = engine.compute("Ziegler-Nichols", metrics=metrics)
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Protocol
import numpy as np


@dataclass
class SystemMetrics:
    """系统性能指标"""
    overshoot: float = 0.0          # 超调量 %
    rise_time_ms: float = 0.0       # 上升时间 ms
    settling_time_ms: float = 0.0   # 调节时间 ms
    steady_error: float = 0.0        # 稳态误差 %
    # 等效一阶参数（从响应辨识）
    K: float = 1.0                  # 直流增益
    T: float = 0.025                # 时间常数 s
    L: float = 0.005                # 纯滞后 s
    # 辨识是否可信；False 时 K/T/L 为回退默认值，调参结果不可信
    identified: bool = True


@dataclass
class PIDParams:
    """PID 参数"""
    kp: float = 0.0
    ki: float = 0.0
    kd: float = 0.0
    # 额外信息
    info: str = ""
    # 来源策略
    source: str = ""
    # 计算是否有效；False 时 kp/ki/kd 无意义（输入非法/辨识失败）
    valid: bool = True

    def clamp(self, kp_max: float = 5.0, ki_max: float = 2000.0, kd_max: float = 0.5) -> "PIDParams":
        """限幅并返回新实例"""
        return PIDParams(
            kp=max(0.0, min(kp_max, self.kp)),
            ki=max(0.0, min(ki_max, self.ki)),
            kd=max(0.0, min(kd_max, self.kd)),
            info=self.info,
            source=self.source,
            valid=self.valid,
        )


class TuningStrategy(Protocol):
    """调参策略接口"""

    def compute(self, metrics: SystemMetrics) -> PIDParams:
        """根据系统指标计算 PID 参数"""
        ...

    def name(self) -> str:
        """策略名称"""
        ...


# ------------------------------------------------------------------
# 辅助
# ------------------------------------------------------------------

def _effective_L(T: float, L: float) -> float:
    """给纯滞后 L 一个下限，避免 L→0 时整定公式 Kp 爆炸。

    经验下限取 0.02·T（无 T 时取 1ms），既保留物理趋势又数值稳定。
    """
    floor = 0.02 * T if T > 0 else 1e-3
    return max(L, floor)


# ------------------------------------------------------------------
# 具体策略
# ------------------------------------------------------------------

class ZieglerNicholsTuner:
    """Ziegler-Nichols 反应曲线法（开环 FOPDT 整定）

    采用经典开环整定式（比反推临界增益 Ku/Tu 更稳、可复现）：
        Kp = 1.2·T/(K·L),  Ti = 2·L,  Td = 0.5·L
    其中 Ki = Kp/Ti, Kd = Kp·Td。L 过小时用 _effective_L 兜底。
    """

    def name(self) -> str:
        return "Ziegler-Nichols"

    def compute(self, metrics: SystemMetrics) -> PIDParams:
        K, T = metrics.K, metrics.T
        if K <= 0 or T <= 0:
            return PIDParams(info="无效参数: K/T 必须 > 0", source="Ziegler-Nichols", valid=False)
        L = _effective_L(T, metrics.L)
        Ti = 2.0 * L
        Td = 0.5 * L
        kp = 1.2 * T / (K * L)
        ki = kp / Ti
        kd = kp * Td
        note = "" if metrics.L > 0 else "（L 缺失，已用下限估算）"
        return PIDParams(
            kp=kp, ki=ki, kd=kd,
            info=f"K={K:.3f}, T={T*1000:.1f}ms, L={L*1000:.1f}ms{note}",
            source="Ziegler-Nichols",
        )


class CohenCoonTuner:
    """Cohen-Coon 反应曲线法"""

    def name(self) -> str:
        return "Cohen-Coon"

    def compute(self, metrics: SystemMetrics) -> PIDParams:
        K, T, L = metrics.K, metrics.T, metrics.L
        if K <= 0 or L <= 0 or T <= 0:
            return PIDParams(kp=0, ki=0, kd=0, info="无效参数: K/L/T 必须 > 0",
                             source="Cohen-Coon", valid=False)

        ratio = L / T
        # Cohen-Coon PID 公式
        kp = (1.35 / K) * (1 / ratio + 0.185) / (1 + 0.611 * ratio)
        ki = kp / (2.5 * L * (1 + 0.185 * ratio))
        kd = kp * 0.37 * L * (1 - 0.37 * ratio)
        return PIDParams(
            kp=kp, ki=ki, kd=kd,
            info=f"K={K:.3f}, T={T*1000:.1f}ms, L={L*1000:.1f}ms",
            source="Cohen-Coon",
        )


class IMCTuner:
    """IMC 内模控制法"""

    def __init__(self, tau_c_factor: float = 0.5) -> None:
        self.tau_c_factor = tau_c_factor  # tau_c = tau_c_factor * T

    def name(self) -> str:
        return "IMC"

    def compute(self, metrics: SystemMetrics) -> PIDParams:
        K, T, L = metrics.K, metrics.T, metrics.L
        if K <= 0 or L <= 0 or T <= 0:
            return PIDParams(kp=0, ki=0, kd=0, info="无效参数: K/L/T 必须 > 0",
                             source="IMC", valid=False)

        tau_c = self.tau_c_factor * T
        # IMC PID 公式 (FOPDT 一阶纯滞后)
        kp = T / (K * (tau_c + L))
        ki = kp / (T + 0.5 * L)
        kd = 0.5 * kp * L / (T + 0.5 * L)
        return PIDParams(
            kp=kp, ki=ki, kd=kd,
            info=f"tau_c={tau_c*1000:.1f}ms, K={K:.3f}",
            source="IMC",
        )


class FrequencyResponseTuner:
    """频率响应法 — 基于相位裕度和增益裕度

    超调量 → 阻尼比 ζ → 相位裕度（标准闭式关系）：
        ζ = -ln(Mp)/√(π²+ln²(Mp)),  Mp = 超调/100
        PM = atan( 2ζ / √(√(1+4ζ⁴) − 2ζ²) )   （度）
    再据穿越频率与 FOPDT 增益设计 PI。此法为工程近似，info 中标注。
    """

    def name(self) -> str:
        return "Frequency-Response"

    def compute(self, metrics: SystemMetrics) -> PIDParams:
        if metrics.K <= 0 or metrics.T <= 0:
            return PIDParams(info="无效参数: K/T 必须 > 0", source="Frequency-Response", valid=False)

        # 从超调量估算阻尼比与相位裕度（标准二阶闭式关系）
        overshoot = metrics.overshoot
        if overshoot > 0:
            mp = min(0.99, overshoot / 100.0)
            ln_mp = np.log(mp)
            zeta = -ln_mp / np.sqrt(np.pi ** 2 + ln_mp ** 2)
            zeta = float(np.clip(zeta, 0.05, 0.99))
            pm = np.degrees(np.arctan2(2 * zeta,
                                       np.sqrt(np.sqrt(1 + 4 * zeta ** 4) - 2 * zeta ** 2)))
        else:
            pm = 60.0

        # 从时间常数估算穿越频率
        wc = 1.0 / metrics.T
        # 基于相位裕度设计 PI
        kp = wc * metrics.T / metrics.K
        ki = kp * wc / (2 * np.tan(np.radians(pm)))
        kd = 0.0  # PI 控制

        return PIDParams(
            kp=kp, ki=ki, kd=kd,
            info=f"wc={wc:.1f}rad/s, PM≈{pm:.0f}°(近似), Gm≈6dB",
            source="Frequency-Response",
        )


# ------------------------------------------------------------------
# 引擎
# ------------------------------------------------------------------

class TuningEngine:
    """调参引擎 — 策略注册与执行"""

    def __init__(self) -> None:
        self._strategies: dict[str, TuningStrategy] = {}
        # 注册默认策略
        self.register("Ziegler-Nichols", ZieglerNicholsTuner())
        self.register("Cohen-Coon", CohenCoonTuner())
        self.register("IMC", IMCTuner())
        self.register("Frequency-Response", FrequencyResponseTuner())

    def register(self, name: str, strategy: TuningStrategy) -> None:
        """注册策略"""
        self._strategies[name] = strategy

    def compute(self, name: str, metrics: SystemMetrics) -> PIDParams:
        """执行指定策略"""
        strategy = self._strategies.get(name)
        if strategy is None:
            return PIDParams(info=f"未知策略: {name}", source="error", valid=False)
        return strategy.compute(metrics)

    def compute_all(self, metrics: SystemMetrics) -> dict[str, PIDParams]:
        """对所有已注册策略各算一组参数，供多方法对比。"""
        return {name: strat.compute(metrics) for name, strat in self._strategies.items()}

    def list_strategies(self) -> list[str]:
        """列出已注册策略"""
        return list(self._strategies.keys())

    def get_strategy(self, name: str) -> Optional[TuningStrategy]:
        """获取策略实例"""
        return self._strategies.get(name)
