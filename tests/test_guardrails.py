"""test_guardrails.py — 安全护栏测试"""
import pytest
from power_scope.core.guardrails import Guardrails, GuardrailsResult
from power_scope.config.device_profile import VarBinding, DeviceProfile


class TestGuardrailsBasic:
    def test_create_without_profile(self):
        gr = Guardrails()
        assert gr is not None

    def test_validate_no_profile_no_limits(self):
        gr = Guardrails()
        result = gr.validate("Kp", 150.0)
        assert result.allowed is True
        assert result.clamped_value == 150.0
        assert result.message == "OK"
        assert result.previous_value is None

    def test_record_and_get_last(self):
        gr = Guardrails()
        gr.record("Kp", 10.0)
        assert gr.get_last_value("Kp") == 10.0
        gr.record("Kp", 20.0)
        assert gr.get_last_value("Kp") == 20.0

    def test_rollback_no_history(self):
        gr = Guardrails()
        assert gr.rollback("Kp") is None

    def test_rollback_with_history(self):
        gr = Guardrails()
        gr.record("Kp", 10.0)
        gr.record("Kp", 20.0)
        assert gr.rollback("Kp") == 10.0

    def test_history_limit(self):
        gr = Guardrails()
        for i in range(1100):
            gr.record("Kp", float(i))
        history = gr.get_history("Kp")
        assert len(history) <= 600  # 截断后追加，不会超过 600
        assert len(history) > 500   # 至少保留了 500 条
        # 截断保留的是最后 500 条（501-1000），然后追加 1001-1099
        assert history[0][1] == 501.0  # 截断后第一条（history条目格式: (timestamp, value)）


class TestGuardrailsWithProfile:
    @pytest.fixture
    def profile(self):
        return DeviceProfile(
            name="TestDevice",
            device_type="test",
            version="1.0",
            variables=[
                VarBinding(
                    name="Kp", elf_symbol="gKp", display_name="比例增益",
                    unit="", scale=1.0, offset=0, min_val=0, max_val=100, precision=2,
                ),
                VarBinding(
                    name="Ki", elf_symbol="gKi", display_name="积分增益",
                    unit="", scale=1.0, offset=0, min_val=0, max_val=10, precision=2,
                ),
            ],
        )

    def test_clamp_upper(self, profile):
        gr = Guardrails(profile)
        result = gr.validate("Kp", 150.0)
        assert result.allowed is True
        assert result.clamped_value == 100.0
        assert "上限幅" in result.message
        assert result.original_value == 150.0

    def test_clamp_lower(self, profile):
        gr = Guardrails(profile)
        result = gr.validate("Kp", -10.0)
        assert result.clamped_value == 0.0
        assert "下限幅" in result.message

    def test_no_clamp_within_range(self, profile):
        gr = Guardrails(profile)
        result = gr.validate("Kp", 50.0)
        assert result.clamped_value == 50.0
        assert result.message == "OK"

    def test_rate_limit(self, profile):
        gr = Guardrails(profile)
        gr.record("Kp", 10.0)
        result = gr.validate("Kp", 50.0, max_rate=20.0)
        assert result.clamped_value == 30.0  # 10 + 20
        assert "增幅限制" in result.message

    def test_rate_limit_negative_direction(self, profile):
        gr = Guardrails(profile)
        gr.record("Kp", 50.0)
        result = gr.validate("Kp", 10.0, max_rate=20.0)
        assert result.clamped_value == 30.0  # 50 - 20
        assert "增幅限制" in result.message

    def test_rate_limit_no_previous(self, profile):
        gr = Guardrails(profile)
        result = gr.validate("Kp", 50.0, max_rate=20.0)
        assert result.clamped_value == 50.0  # 无前值，不限制
        assert result.message == "OK"

    def test_clamp_and_rate_limit_combined(self, profile):
        gr = Guardrails(profile)
        gr.record("Kp", 10.0)
        # 请求 150 -> 先限幅到 100，再增幅限制到 30
        result = gr.validate("Kp", 150.0, max_rate=20.0)
        assert result.clamped_value == 30.0
        assert "上限幅" in result.message
        assert "增幅限制" in result.message

    def test_rollback_uses_history(self, profile):
        gr = Guardrails(profile)
        gr.record("Kp", 10.0)
        gr.record("Kp", 20.0)
        gr.record("Kp", 30.0)
        assert gr.rollback("Kp") == 20.0

    def test_rollback_single_history(self, profile):
        gr = Guardrails(profile)
        gr.record("Kp", 10.0)
        assert gr.rollback("Kp") is None

    def test_unknown_var_no_limits(self, profile):
        gr = Guardrails(profile)
        result = gr.validate("UnknownVar", 500.0)
        assert result.clamped_value == 500.0
        assert result.message == "OK"
