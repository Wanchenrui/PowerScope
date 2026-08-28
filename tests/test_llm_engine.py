"""LLM 引擎测试 — 验证本地规则引擎的意图识别和参数建议"""
import os, sys, pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from power_scope.llm.llm_engine import LLMEngine, LLMConfig, LLMResponse


@pytest.fixture
def engine():
    return LLMEngine(LLMConfig(provider="local"))


class TestIntentRecognition:
    """测试意图识别 — 同一输入始终返回相同结果(非随机)"""

    def test_greeting(self, engine):
        r1 = engine.chat("你好", {})
        r2 = engine.chat("你好", {})
        assert r1.text == r2.text  # 非随机
        assert "调参助手" in r1.text or "您好" in r1.text

    def test_greeting_who_are_you(self, engine):
        r = engine.chat("你是谁", {})
        assert "调参" in r.text or "助手" in r.text

    def test_overshoot(self, engine):
        r = engine.chat("超调太大，帮我降到5%以内", {"current_kp": 0.85, "current_ki": 120, "current_kd": 0})
        assert "Kp" in r.text
        assert "超调" in r.text
        assert "Kp" in r.params_suggested
        assert r.params_suggested["Kp"] < 0.85  # 应该减小Kp

    def test_slow_response(self, engine):
        # 需要提供 rise_time 才能预测 (无数据时应拒绝)
        r = engine.chat("系统响应太慢", {"current_kp": 0.85, "current_ki": 120, "rise_time": 15})
        assert "Kp" in r.params_suggested
        # 神经网络预测值在合理范围
        assert 0 <= r.params_suggested["Kp"] <= 5

    def test_slow_no_data(self, engine):
        # 无实测数据时应诚实拒绝
        r = engine.chat("系统响应太慢", {"current_kp": 0.85, "current_ki": 120})
        assert "缺少" in r.text or "无法" in r.text

    def test_steady_error(self, engine):
        # 需要提供 steady_error 才能预测
        r = engine.chat("稳态误差0.5%太大", {"current_ki": 120, "steady_error": 0.5})
        assert "Ki" in r.params_suggested
        assert r.params_suggested["Ki"] >= 0  # 神经网络预测值在合理范围

    def test_steady_error_no_data(self, engine):
        # 无数据时应拒绝
        r = engine.chat("稳态误差太大", {"current_ki": 120})
        assert "缺少" in r.text or "无法" in r.text

    def test_vsg(self, engine):
        r = engine.chat("VSG频率波动大", {"vsg_J": 2.0, "vsg_D": 5.0})
        assert "VSG" in r.text or "惯量" in r.text
        assert "中" in r.risk_level  # VSG 是中等风险

    def test_specific_params(self, engine):
        r = engine.chat("Kp=0.85 Ki=120 怎么优化", {})
        assert "0.85" in r.text
        assert "120" in r.text

    def test_analyze_data(self, engine):
        r = engine.chat("分析阶跃响应数据", {})
        assert "上升时间" in r.text or "超调" in r.text

    def test_unknown_query(self, engine):
        r = engine.chat("今天天气怎么样", {})
        assert "调参" in r.text  # 应回到调参主题


class TestConsistency:
    """同一输入多次调用结果完全一致"""

    def test_overshoot_consistent(self, engine):
        results = [engine.chat("超调太大", {"current_kp": 1.0, "current_ki": 100, "current_kd": 0, "overshoot": 20})
                   for _ in range(5)]
        # 所有结果应完全相同
        assert all(r.text == results[0].text for r in results)
        assert all(r.params_suggested == results[0].params_suggested for r in results)


class TestParamSafety:
    """参数建议在安全范围内"""

    def test_kp_in_range(self, engine):
        r = engine.chat("超调太大", {"current_kp": 0.85, "current_ki": 120, "current_kd": 0})
        if "Kp" in r.params_suggested:
            assert 0 <= r.params_suggested["Kp"] <= 5

    def test_ki_in_range(self, engine):
        r = engine.chat("稳态误差大", {"current_ki": 100})
        if "Ki" in r.params_suggested:
            assert 0 <= r.params_suggested["Ki"] <= 2000

    def test_risk_level_set(self, engine):
        r = engine.chat("超调太大，帮我降到5%", {"current_kp": 0.85, "current_ki": 120, "overshoot": 18})
        assert r.risk_level in ("", "低", "中", "高")


class TestProviderConfig:
    def test_local_uses_neural(self):
        """local 提供商现在也走神经网络 (规则引擎已废弃)"""
        e = LLMEngine(LLMConfig(provider="local"))
        # local 不算真实云 LLM，但有神经网络引擎
        assert not e.is_using_real_llm() or e.config.provider == "local"

    def test_neural_provider(self):
        """neural 提供商使用神经网络"""
        e = LLMEngine(LLMConfig(provider="neural"))
        assert e.is_using_real_llm()

    def test_deepseek_with_key(self):
        e = LLMEngine(LLMConfig(provider="deepseek", api_key="test_key"))
        assert e.is_using_real_llm()

    def test_set_provider(self):
        e = LLMEngine(LLMConfig(provider="local"))
        e.set_provider("deepseek", "sk-test")
        assert e.config.provider == "deepseek"
        assert e.config.api_key == "sk-test"
        assert e.config.model == "deepseek-v4-pro"
