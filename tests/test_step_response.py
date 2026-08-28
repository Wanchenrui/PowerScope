"""test_step_response.py — 阶跃响应指标提取 (Task 2 Slice 1, TDD)

StepResponseAnalyzer 把一段 (t, 反馈值) 采样 + 阶跃信息 → 超调/上升/调节/稳态误差
+ 等效 FOPDT(K/T/L)，喂给现有 TuningEngine。纯函数、无 Qt、无硬件。
"""
from __future__ import annotations

import math
import pytest


def _first_order(t_step, y0, delta, T, L, dt=0.001, total=0.6):
    """一阶+纯滞后阶跃响应采样 [(t, y)]，含阶跃前稳态段。"""
    out = []
    for k in range(int(total / dt)):
        t = k * dt
        tau = t - t_step - L
        y = y0 if tau <= 0 else y0 + delta * (1.0 - math.exp(-tau / T))
        out.append((t, y))
    return out


def _second_order(t_step, y0, delta, zeta, wn, dt=0.0005, total=1.0):
    """欠阻尼二阶阶跃响应，超调 = exp(-pi*zeta/sqrt(1-zeta^2))。"""
    out = []
    wd = wn * math.sqrt(1 - zeta * zeta)
    phi = math.acos(zeta)
    for k in range(int(total / dt)):
        t = k * dt
        tau = t - t_step
        if tau <= 0:
            y = y0
        else:
            y = y0 + delta * (1.0 - math.exp(-zeta * wn * tau) /
                              math.sqrt(1 - zeta * zeta) * math.sin(wd * tau + phi))
        out.append((t, y))
    return out


@pytest.fixture
def analyze():
    from power_scope.core.step_response import analyze_step
    return analyze_step


class TestFirstOrder:
    def test_identifies_T_and_L(self, analyze):
        s = _first_order(t_step=0.05, y0=10.0, delta=2.0, T=0.05, L=0.01)
        m = analyze(s, t_step=0.05, input_step=2.0)
        assert m.valid
        assert m.overshoot_pct < 1.0
        assert abs(m.T - 0.05) < 0.008
        assert abs(m.L - 0.01) < 0.006
        assert abs(m.K - 1.0) < 0.05

    def test_rise_and_settling_time(self, analyze):
        s = _first_order(t_step=0.05, y0=0.0, delta=1.0, T=0.05, L=0.0)
        m = analyze(s, t_step=0.05, input_step=1.0)
        assert abs(m.rise_time_ms - 109.9) < 8.0      # 一阶 10-90% ≈ 2.197T
        assert abs(m.settling_time_ms - 195.6) < 12.0  # 2% 调节 ≈ 3.912T

    def test_steady_error_when_undertracking(self, analyze):
        s = _first_order(t_step=0.05, y0=0.0, delta=1.8, T=0.03, L=0.0)
        m = analyze(s, t_step=0.05, input_step=2.0)   # 命令2 实到1.8 → 误差10%
        assert abs(m.steady_error_pct - 10.0) < 1.5


class TestSecondOrder:
    def test_overshoot_matches_zeta(self, analyze):
        s = _second_order(t_step=0.1, y0=5.0, delta=3.0, zeta=0.5, wn=100.0)
        m = analyze(s, t_step=0.1, input_step=3.0)
        assert abs(m.overshoot_pct - 16.3) < 3.0      # zeta=0.5 → ~16.3%
        assert m.rise_time_ms > 0


class TestEdgeCases:
    def test_no_response_is_invalid(self, analyze):
        s = [(k * 0.001, 7.0) for k in range(200)]
        m = analyze(s, t_step=0.05, input_step=1.0)
        assert not m.valid

    def test_too_few_samples_invalid(self, analyze):
        m = analyze([(0.0, 1.0), (0.01, 1.0)], t_step=0.0, input_step=1.0)
        assert not m.valid

    def test_negative_step_normalized(self, analyze):
        s = _first_order(t_step=0.05, y0=10.0, delta=-2.0, T=0.04, L=0.0)
        m = analyze(s, t_step=0.05, input_step=-2.0)
        assert m.valid
        assert m.overshoot_pct < 1.0
        assert abs(m.T - 0.04) < 0.008
        assert abs(m.K - 1.0) < 0.05

    def test_to_system_metrics_feeds_engine(self, analyze):
        from power_scope.core.tuning_engine import TuningEngine
        s = _first_order(t_step=0.05, y0=0.0, delta=1.0, T=0.05, L=0.01)
        sm = analyze(s, t_step=0.05, input_step=1.0).to_system_metrics()
        pid = TuningEngine().compute("IMC", sm)
        assert pid.source == "IMC"
        assert pid.kp > 0


class TestStepLoopConfig:
    """profile 环路阶跃配置解析(Slice 2)：setpoint/feedback/step_default/step_max。"""

    def _parse(self, loop):
        from power_scope.core.step_response import parse_step_loop
        return parse_step_loop(loop)

    def test_full_loop_parsed(self):
        cfg = self._parse({
            "id": "inv_curr_freq", "label": "逆变电流环(频率)",
            "params": {"Kp": "inv_curr_freq_kp", "Ki": "inv_curr_freq_ki", "Kd": None},
            "setpoint": "inv_curr_ref", "feedback": "inv_current_out",
            "step_default": 0.5, "step_max": 2.0,
        })
        assert cfg.loop_id == "inv_curr_freq"
        assert cfg.setpoint == "inv_curr_ref"
        assert cfg.feedback == "inv_current_out"
        assert cfg.step_default == 0.5
        assert cfg.step_max == 2.0
        assert cfg.params["Kp"] == "inv_curr_freq_kp"
        assert cfg.ready_for_active_step is True

    def test_minimal_loop_not_ready_for_active_step(self):
        cfg = self._parse({"id": "spll", "label": "PLL", "params": {"Kp": "spll_kp"}})
        assert cfg.setpoint == ""
        assert cfg.feedback == ""
        assert cfg.step_max == 0.0
        assert cfg.step_default == 1.0          # 缺省默认
        assert cfg.ready_for_active_step is False

    def test_clamp_amplitude_respects_step_max(self):
        cfg = self._parse({"id": "x", "setpoint": "s", "feedback": "f", "step_max": 2.0})
        assert cfg.clamp_amplitude(5.0) == 2.0
        assert cfg.clamp_amplitude(-5.0) == -2.0
        assert cfg.clamp_amplitude(1.5) == 1.5

    def test_clamp_zero_when_step_max_unset(self):
        cfg = self._parse({"id": "x"})
        assert cfg.clamp_amplitude(3.0) == 0.0   # 未配 step_max → 禁止主动写

    def test_bad_numbers_fall_back(self):
        cfg = self._parse({"id": "x", "step_default": "oops", "step_max": -9})
        assert cfg.step_default == 1.0
        assert cfg.step_max == 0.0               # 负值钳到0