"""test_tuning_engine.py — TuningEngine 策略模式测试"""
import pytest
import numpy as np
from power_scope.core.tuning_engine import (
    TuningEngine, SystemMetrics, PIDParams,
    ZieglerNicholsTuner, CohenCoonTuner, IMCTuner, FrequencyResponseTuner,
)


class TestSystemMetrics:
    def test_default_values(self):
        m = SystemMetrics()
        assert m.overshoot == 0.0
        assert m.rise_time_ms == 0.0
        assert m.K == 1.0
        assert m.T == 0.025


class TestPIDParams:
    def test_clamp(self):
        p = PIDParams(kp=10.0, ki=5000.0, kd=1.0)
        c = p.clamp()
        assert c.kp == 5.0
        assert c.ki == 2000.0
        assert c.kd == 0.5

    def test_clamp_negative(self):
        p = PIDParams(kp=-1.0, ki=-10.0, kd=-0.1)
        c = p.clamp()
        assert c.kp == 0.0
        assert c.ki == 0.0
        assert c.kd == 0.0

    def test_clamp_custom_bounds(self):
        p = PIDParams(kp=10.0, ki=500.0, kd=0.1)
        c = p.clamp(kp_max=2.0, ki_max=100.0, kd_max=0.05)
        assert c.kp == 2.0
        assert c.ki == 100.0
        assert c.kd == 0.05


class TestZieglerNicholsTuner:
    def test_compute(self):
        t = ZieglerNicholsTuner()
        m = SystemMetrics(K=1.0, T=0.025, L=0.005)
        result = t.compute(m)
        assert result.kp > 0
        assert result.ki > 0
        assert result.kd > 0
        assert result.source == "Ziegler-Nichols"

    def test_name(self):
        t = ZieglerNicholsTuner()
        assert t.name() == "Ziegler-Nichols"


class TestCohenCoonTuner:
    def test_compute(self):
        t = CohenCoonTuner()
        m = SystemMetrics(K=1.0, T=0.025, L=0.005)
        result = t.compute(m)
        assert result.kp > 0
        assert result.ki > 0
        assert result.kd >= 0
        assert result.source == "Cohen-Coon"

    def test_invalid_params(self):
        t = CohenCoonTuner()
        m = SystemMetrics(K=1.0, T=0, L=0.005)
        result = t.compute(m)
        assert result.kp == 0
        assert "无效" in result.info


class TestIMCTuner:
    def test_compute(self):
        t = IMCTuner()
        m = SystemMetrics(K=1.0, T=0.025, L=0.005)
        result = t.compute(m)
        assert result.kp > 0
        assert result.ki > 0
        assert result.kd >= 0
        assert result.source == "IMC"

    def test_tau_c_factor(self):
        t = IMCTuner(tau_c_factor=0.2)
        m = SystemMetrics(K=1.0, T=0.025, L=0.005)
        result1 = t.compute(m)
        t2 = IMCTuner(tau_c_factor=1.0)
        result2 = t2.compute(m)
        # tau_c 越大，kp 越小
        assert result1.kp > result2.kp


class TestFrequencyResponseTuner:
    def test_compute_with_overshoot(self):
        t = FrequencyResponseTuner()
        m = SystemMetrics(overshoot=20.0, T=0.025, K=1.0)
        result = t.compute(m)
        assert result.kp > 0
        assert result.ki > 0
        assert result.source == "Frequency-Response"

    def test_compute_no_overshoot(self):
        t = FrequencyResponseTuner()
        m = SystemMetrics(T=0.025, K=1.0)
        result = t.compute(m)
        assert result.kp > 0
        assert result.ki > 0


class TestTuningEngine:
    def test_default_strategies(self):
        engine = TuningEngine()
        names = engine.list_strategies()
        assert "Ziegler-Nichols" in names
        assert "Cohen-Coon" in names
        assert "IMC" in names
        assert "Frequency-Response" in names

    def test_compute_all_strategies(self):
        engine = TuningEngine()
        m = SystemMetrics(K=1.0, T=0.025, L=0.005, overshoot=15.0)
        for name in engine.list_strategies():
            result = engine.compute(name, m)
            assert result.kp > 0, f"{name} failed: kp={result.kp}"
            assert result.ki > 0, f"{name} failed: ki={result.ki}"

    def test_unknown_strategy(self):
        engine = TuningEngine()
        result = engine.compute("Unknown", SystemMetrics())
        assert result.source == "error"
        assert "未知" in result.info

    def test_register_custom(self):
        engine = TuningEngine()
        
        class CustomTuner:
            def name(self):
                return "Custom"
            def compute(self, metrics):
                return PIDParams(kp=1.0, ki=2.0, kd=3.0, source="Custom")
        
        engine.register("Custom", CustomTuner())
        result = engine.compute("Custom", SystemMetrics())
        assert result.kp == 1.0
        assert result.ki == 2.0
        assert result.kd == 3.0

    def test_get_strategy(self):
        engine = TuningEngine()
        s = engine.get_strategy("IMC")
        assert s is not None
        assert s.name() == "IMC"
        assert engine.get_strategy("Unknown") is None
