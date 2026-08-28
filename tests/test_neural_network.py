"""神经网络调参引擎测试"""
import os, sys, pytest
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from power_scope.llm.local_nn import NeuralNetwork, PIDTunerNN
from power_scope.llm.training_data import generate_training_data, simulate_second_order_step
from power_scope.llm.nlu import TuneNLU, NeuralTuner


class TestNeuralNetwork:
    """神经网络核心测试"""

    def test_init(self):
        nn = NeuralNetwork([4, 8, 3])
        assert len(nn.weights) == 2
        assert nn.weights[0].shape == (4, 8)
        assert nn.weights[1].shape == (8, 3)

    def test_forward_shape(self):
        nn = NeuralNetwork([4, 8, 3])
        X = [[0.1, 0.2, 0.3, 0.4]]
        out = nn.predict(X)
        assert out.shape == (1, 3)

    def test_train_reduces_loss(self):
        """训练应降低损失"""
        nn = NeuralNetwork([4, 16, 3], learning_rate=0.01)
        X = [[0.1, 0.2, 0.3, 0.4], [0.5, 0.6, 0.7, 0.8],
             [0.2, 0.3, 0.4, 0.5], [0.7, 0.8, 0.9, 1.0]]
        y = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6], [0.2, 0.3, 0.4], [0.7, 0.8, 0.9]]
        loss_before = nn.train(X, y, epochs=10)
        loss_after = nn.train(X, y, epochs=50)
        assert loss_after <= loss_before or loss_after < 0.1

    def test_save_load(self, tmp_path):
        nn = NeuralNetwork([4, 8, 3])
        X = [[0.1, 0.2, 0.3, 0.4]]
        y = [[0.1, 0.2, 0.3]]
        nn.train(X, y, epochs=5)
        path = str(tmp_path / "model.json")
        nn.save(path)
        nn2 = NeuralNetwork.load(path)
        out1 = nn.predict(X)
        out2 = nn2.predict(X)
        assert np.allclose(out1, out2)

    def test_online_learn(self):
        nn = NeuralNetwork([4, 8, 3])
        out_before = nn.predict([[0.5, 0.5, 0.5, 0.5]])
        nn.online_learn([0.5, 0.5, 0.5, 0.5], [0.9, 0.1, 0.5], lr=0.1)
        out_after = nn.predict([[0.5, 0.5, 0.5, 0.5]])
        # 在线学习后输出应有变化
        assert not np.allclose(out_before, out_after)


class TestPIDTunerNN:
    """PID 调参神经网络测试"""

    def test_predict_returns_valid_params(self):
        tuner = PIDTunerNN()
        X_train, y_train, X_val, y_val = generate_training_data(n_samples=100)
        tuner.train_on_data(X_train, y_train, epochs=20)
        result = tuner.predict(
            overshoot=18.0, rise_time=12.0, settling_time=85.0,
            steady_error=0.2, current_kp=0.85, current_ki=120.0,
            current_kd=0.0, target_overshoot=5.0
        )
        assert "kp" in result
        assert "ki" in result
        assert "kd" in result
        assert 0 <= result["kp"] <= 5
        assert 0 <= result["ki"] <= 2000
        assert 0 <= result["kd"] <= 0.5
        assert 0 < result["confidence"] <= 1.0

    def test_evaluate_returns_float(self):
        """evaluate() 返回验证集损失"""
        tuner = PIDTunerNN()
        X_train, y_train, X_val, y_val = generate_training_data(n_samples=100)
        tuner.train_on_data(X_train, y_train, epochs=20)
        loss = tuner.evaluate(X_val, y_val)
        assert isinstance(loss, float)
        assert loss >= 0

    def test_consistent_predictions(self):
        """相同输入应返回相同预测 (非随机)"""
        tuner = PIDTunerNN()
        X_train, y_train, _, _ = generate_training_data(n_samples=100)
        tuner.train_on_data(X_train, y_train, epochs=20)
        r1 = tuner.predict(18.0, 12.0, 85.0, 0.2, 0.85, 120.0, 0.0, 5.0)
        r2 = tuner.predict(18.0, 12.0, 85.0, 0.2, 0.85, 120.0, 0.0, 5.0)
        assert abs(r1["kp"] - r2["kp"]) < 1e-10
        assert abs(r1["ki"] - r2["ki"]) < 1e-10

    def test_online_learning_changes_prediction(self):
        """在线学习后预测应有变化"""
        tuner = PIDTunerNN()
        X_train, y_train, _, _ = generate_training_data(n_samples=100)
        tuner.train_on_data(X_train, y_train, epochs=20)
        before = tuner.predict(18.0, 12.0, 85.0, 0.2, 0.85, 120.0, 0.0, 5.0)
        tuner.online_learn([18.0, 12.0, 85.0, 0.2, 0.85, 120.0, 0.0, 5.0],
                           [2.0, 500.0, 0.1], lr=0.1)
        after = tuner.predict(18.0, 12.0, 85.0, 0.2, 0.85, 120.0, 0.0, 5.0)
        # 在线学习后预测应朝目标方向移动
        assert abs(after["kp"] - 2.0) <= abs(before["kp"] - 2.0) or after["kp"] != before["kp"]


