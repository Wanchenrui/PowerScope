"""
LLM 引擎 — 真实 LLM API 调用 + 无 Key 时的智能规则降级

支持提供商: DeepSeek / OpenAI / Claude / Ollama(本地)
降级模式: 无 API Key 时使用基于关键词和参数分析的规则引擎(非随机)
"""
import json
import re
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime


# 光伏微逆/储能调参专家系统提示词
SYSTEM_PROMPT = """你是光伏微逆变器与储能系统的功率控制软件调参专家。

你的职责:
1. 理解工程师的自然语言调参需求
2. 分析控制环路性能指标(超调/上升时间/稳态误差/相位裕度)
3. 给出具体的 PI/PID 参数调整建议
4. 评估参数修改的风险等级

专业知识领域:
- dq 解耦控制的电流内环(带宽通常 1-3kHz, Kp 典型 0.5-2.0, Ki 典型 50-500)
- 电压外环(带宽通常 50-200Hz, Kp 典型 0.1-1.0, Ki 典型 10-100)
- VSG 虚拟同步发电机(虚拟惯量 J: 0.1-5, 阻尼 D: 0.1-50)
- 功率环(有功/无功 PI 控制)

回复格式要求:
1. 先简短回应用户的问题(1-2句)
2. 给出具体参数建议: Kp/Ki/Kd 的旧值→新值
3. 预测效果: 超调/响应时间/稳态误差的变化
4. 风险评估: 低/中/高风险 + 原因
5. 如果用户问的不是调参问题，正常回答即可

安全规则:
- 单次参数变化幅度不超过当前值的 50%
- Kp 范围 0-5, Ki 范围 0-2000, Kd 范围 0-0.5
- 高风险(大幅改动)时建议先小幅试调

工具使用规范:
- 可调用只读工具获取实时数据(read_variable/get_waveform_stats/get_fault_codes/get_current_metrics)，据实分析，勿臆测数值。
- 需改参数或触发阶跃时，调用 propose_param_write / propose_step_test 提交'提议'。它们不会立即生效，工程师将在界面二次确认，且受安全护栏限幅。
- 严禁声称已写入或已生效；只能说'已提交建议，待确认'。
- 缺数据时先用只读工具获取，再给结论。
"""


@dataclass
class LLMMessage:
    role: str  # system / user / assistant
    content: str


@dataclass
class LLMConfig:
    provider: str = "deepseek"        # deepseek / openai / claude / ollama / local
    api_key: str = ""
    model: str = "deepseek-v4-pro"
    base_url: str = ""
    temperature: float = 0.3
    max_tokens: int = 1000
    thinking: bool = True           # DeepSeek v4 思考模式(deepseek-v4-pro/flash)
    reasoning_effort: str = "high"  # high | max


@dataclass
class LLMResponse:
    text: str
    success: bool
    error: str = ""
    provider_used: str = ""
    params_suggested: dict = field(default_factory=dict)  # {kp: 0.92, ki: 135, ...}
    risk_level: str = ""  # 低/中/高
    tool_trace: list = field(default_factory=list)  # 工具调用轨迹 [{name,result}]


