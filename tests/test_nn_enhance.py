"""test_nn_enhance.py — 阶段3C 本地NN增强：解析式指标/仿真标签/置信度校准/bug修复"""
import numpy as np
import pytest
from power_scope.llm.training_data import (
    simulate_second_order_step, second_order_time_metrics,
    generate_training_data, generate_simulation_training_data,
)
from power_scope.llm.local_nn import PIDTunerNN


@pytest.mark.parametrize("wn", [500, 5000, 20000])
@pytest.mark.parametrize("zeta", [0.1, 0.5, 1.0])
def test_analytical_metrics_stable(wn, zeta):
    """解析式二阶指标在任意 wn/阻尼下有限（旧显式欧拉会发散）。"""
    m = simulate_second_order_step(1.0, zeta, wn)
    assert np.isfinite(m["overshoot"]) and m["overshoot"] >= 0
    assert m["rise_time"] > 0 and m["settling_time"] > 0


def test_overshoot_monotonic_in_damping():
    """阻尼越小超调越大（物理正确性）。"""
    ov_low, _, _ = second_order_time_metrics(0.2, 1000)
    ov_high, _, _ = second_order_time_metrics(0.8, 1000)
    assert ov_low > ov_high


def test_generate_training_data_shape():
    Xtr, ytr, Xv, yv = generate_training_data(n_samples=40)
    assert len(Xtr) + len(Xv) == 40
    assert len(Xtr[0]) == 8 and len(ytr[0]) == 3
    assert np.all(np.isfinite(np.array(Xtr)))


def test_generate_simulation_training_data():
    Xtr, ytr, Xv, yv = generate_simulation_training_data(n_samples=6)
    assert len(Xtr[0]) == 8 and len(ytr[0]) == 3
    # 标签在安全范围
    for kp, ki, kd in ytr:
        assert 0 <= kp <= 5 and 0 <= ki <= 2000 and 0 <= kd <= 0.5


def test_confidence_calibration_uses_val_loss():
    nn = PIDTunerNN()
    # 低残差 → 高置信；高残差 → 低置信
    nn.set_val_loss(0.001)
    hi = nn.predict(18, 12, 100, 0.5, 0.85, 120, 0.0)["confidence"]
    nn.set_val_loss(0.2)
    lo = nn.predict(18, 12, 100, 0.5, 0.85, 120, 0.0)["confidence"]
    assert hi > lo
    assert 0.1 <= lo <= 0.95 and 0.1 <= hi <= 0.95


def test_train_response_no_longer_crashes():
    """回归：generate_training_data 返回4元组，_train_response 曾按2元组解包崩溃。"""
    from power_scope.llm.nlu import NeuralTuner
    import tempfile, os
    with tempfile.TemporaryDirectory() as d:
        tuner = NeuralTuner(model_path=os.path.join(d, "m.json"))
        out = tuner._train_response()   # 不应抛异常
        assert "训练" in out["text"]
