"""test_sim_stability.py — 阶段1 调参可用性加固回归

覆盖:
  - power_simulator 精确 ZOH 离散对刚性/高频对象的数值稳定性
  - compare_pid 整定前后闭环对比
  - tuning_engine valid 标志与 ZN 公式合理性
  - step_response.to_system_metrics 的 identified 标志
"""
import numpy as np
import pytest

from power_scope.core.power_simulator import (
    simulate_step, compare_pid, PlantModel, PRESET_PLANTS,
)
from power_scope.core.tuning_engine import TuningEngine, SystemMetrics
from power_scope.core.step_response import StepMetrics


# ---------------- 数值稳定性 ----------------

@pytest.mark.parametrize("wn", [2000.0, 6000.0, 15000.0])
def test_second_order_high_wn_stable(wn):
    """高自然频率二阶对象用大步长不发散（旧显式欧拉会炸）。"""
    plant = PlantModel.second_order(K=1.0, zeta=0.3, wn=wn)
    t, y = simulate_step(plant, 0.5, 50.0, 0.0, amplitude=1.0, duration=0.05, dt=1e-4)
    assert np.all(np.isfinite(y))
    assert np.max(np.abs(y)) < 10.0  # 有界


@pytest.mark.parametrize("T", [5e-4, 5e-5])
def test_first_order_stiff_stable(T):
    """时间常数小于步长(dt>T)的刚性一阶不发散。"""
    plant = PlantModel.first_order(K=1.0, T=T)
    t, y = simulate_step(plant, 0.5, 100.0, 0.0, amplitude=1.0, duration=0.02, dt=1e-4)
    assert np.all(np.isfinite(y))
    assert np.max(np.abs(y)) < 10.0


def test_all_presets_finite():
    """所有内置预设对象在默认 PID 下仿真都有界。"""
    for name, plant in PRESET_PLANTS.items():
        t, y = simulate_step(plant, 0.5, 20.0, 0.0, amplitude=1.0, duration=0.1, dt=1e-4)
        assert np.all(np.isfinite(y)), name


def test_output_grid_matches_requested_dt():
    """内部细分后输出仍重采样回请求栅格。"""
    plant = PlantModel.first_order(K=1.0, T=1e-4)  # 触发细分
    t, y = simulate_step(plant, 0.5, 50.0, 0.0, amplitude=1.0, duration=0.01, dt=1e-4)
    assert len(t) == int(round(0.01 / 1e-4)) + 1


# ---------------- compare_pid ----------------

def test_compare_pid_structure():
    plant = PlantModel.first_order(1.0, 0.01, 0.001)
    r = compare_pid(plant, (0.2, 5.0, 0.0), (0.8, 60.0, 0.0), amplitude=1.0)
    assert set(r["old"].keys()) == {"t", "y", "metrics"}
    assert r["duration"] > 0 and r["dt"] > 0
    assert len(r["old"]["t"]) == len(r["old"]["y"])


def test_compare_pid_better_gains_faster():
    """更强的增益应缩短上升时间（对比图有区分度）。"""
    plant = PlantModel.first_order(1.0, 0.02, 0.001)
    r = compare_pid(plant, (0.1, 2.0, 0.0), (1.0, 80.0, 0.0), amplitude=1.0)
    old_rise = r["old"]["metrics"].rise_time_ms
    new_rise = r["new"]["metrics"].rise_time_ms
    assert new_rise < old_rise


# ---------------- tuning_engine valid 标志 ----------------

def test_zn_invalid_when_no_gain():
    eng = TuningEngine()
    res = eng.compute("Ziegler-Nichols", SystemMetrics(K=0.0, T=0.0, L=0.0))
    assert res.valid is False


def test_cohencoon_imc_invalid_without_delay():
    eng = TuningEngine()
    for name in ("Cohen-Coon", "IMC"):
        res = eng.compute(name, SystemMetrics(K=1.0, T=0.02, L=0.0))
        assert res.valid is False, name


def test_zn_reasonable_positive_gains():
    """ZN 反应曲线式给出正的、有限的 PID。"""
    eng = TuningEngine()
    res = eng.compute("Ziegler-Nichols", SystemMetrics(K=1.0, T=0.02, L=0.002))
    assert res.valid is True
    assert res.kp > 0 and res.ki > 0 and res.kd >= 0
    assert np.isfinite([res.kp, res.ki, res.kd]).all()


def test_zn_no_blowup_tiny_L():
    """L 极小时 ZN 不产生爆炸增益（下限保护）。"""
    eng = TuningEngine()
    res = eng.compute("Ziegler-Nichols", SystemMetrics(K=1.0, T=0.02, L=1e-9))
    assert np.isfinite(res.kp) and res.kp < 1e4


def test_compute_all_returns_all_strategies():
    eng = TuningEngine()
    out = eng.compute_all(SystemMetrics(K=1.0, T=0.02, L=0.002))
    assert set(out.keys()) == set(eng.list_strategies())


# ---------------- step_response identified 标志 ----------------

def test_identified_true_when_valid():
    m = StepMetrics(valid=True, K=0.5, T=0.01, L=0.001)
    sm = m.to_system_metrics()
    assert sm.identified is True


def test_identified_false_on_fallback():
    """辨识无效 → identified=False，且回退默认值。"""
    m = StepMetrics(valid=False)
    sm = m.to_system_metrics()
    assert sm.identified is False
    assert sm.K == 1.0 and abs(sm.T - 0.025) < 1e-9
