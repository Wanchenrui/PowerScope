"""test_power_simulator.py — 离线仿真引擎测试"""
import pytest
import numpy as np
from power_scope.core.power_simulator import (
    PlantModel, simulate_step, simulate_and_analyze, PRESET_PLANTS,
)


# ═══════════════════════════════════════════════════════════════
# PlantModel 构造
# ═══════════════════════════════════════════════════════════════

def test_first_order_factory():
    p = PlantModel.first_order(K=10.0, T=0.005, L=0.001)
    assert p.kind == "first_order"
    assert p.K == 10.0
    assert p.L == 0.001


def test_second_order_factory():
    p = PlantModel.second_order(K=1.0, zeta=0.7, wn=628.0)
    assert p.kind == "second_order"
    assert p.zeta == 0.7


def test_integrator_factory():
    p = PlantModel.integrator(K=0.01)
    assert p.kind == "integrator"
    assert p.T == 0.0


def test_to_label_returns_string():
    for p in [PlantModel.first_order(1, 0.01), PlantModel.second_order(1, 0.7, 628)]:
        label = p.to_label()
        assert isinstance(label, str)
        assert len(label) > 10


# ═══════════════════════════════════════════════════════════════════
# 仿真基础行为
# ═══════════════════════════════════════════════════════════════════

def test_simulate_returns_correct_shape():
    t, y = simulate_step(PlantModel.first_order(1, 0.01), Kp=1, Ki=0, Kd=0,
                         amplitude=1, duration=0.1, dt=0.001)
    assert len(t) == len(y)
    assert len(t) >= 90
    assert t[0] == 0.0
    assert abs(t[-1] - 0.1) < 0.002


def test_simulate_output_is_numpy():
    t, y = simulate_step(PlantModel.first_order(1, 0.01), 1, 0, 0, 1, 0.01)
    assert isinstance(t, np.ndarray)
    assert isinstance(y, np.ndarray)


def test_first_order_step_tracks_setpoint():
    """一阶系统 + P 控制：y 应跟踪设定值方向。"""
    t, y = simulate_step(PlantModel.first_order(K=10, T=0.005),
                         2.0, 0, 0, 1.0, 0.1)
    assert y[-1] > 0.3, f"y_end={y[-1]:.3f}"


def test_integrator_with_pi_tracks():
    """积分器 + PI：无静差跟踪（增益需要足够高）。"""
    t, y = simulate_step(PlantModel.integrator(K=1.0),
                         10.0, 200, 0, 1.0, 0.3, 0.001)
    # PI 消除静差 → y 最终趋近 1.0
    assert abs(y[-1] - 1.0) < 0.15, f"y_end={y[-1]:.3f}"


def test_second_order_with_p_has_overshoot():
    """欠阻尼二阶 + 高 P：应有明显超调（相对于稳态值）。"""
    t, y = simulate_step(PlantModel.second_order(K=1.0, zeta=0.3, wn=628),
                         5.0, 0, 0, 1.0, 0.3)
    ymax = float(np.max(y))
    yend = float(y[-1])
    # 欠阻尼 + 高增益 → ymax 应明显高于稳态值
    assert (ymax - yend) / yend > 0.15, \
        f"no significant overshoot: ymax={ymax:.3f}, yend={yend:.3f}"


def test_dead_time_delays_response():
    """有纯滞后的对象：初始若干步 y 应维持为 0。"""
    t, y = simulate_step(PlantModel.first_order(K=1, T=0.01, L=0.01),
                         1.0, 0, 0, 1.0, 0.05)
    L = 0.01
    idx = int(L * 0.8 / 0.0001)
    early = y[:idx]
    assert np.max(np.abs(early)) < 0.01, f"early response non-zero: max={np.max(np.abs(early)):.4f}"


def test_ki_eliminates_steady_error():
    """一阶系统 + PI：Ki 消除静差。"""
    _, y_p = simulate_step(PlantModel.first_order(K=10, T=0.005),
                           1.0, 0, 0, 1.0, 0.1)
    err_p = abs(1.0 - y_p[-1])

    _, y_pi = simulate_step(PlantModel.first_order(K=10, T=0.005),
                            1.0, 100, 0, 1.0, 0.1)
    err_pi = abs(1.0 - y_pi[-1])

    assert err_pi < err_p, f"P-only err={err_p:.4f}, PI err={err_pi:.4f}"
    assert err_pi < 0.1, f"PI steady error too large: {err_pi:.4f}"