class LLMEngine:
    """LLM 引擎: 真实 API 调用 + 智能降级"""

    PROVIDER_CONFIGS = {
        "deepseek": {
            "default_model": "deepseek-v4-pro",  # deepseek-chat 将于 2026/07/24 弃用
            "default_url": "https://api.deepseek.com/v1/chat/completions",
        },
        "openai": {
            "default_model": "gpt-4o-mini",
            "default_url": "https://api.openai.com/v1/chat/completions",
        },
        "claude": {
            "default_model": "claude-3-5-sonnet-20241022",
            "default_url": "https://api.anthropic.com/v1/messages",
        },
        "ollama": {
            "default_model": "qwen2:7b",
            "default_url": "http://localhost:11434/api/chat",
        },
        "neural": {
            "default_model": "local-nn-8-32-16-3",
            "default_url": "",
        },
        "local": {
            "default_model": "rule-engine",
            "default_url": "",
        },
    }

    def __init__(self, config: LLMConfig = None):
        self.config = config or LLMConfig()
        self._history: list[LLMMessage] = []
        self._max_history: int = 20  # 最多保留 20 轮对话
        self._max_retries: int = 3
        self._retry_delay_base: float = 1.0  # 基础退避秒数
        self._tool_executor = None  # 设置后启用 function-calling
        self._reset_history()

    def _reset_history(self):
        self._history = [LLMMessage("system", SYSTEM_PROMPT)]

    def _trim_history(self):
        """修剪历史，保留系统提示 + 最近 max_history 轮对话"""
        system_msgs = [m for m in self._history if m.role == "system"]
        other_msgs = [m for m in self._history if m.role != "system"]
        if len(other_msgs) > self._max_history * 2:
            # 保留最近 max_history 轮 (user + assistant = 2 * max_history)
            keep = other_msgs[-self._max_history * 2:]
            self._history = system_msgs + keep

    def set_provider(self, provider: str, api_key: str = "", model: str = ""):
        """配置 LLM 提供商"""
        self.config.provider = provider
        self.config.api_key = api_key
        cfg = self.PROVIDER_CONFIGS.get(provider, {})
        self.config.model = model or cfg.get("default_model", "")
        self.config.base_url = cfg.get("default_url", "")
        self._reset_history()

    def chat(self, user_message: str, context: dict = None) -> LLMResponse:
        """
        发送消息并获取回复

        Args:
            user_message: 用户输入
            context: 可选上下文 {current_kp, current_ki, current_kd, overshoot, rise_time, ...}

        Returns:
            LLMResponse
        """
        # 构建完整消息 (含上下文)
        full_msg = user_message
        if context:
            ctx_str = "\n\n[当前系统状态]\n"
            for k, v in context.items():
                ctx_str += f"  {k}: {v}\n"
            full_msg += ctx_str

        # 检查是否有 API Key (local/neural 模式除外)
        if self.config.provider in ("local", "neural") or not self.config.api_key:
            # local 和 neural 都走神经网络 (规则引擎已废弃，存在数据造假问题)
            return self._neural_response(user_message, context)

        # 调用真实 LLM API
        try:
            return self._call_api(full_msg)
        except Exception as e:
            # API 调用失败，降级到本地规则
            resp = self._local_response(user_message, context)
            resp.error = f"LLM API 调用失败: {e}，已降级为本地规则引擎"
            return resp

    def _call_api(self, message: str) -> LLMResponse:
        """调用真实 LLM API (带重试和退避，区分可重试/不可重试错误)"""
        import time
        from urllib.error import HTTPError

        self._trim_history()
        self._history.append(LLMMessage("user", message))

        last_error = None
        for attempt in range(self._max_retries):
            try:
                if self.config.provider == "claude":
                    return self._call_claude()
                elif self.config.provider == "ollama":
                    return self._call_ollama()
                else:
                    return self._call_openai_compatible()
            except HTTPError as e:
                # HTTP 状态码分类处理
                if e.code == 401:
                    # 鉴权失败 — 不可重试
                    self._history.pop()
                    return LLMResponse(
                        text="", success=False,
                        error=f"API 鉴权失败 (401): 请检查 API Key 是否正确",
                        provider_used=self.config.provider,
                    )
                elif e.code == 429:
                    # 速率限制 — 可重试，等待更长时间
                    last_error = e
                    if attempt < self._max_retries - 1:
                        retry_after = e.headers.get("Retry-After", "")
                        delay = float(retry_after) if retry_after else self._retry_delay_base * (4 ** attempt)
                        time.sleep(delay)
                        continue
                elif e.code in (500, 502, 503):
                    # 服务端错误 — 可重试
                    last_error = e
                    if attempt < self._max_retries - 1:
                        delay = self._retry_delay_base * (2 ** attempt)
                        time.sleep(delay)
                        continue
                else:
                    # 其他 HTTP 错误 (400, 403, 404 等) — 不可重试
                    self._history.pop()
                    return LLMResponse(
                        text="", success=False,
                        error=f"API 请求失败 ({e.code}): {e.reason}",
                        provider_used=self.config.provider,
                    )
            except urllib.error.URLError as e:
                # 网络错误 — 可重试
                last_error = e
                if attempt < self._max_retries - 1:
                    delay = self._retry_delay_base * (2 ** attempt)
                    time.sleep(delay)
                    continue
            except Exception as e:
                last_error = e
                if attempt < self._max_retries - 1:
                    delay = self._retry_delay_base * (2 ** attempt)
                    time.sleep(delay)
                else:
                    break

        # 所有重试失败，降级
        self._history.pop()  # 移除添加的用户消息
        resp = self._local_response(message, None)
        resp.error = f"LLM API 调用失败(重试{self._max_retries}次): {last_error}，已降级"
        return resp

    def set_tool_executor(self, executor):
        """注入工具执行器以启用 function-calling（DeepSeek/OpenAI 兼容）。"""
        self._tool_executor = executor

    def _post_openai(self, payload: dict) -> dict:
        """POST 到 OpenAI/DeepSeek 兼容端点并返回解析后的 JSON（含 SSL 验证）。"""
        import ssl
        req = urllib.request.Request(
            self.config.base_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.config.api_key}",
            },
            method="POST",
        )
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=60, context=ctx) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _build_payload(self, messages: list, tools=None) -> dict:
        """构建请求体。DeepSeek 思考模式：启用 thinking + reasoning_effort，且不发 temperature。"""
        payload = {
            "model": self.config.model,
            "messages": messages,
            "max_tokens": self.config.max_tokens,
            "stream": False,
        }
        use_thinking = (self.config.provider == "deepseek"
                        and getattr(self.config, "thinking", False))
        if use_thinking:
            payload["thinking"] = {"type": "enabled"}
            payload["reasoning_effort"] = getattr(self.config, "reasoning_effort", "high")
            # 思考模式不支持 temperature/top_p/penalty，故不发送
        else:
            payload["temperature"] = self.config.temperature
        if tools is not None:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        return payload

    def _call_openai_compatible(self) -> LLMResponse:
        """调用 OpenAI/DeepSeek 兼容 API；设置了工具执行器则走 function-calling。"""
        if self._tool_executor is not None:
            return self._call_with_tools()
        messages = [{"role": m.role, "content": m.content} for m in self._history]
        data = self._post_openai(self._build_payload(messages))
        text = data["choices"][0]["message"]["content"]
        self._history.append(LLMMessage("assistant", text))
        return self._parse_response(text, self.config.provider)

    def _call_with_tools(self, max_rounds: int = 4) -> LLMResponse:
        """function-calling 循环：模型请求工具→本地执行→回灌结果→直至最终答复。

        思考模式下需把 reasoning_content 一并回传给后续请求（DeepSeek 要求）。
        """
        from .tools import TOOL_SCHEMAS
        messages = [{"role": m.role, "content": m.content} for m in self._history]
        tool_trace = []
        for _ in range(max_rounds):
            data = self._post_openai(self._build_payload(messages, TOOL_SCHEMAS))
            msg = data["choices"][0]["message"]
            tool_calls = msg.get("tool_calls")
            if not tool_calls:
                text = msg.get("content") or ""
                self._history.append(LLMMessage("assistant", text))
                resp = self._parse_response(text, self.config.provider)
                resp.tool_trace = tool_trace
                return resp
            # 回灌 assistant(tool_calls)，思考模式必须带上 reasoning_content
            assistant_msg = {"role": "assistant", "content": msg.get("content"),
                             "tool_calls": tool_calls}
            if msg.get("reasoning_content") is not None:
                assistant_msg["reasoning_content"] = msg.get("reasoning_content")
            messages.append(assistant_msg)
            for tc in tool_calls:
                fn = tc.get("function", {})
                result = self._tool_executor.execute(fn.get("name", ""),
                                                     fn.get("arguments", "{}"))
                tool_trace.append({"name": fn.get("name", ""), "result": result})
                messages.append({"role": "tool", "tool_call_id": tc.get("id", ""),
                                 "content": json.dumps(result, ensure_ascii=False)})
        return LLMResponse(text="(工具调用轮数超过上限，未收敛)", success=True,
                           provider_used=self.config.provider, tool_trace=tool_trace)

    def _call_claude(self) -> LLMResponse:
        """调用 Claude API（含 SSL 证书验证）"""
        import ssl

        # Claude 格式: system 单独传, messages 不含 system
        messages = [{"role": m.role, "content": m.content}
                     for m in self._history if m.role != "system"]
        payload = {
            "model": self.config.model,
            "max_tokens": self.config.max_tokens,
            "system": SYSTEM_PROMPT,
            "messages": messages,
        }

        req = urllib.request.Request(
            self.config.base_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-api-key": self.config.api_key,
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )

        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            text = data["content"][0]["text"]

        self._history.append(LLMMessage("assistant", text))
        return self._parse_response(text, "claude")

    def _call_ollama(self) -> LLMResponse:
        """调用本地 Ollama API（本地连接不强制 SSL）"""
        import ssl

        payload = {
            "model": self.config.model,
            "messages": [{"role": m.role, "content": m.content} for m in self._history],
            "stream": False,
            "options": {"temperature": self.config.temperature},
        }

        req = urllib.request.Request(
            self.config.base_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        # Ollama 通常运行在 localhost，无需 SSL；远程部署时自动使用系统证书
        ctx = ssl.create_default_context() if "localhost" not in self.config.base_url and "127.0.0.1" not in self.config.base_url else None
        with urllib.request.urlopen(req, timeout=60, context=ctx) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            text = data["message"]["content"]

        self._history.append(LLMMessage("assistant", text))
        return self._parse_response(text, "ollama")

    def _local_response(self, user_message: str, context: dict = None) -> LLMResponse:
        """规则引擎降级 — 基于关键词的简单响应"""
        text = f"[规则引擎降级] 收到调参请求: {user_message[:50]}...\n"
        text += "当前为离线模式，建议:\n"
        text += "1. 使用「传统计算法」标签页进行 ZN/IMC 整定\n"
        text += "2. 或切换到「本地神经网络」模式获取 AI 建议\n"
        return LLMResponse(
            text=text,
            success=True,
            provider_used="rule-engine",
            params_suggested={},
            risk_level="低",
        )

    def _neural_response(self, user_message: str, context: dict = None) -> LLMResponse:
        """神经网络调参 — 使用本地训练的 MLP 预测参数"""
        try:
            from .nlu import NeuralTuner
            if not hasattr(self, '_neural_tuner') or self._neural_tuner is None:
                self._neural_tuner = NeuralTuner()

            result = self._neural_tuner.chat(user_message, context)

            params = {}
            if result.get("params"):
                p = result["params"]
                if "kp" in p: params["Kp"] = p["kp"]
                if "ki" in p: params["Ki"] = p["ki"]
                if "kd" in p: params["Kd"] = p["kd"]

            return LLMResponse(
                text=result["text"],
                success=True,
                provider_used="neural-network",
                params_suggested=params,
                risk_level=result.get("risk", ""),
            )
        except Exception as e:
            # 神经网络失败，降级到规则引擎
            resp = self._local_response(user_message, context)
            resp.error = f"神经网络异常: {e}，已降级为规则引擎"
            resp.provider_used = "rule-engine(fallback)"
            return resp

    def _parse_response(self, text: str, provider: str) -> LLMResponse:
        """解析 LLM 回复，提取建议参数和风险等级"""
        params = {}
        risk = ""

        # 提取 Kp/Ki/Kd 建议值
        for param_name, pattern in [
            ("Kp", r'[Kk]p[：:\s]*([\d.]+)'),
            ("Ki", r'[Kk]i[：:\s]*([\d.]+)'),
            ("Kd", r'[Kk]d[：:\s]*([\d.]+)'),
            ("J", r'[Jj][：:\s]*([\d.]+)'),
            ("D", r'[Dd][：:\s]*([\d.]+)'),
        ]:
            matches = re.findall(pattern, text)
            if matches:
                try:
                    params[param_name] = float(matches[-1])  # 取最后一个(新值)
                except ValueError:
                    pass

        # 提取风险等级
        if re.search(r'高风险|风险.*高|risk.*high', text, re.IGNORECASE):
            risk = "高"
        elif re.search(r'中风险|风险.*中|risk.*medium', text, re.IGNORECASE):
            risk = "中"
        elif re.search(r'低风险|风险.*低|risk.*low', text, re.IGNORECASE):
            risk = "低"

        return LLMResponse(
            text=text,
            success=True,
            provider_used=provider,
            params_suggested=params,
            risk_level=risk,
        )

    def clear_history(self):
        """清除对话历史"""
        self._reset_history()

    def is_using_real_llm(self) -> bool:
        """是否使用 LLM 引擎 (神经网络或云API)"""
        return self.config.provider in ("neural", "local") or bool(self.config.api_key)