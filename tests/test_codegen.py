"""test_codegen.py — AI 代码生成的纯逻辑部分"""
import os, tempfile
import pytest
from power_scope.llm import codegen


class FakeProfile:
    name = "TestDev"; device_type = "microinverter"
    class _V:
        def __init__(s, n): s.name = n
    variables = [_V("Vdc"), _V("Id")]
    control_buttons = []
    tuning = {"loops": [{"id": "id_loop"}]}


def test_profile_summary():
    s = codegen.profile_summary(FakeProfile())
    assert "TestDev" in s and "Vdc" in s and "id_loop" in s


def test_build_prompts():
    p = codegen.build_test_prompt(FakeProfile(), "验证写参数经护栏限幅")
    assert "测试场景" in p and "护栏" in p
    assert "任务" in codegen.build_script_prompt(FakeProfile(), "批量读变量")


def test_extract_code_block():
    text = "好的：\n```python\ndef test_x():\n    assert 1\n```\n完成"
    assert codegen.extract_code_block(text) == "def test_x():\n    assert 1"
    # 无围栏
    assert codegen.extract_code_block("assert 2") == "assert 2"
    assert codegen.extract_code_block("") == ""


def test_save_generated():
    with tempfile.TemporaryDirectory() as d:
        path = codegen.save_generated("def test_a():\n    assert True", "my scenario", base_dir=d)
        assert os.path.basename(path) == "test_my_scenario.py"
        content = open(path, encoding="utf-8").read()
        assert "def test_a" in content and content.startswith("#")


def test_generate_test_with_fake_engine():
    class FakeResp:
        text = "```python\ndef test_gen():\n    assert True\n```"
        success = True; error = ""
    class FakeEngine:
        def chat(self, prompt, context=None): return FakeResp()
    out = codegen.generate_test(FakeEngine(), FakeProfile(), "场景X")
    assert out["code"] == "def test_gen():\n    assert True"
    assert out["error"] == ""