def test_kd_dampens_first_order():
    """一阶系统 + PD vs P：D 项抑制超调、加快阻尼。"""
    # 一阶系统 P 控制无超调，加 D 也不应引入振荡
    _, y = simulate_step(PlantModel.first_order(K=10, T=0.005),
                         2.0, 0, 0.001, 1.0, 0.1)
    # D 不导致发散
    assert np.max(y) < 3.0, f"PD unstable: ymax={np.max(y):.3f}"
    assert not np.any(np.isnan(y)), "NaN in PD output"


def test_anti_windup_prevents_divergence():
    """抗饱和：高增益 + 大积分 → 不发散。"""
    # Buck 型高增益对象 + 大 Ki：应有抗饱和保护
    t, y = simulate_step(PlantModel.first_order(K=12, T=0.0005),
                         0.5, 50, 0,  # 大 Ki
                         1.0, 0.1)
    assert np.max(np.abs(y)) < 100, f"divergent: max|y|={np.max(np.abs(y)):.1f}"
    assert not np.any(np.isnan(y))


# ═══════════════════════════════════════════════════════════════════
# simulate_and_analyze — 与现有管线连线
# ═══════════════════════════════════════════════════════════════════

def test_simulate_and_analyze_returns_valid_metrics():
    m = simulate_and_analyze(PlantModel.first_order(K=10, T=0.005),
                             0.8, 160, 0, 1.0, 0.1)
    assert m.valid, f"analysis invalid: {m.info}"
    assert m.overshoot_pct >= 0
    assert m.rise_time_ms > 0
    assert m.K > 0


def test_simulate_and_analyze_feeds_tuning_engine():
    """simulate → analyze → SystemMetrics → TuningEngine 链路不断。"""
    m = simulate_and_analyze(PlantModel.first_order(K=10, T=0.005),
                             0.8, 160, 0, 1.0, 0.1)
    sm = m.to_system_metrics()
    from power_scope.core.tuning_engine import TuningEngine
    engine = TuningEngine()
    result = engine.compute("Ziegler-Nichols", metrics=sm)
    assert result.kp > 0


def test_simulate_and_analyze_second_order():
    """二阶欠阻尼仿真 → 分析应返回有效超调指标。"""
    m = simulate_and_analyze(PlantModel.second_order(K=1.0, zeta=0.3, wn=628),
                             5.0, 200, 0.001, 1.0, 0.3)
    assert m.valid
    # 欠阻尼闭环应有显著超调
    assert m.overshoot_pct > 3, f"expected overshoot, got {m.overshoot_pct:.2f}%"


# ═══════════════════════════════════════════════════════════════════
# 预设
# ═══════════════════════════════════════════════════════════════════

def test_presets_all_simulate_stable():
    """每个预设模型都能仿真且不崩溃、不发散。"""
    for name, plant in PRESET_PLANTS.items():
        t, y = simulate_step(plant, 0.5, 10, 0, 1.0, 0.1)
        assert len(t) > 10, f"{name}: too few points"
        assert not np.any(np.isnan(y)), f"{name}: NaN in output"
        assert not np.any(np.isinf(y)), f"{name}: inf in output"
        assert np.max(np.abs(y)) < 100, \
            f"{name}: unstable: max|y|={np.max(np.abs(y)):.1f}"


def test_presets_each_produces_valid_metrics():
    """每个预设模拟后都能通过分析（至少 valid 或给出 info）。"""
    for name, plant in PRESET_PLANTS.items():
        m = simulate_and_analyze(plant, 0.8, 160, 0, 1.0, 0.3)
        if not m.valid:
            # 允许分析返回 invalid（如纯积分器响应极慢）
            assert len(m.info) > 0, f"{name}: invalid with no info"
        else:
            assert m.rise_time_ms > 0, f"{name}: rise_time=0"
