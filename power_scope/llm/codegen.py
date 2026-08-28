"""codegen.py — 基于 LLM 的测试/脚本代码生成。

按当前设备 profile + 场景，生成 pytest 或 mock_mcu 交互脚本。提示词构建与
代码块提取为纯函数（可单测）；实际生成调用注入的 LLMEngine.chat()。
生成结果落到 tests/generated/，需人工 review 后保留。
"""
from __future__ import annotations
import os
import re


CODEGEN_SYSTEM = (
    "你是资深测试工程师，为 PowerScope（PySide6 + C 核心的串口调试/调参工具）编写"
    "可直接运行的 Python 测试或自动化脚本。要求：\n"
    "- 只输出一个 ```python 代码块，不要多余解释；\n"
    "- pytest 风格，函数名 test_ 开头，含清晰断言；\n"
    "- 不依赖真实硬件：用 mock_transport / Fake 对象；\n"
    "- 覆盖正常路径 + 至少一个边界/异常情况。"
)


def profile_summary(profile) -> str:
    """把 profile 关键信息压成提示词用的简要描述。"""
    try:
        vars_ = ", ".join(v.name for v in getattr(profile, "variables", [])[:12])
        btns = ", ".join(b.label for b in getattr(profile, "control_buttons", [])[:8])
        loops = getattr(profile, "tuning", {}).get("loops", []) if getattr(profile, "tuning", None) else []
        loop_ids = ", ".join(str(l.get("id", "")) for l in loops[:6])
    except Exception:
        vars_ = btns = loop_ids = ""
    return (
        f"设备: {getattr(profile, 'name', '?')} (类型 {getattr(profile, 'device_type', '?')})\n"
        f"变量: {vars_}\n"
        f"控制按钮: {btns}\n"
        f"调参环路: {loop_ids}"
    )


def build_test_prompt(profile, scenario: str) -> str:
    """构建"生成 pytest"的用户提示词。"""
    return (
        f"请为以下测试场景生成 pytest 测试代码。\n\n"
        f"[设备信息]\n{profile_summary(profile)}\n\n"
        f"[测试场景]\n{scenario}\n"
    )


def build_script_prompt(profile, task: str) -> str:
    """构建"生成自动化脚本"的用户提示词。"""
    return (
        f"请生成一个自动化脚本完成以下任务。\n\n"
        f"[设备信息]\n{profile_summary(profile)}\n\n"
        f"[任务]\n{task}\n"
    )


def extract_code_block(text: str) -> str:
    """从 LLM 回复里抽取第一个 ```python 代码块；没有围栏则原样返回 strip。"""
    if not text:
        return ""
    m = re.search(r"```(?:python|py)?\s*\n(.*?)```", text, re.DOTALL)
    if m:
        return m.group(1).strip("\n")
    return text.strip()


GENERATED_DIR = os.path.join("tests", "generated")


def save_generated(code: str, name: str, base_dir: str = None) -> str:
    """把生成代码写入 tests/generated/<name>.py（补全 .py 与前缀 test_）。返回路径。"""
    d = base_dir or GENERATED_DIR
    os.makedirs(d, exist_ok=True)
    safe = re.sub(r"[^0-9A-Za-z_]", "_", name).strip("_") or "generated"
    if not safe.startswith("test_"):
        safe = "test_" + safe
    if not safe.endswith(".py"):
        safe += ".py"
    path = os.path.join(d, safe)
    header = "# 由 PowerScope AI 代码生成 —— 请人工 review 后再纳入 CI\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(header + code + "\n")
    return path


def generate_test(engine, profile, scenario: str) -> dict:
    """调用注入的 LLMEngine 生成测试代码。返回 {code, raw, error}。"""
    prompt = build_test_prompt(profile, scenario)
    try:
        resp = engine.chat(prompt)
        code = extract_code_block(resp.text)
        return {"code": code, "raw": resp.text, "error": resp.error if not resp.success else ""}
    except Exception as e:  # noqa: BLE001
        return {"code": "", "raw": "", "error": str(e)}