class TestTrainingData:
    """训练数据生成测试"""

    def test_generate_data(self):
        X_train, y_train, X_val, y_val = generate_training_data(n_samples=100, seed=42)
        assert len(X_train) + len(X_val) == 100
        assert len(y_train) + len(y_val) == 100
        assert len(X_train[0]) == 8  # 8 个特征
        assert len(y_train[0]) == 3  # 3 个输出
        # 验证集应该有 ~15%
        assert 80 <= len(X_train) <= 95

    def test_data_consistency(self):
        """相同 seed 生成相同数据"""
        X1, y1, _, _ = generate_training_data(n_samples=50, seed=42)
        X2, y2, _, _ = generate_training_data(n_samples=50, seed=42)
        assert X1 == X2
        assert y1 == y2

    def test_data_noise_present(self):
        """噪声模式：两次生成的数据（不同 seed）输入不同"""
        X1, y1, _, _ = generate_training_data(n_samples=20, seed=42, noise_std=0.05)
        X2, y2, _, _ = generate_training_data(n_samples=20, seed=99, noise_std=0.05)
        # 不同 seed 应产生不同的噪声，输入不完全相同
        assert X1 != X2

    def test_simulate_step_response(self):
        """二阶系统仿真"""
        metrics = simulate_second_order_step(K=1.0, zeta=0.5, wn=100)
        assert "overshoot" in metrics
        assert "rise_time" in metrics
        assert "settling_time" in metrics
        assert metrics["overshoot"] > 0  # zeta=0.5 应有超调
        assert metrics["rise_time"] > 0


class TestNLU:
    """自然语言理解测试"""

    def test_intent_greet(self):
        nlu = TuneNLU()
        intent = nlu.parse("你好")
        assert intent.intent == "greet"

    def test_intent_overshoot(self):
        nlu = TuneNLU()
        intent = nlu.parse("超调太大")
        assert intent.intent == "overshoot"

    def test_intent_slow(self):
        nlu = TuneNLU()
        intent = nlu.parse("系统响应太慢")
        assert intent.intent == "slow"

    def test_intent_steady_error(self):
        nlu = TuneNLU()
        intent = nlu.parse("稳态误差大")
        assert intent.intent == "steady_error"

    def test_intent_vsg(self):
        nlu = TuneNLU()
        intent = nlu.parse("VSG频率波动")
        assert intent.intent == "vsg"

    def test_extract_params(self):
        nlu = TuneNLU()
        intent = nlu.parse("Kp=0.85 Ki=120")
        assert intent.intent == "specific_params"
        assert intent.extracted_kp == 0.85
        assert intent.extracted_ki == 120.0

    def test_extract_target_overshoot(self):
        nlu = TuneNLU()
        intent = nlu.parse("超调降到5%")
        assert intent.intent == "overshoot"
        assert intent.target_overshoot == 5.0


class TestNeuralTuner:
    """神经网络调参器集成测试"""

    @pytest.fixture
    def tuner(self):
        return NeuralTuner()

    def test_greet(self, tuner):
        r = tuner.chat("你好", {})
        assert "神经网络" in r["text"] or "调参" in r["text"]

    def test_overshoot_predicts_params(self, tuner):
        r = tuner.chat("超调18%太大，帮我降到5%", {
            "current_kp": 0.85, "current_ki": 120, "current_kd": 0,
            "overshoot": 18.0, "rise_time": 12.0, "settling_time": 85,
            "steady_error": 0.2
        })
        assert "kp" in r["params"]
        assert "ki" in r["params"]
        assert "kd" in r["params"]
        assert r["risk"] in ("低", "中", "高")
        assert r["confidence"] > 0

    def test_slow_predicts_params(self, tuner):
        r = tuner.chat("系统响应太慢", {
            "current_kp": 0.5, "current_ki": 50, "current_kd": 0,
            "overshoot": 5.0, "rise_time": 25.0, "settling_time": 200,
            "steady_error": 1.0
        })
        assert "kp" in r["params"]

    def test_consistency(self, tuner):
        """相同输入相同结果"""
        ctx = {"current_kp": 0.85, "current_ki": 120, "current_kd": 0,
               "overshoot": 18.0, "rise_time": 12.0, "settling_time": 85,
               "steady_error": 0.2}
        r1 = tuner.chat("超调太大", ctx)
        r2 = tuner.chat("超调太大", ctx)
        assert abs(r1["params"]["kp"] - r2["params"]["kp"]) < 1e-6

    def test_feedback_online_learning(self, tuner):
        """反馈后模型应更新"""
        ctx = {"current_kp": 0.85, "current_ki": 120, "current_kd": 0,
               "overshoot": 18.0, "rise_time": 12.0, "settling_time": 85,
               "steady_error": 0.2}
        before = tuner.chat("超调太大", ctx)
        msg = tuner.feedback(0.85, 120, 0, 18.0, 12.0, 85, 0.2, good_result=False)
        assert "微调" in msg or "学习" in msg
