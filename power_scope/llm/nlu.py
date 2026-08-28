"""
nlu.py — 自然语言理解 + 神经网络调参

工作流:
  用户输入 → 意图识别 → 参数提取 → 神经网络预测 → 生成回复
"""
import re
from dataclasses import dataclass
from .local_nn import PIDTunerNN
from .training_data import generate_training_data, generate_feedback_data


@dataclass
class TuneIntent:
    """调参意图"""
    intent: str           # greet / overshoot / slow / steady_error / vsg / analyze / specific_params / unknown
    target_overshoot: float = 5.0
    extracted_kp: float = None
    extracted_ki: float = None
    extracted_kd: float = None
    raw_text: str = ""


class TuneNLU:
    """自然语言理解 — 意图识别 + 参数提取"""

    INTENT_PATTERNS = {
        "greet": [r"你好|hello|hi|嗨|你是谁|介绍|帮忙|功能"],
        "overshoot": [r"超调|overshoot|振荡|震荡|过冲|不稳定|跳"],
        "slow": [r"慢|slow|响应|快速|加速|迟缓|快"],
        "steady_error": [r"稳态|误差|steady|偏差|不准|精度"],
        "vsg": [r"vsg|虚拟同步|惯量|阻尼|频率波动|频率偏"],
        "analyze": [r"分析|数据|波形|阶跃|step|看|诊断"],
        "train": [r"训练|train|学习|learn|优化模型|微调"],
    }

    def parse(self, text: str) -> TuneIntent:
        """解析用户输入"""
        msg = text.lower().strip()
        intent = "unknown"

        # 意图识别 (按优先级)
        for intent_name, patterns in self.INTENT_PATTERNS.items():
            for pat in patterns:
                if re.search(pat, msg):
                    intent = intent_name
                    break
            if intent != "unknown":
                break

        # 具体参数提取
        kp_match = re.search(r'kp\s*[=＝:]\s*([\d.]+)', msg)
        ki_match = re.search(r'ki\s*[=＝:]\s*([\d.]+)', msg)
        kd_match = re.search(r'kd\s*[=＝:]\s*([\d.]+)', msg)

        # 如果有具体参数，覆盖意图为 specific_params
        if kp_match or ki_match:
            intent = "specific_params"

        # 目标超调提取
        target_match = re.search(r'(\d+(?:\.\d+)?)\s*[%％]', msg)
        target_overshoot = 5.0
        if target_match and intent == "overshoot":
            target_overshoot = float(target_match.group(1))

        return TuneIntent(
            intent=intent,
            target_overshoot=target_overshoot,
            extracted_kp=float(kp_match.group(1)) if kp_match else None,
            extracted_ki=float(ki_match.group(1)) if ki_match else None,
            extracted_kd=float(kd_match.group(1)) if kd_match else None,
            raw_text=text,
        )


class NeuralTuner:
    """神经网络调参器 — NLU + NN 预测 + 回复生成 + 模型持久化

    模型自动保存在 ~/.power_scope/models/pid_tuner_nn.json，
    下次启动时自动加载，避免重复训练。
    """

    # 默认模型存储路径
    _DEFAULT_MODEL_DIR = None

    @classmethod
    def _default_model_path(cls) -> str:
        """获取默认模型路径，确保目录存在"""
        import os
        if cls._DEFAULT_MODEL_DIR is None:
            cls._DEFAULT_MODEL_DIR = os.path.join(
                os.path.expanduser("~"), ".power_scope", "models"
            )
            os.makedirs(cls._DEFAULT_MODEL_DIR, exist_ok=True)
        return os.path.join(cls._DEFAULT_MODEL_DIR, "pid_tuner_nn.json")

    def __init__(self, model_path: str = None):
        self.nlu = TuneNLU()
        self._model_path = model_path or self._default_model_path()
        self.nn = PIDTunerNN(self._model_path)
        self._val_loss: float | None = None  # 验证集损失
        self._train_loss: float | None = None  # 训练集损失
        self._auto_train_if_needed()

    def _auto_train_if_needed(self):
        """如果模型未训练，自动用合成数据训练并持久化"""
        if not self.nn.is_trained:
            # 新 API: generate_training_data 返回 (X_train, y_train, X_val, y_val)
            X_train, y_train, X_val, y_val = generate_training_data(
                n_samples=1000, noise_std=0.02, val_split=0.15
            )
            self._train_loss = self.nn.train_on_data(X_train, y_train, epochs=100, verbose=False)
            # 计算验证集损失
            if X_val:
                self._val_loss = self.nn.evaluate(X_val, y_val)
                self.nn.set_val_loss(self._val_loss)  # 校准置信度
            # 训练完成后持久化，避免下次启动重新训练
            self.nn.save(self._model_path)

    def model_quality(self) -> dict:
        """返回模型质量评估指标

        Returns:
            {"train_loss": float|None, "val_loss": float|None, "epochs": int, "is_trained": bool}
        """
        return {
            "train_loss": self._train_loss,
            "val_loss": self._val_loss,
            "epochs": self.nn.epochs,
            "is_trained": self.nn.is_trained,
        }

    def chat(self, user_message: str, context: dict = None) -> dict:
        """
        处理用户消息

        Returns:
            {
                "text": 回复文本,
                "params": {"kp":..., "ki":..., "kd":...} 或 {},
                "risk": "低"/"中"/"高",
                "intent": 意图,
                "confidence": 置信度,
            }
        """
        ctx = context or {}
        intent = self.nlu.parse(user_message)

        # 获取当前参数 — 这些是用户在界面上填的，是真实的
        kp = intent.extracted_kp or ctx.get("current_kp", 0.85)
        ki = intent.extracted_ki or ctx.get("current_ki", 120.0)
        kd = intent.extracted_kd or ctx.get("current_kd", 0.0)
        
        # 性能指标 — None 表示未测量/未提供
        overshoot = ctx.get("overshoot")
        rise_time = ctx.get("rise_time")
        settling_time = ctx.get("settling_time")
        steady_error = ctx.get("steady_error")

        # 从用户输入中提取指标 (如"超调18%"、"上升时间25ms")
        if overshoot is None:
            m = re.search(r'超调.*?(\d+(?:\.\d+)?)\s*[%％]', intent.raw_text)
            if m: overshoot = float(m.group(1))
        if rise_time is None:
            m = re.search(r'(?:上升|rise).*?(\d+(?:\.\d+)?)\s*ms', intent.raw_text, re.IGNORECASE)
            if m: rise_time = float(m.group(1))
        if steady_error is None:
            m = re.search(r'(?:稳态|误差).*?(\d+(?:\.\d+)?)\s*[%％]', intent.raw_text)
            if m: steady_error = float(m.group(1))

        # 神经网络预测需要至少一个性能指标才有意义
        has_any_metric = any(v is not None for v in [overshoot, rise_time, settling_time, steady_error])
        # 神经网络预测需要完整的当前参数
        has_current_params = kp is not None and ki is not None

        if intent.intent == "greet":
            return self._greet_response()

        elif intent.intent == "overshoot":
            if overshoot is None:
                return self._no_metrics_response("超调优化",
                    "请提供当前超调量，例如「超调18%太大」\n或在调参页面的「实测指标输入」区填写示波器测量值。")
            # 有超调数据才能预测
            return self._predict_response(
                kp, ki, kd, overshoot, rise_time, settling_time, steady_error,
                intent.target_overshoot,
                f"当前超调 {overshoot:.1f}%，目标降到 {intent.target_overshoot:.0f}% 以内。"
            )

        elif intent.intent == "slow":
            if rise_time is None:
                return self._no_metrics_response("响应速度优化",
                    "请提供当前上升时间，例如「上升时间25ms太慢」\n或在调参页面的「实测指标输入」区填写测量值。")
            return self._predict_response(
                kp, ki, kd, overshoot, rise_time, settling_time, steady_error,
                10.0,
                f"当前上升时间 {rise_time:.1f}ms，需要加快响应。"
            )

        elif intent.intent == "steady_error":
            if steady_error is None:
                return self._no_metrics_response("稳态误差优化",
                    "请提供当前稳态误差值，例如「稳态误差0.5%太大」\n或在调参页面的「实测指标输入」区填写测量值。")
            return self._predict_response(
                kp, ki, kd, overshoot, rise_time, settling_time, steady_error,
                8.0,
                f"当前稳态误差 {steady_error:.2f}%，需要增强积分作用。"
            )

        elif intent.intent == "vsg":
            return self._vsg_response(ctx)

        elif intent.intent == "analyze":
            if not has_any_metric:
                return self._no_metrics_response("响应分析",
                    "请提供实测指标用于分析。\n您可以在对话中描述，例如「超调18%，上升时间12ms」\n或在调参页面填写实测指标。")
            return self._analyze_response(overshoot or 0, rise_time or 0,
                                          settling_time or 0, steady_error or 0)

        elif intent.intent == "train":
            return self._train_response()

        elif intent.intent == "specific_params":
            return self._specific_params_response(kp, ki, kd, overshoot, rise_time,
                                                   settling_time, steady_error,
                                                   intent.target_overshoot)

        else:
            return self._unknown_response(user_message)

    def _predict_response(self, kp, ki, kd, overshoot, rise_time,
                          settling_time, steady_error, target_overshoot,
                          problem_desc: str) -> dict:
        """神经网络预测 — 只使用真实数据，标注数据来源"""
        # 神经网络需要的完整输入; 缺失的用保守默认值但明确标注
        nn_overshoot = overshoot if overshoot is not None else 10.0
        nn_rise_time = rise_time if rise_time is not None else 15.0
        nn_settling = settling_time if settling_time is not None else 100.0
        nn_error = steady_error if steady_error is not None else 0.5

        pred = self.nn.predict(
            nn_overshoot, nn_rise_time, nn_settling, nn_error,
            kp, ki, kd, target_overshoot
        )

        new_kp = pred["kp"]
        new_ki = pred["ki"]
        new_kd = pred["kd"]
        confidence = pred["confidence"]

        # 风险评估
        kp_change = abs(new_kp - kp) / max(kp, 0.01)
        ki_change = abs(new_ki - ki) / max(ki, 0.01)
        max_change = max(kp_change, ki_change)
        if max_change > 0.5:
            risk = "高"
        elif max_change > 0.2:
            risk = "中"
        else:
            risk = "低"

        # 构建实测数据说明 — 诚实标注哪些是实测、哪些缺失
        data_lines = []
        if overshoot is not None:
            data_lines.append(f"  超调量: {overshoot:.1f}% (实测)")
        else:
            data_lines.append(f"  超调量: 未提供 (神经网络按典型值估算)")
        if rise_time is not None:
            data_lines.append(f"  上升时间: {rise_time:.1f}ms (实测)")
        else:
            data_lines.append(f"  上升时间: 未提供 (神经网络按典型值估算)")
        if steady_error is not None:
            data_lines.append(f"  稳态误差: {steady_error:.2f}% (实测)")
        data_lines.append(f"  当前参数: Kp={kp}, Ki={ki}, Kd={kd} (界面输入)")

        # 预测效果 — 只在有实测数据时才给出量化预估
        effect_lines = []
        if overshoot is not None and "超调" in problem_desc:
            pred_overshoot = overshoot * (1 - kp_change * 0.5)
            effect_lines.append(f"  预估超调: {overshoot:.1f}% → 约 {max(pred_overshoot, target_overshoot):.1f}% (基于模型估算，需实测验证)")
        if rise_time is not None and ("慢" in problem_desc or "上升" in problem_desc):
            pred_rise = rise_time * (1 - kp_change * 0.3)
            effect_lines.append(f"  预估上升时间: {rise_time:.1f}ms → 约 {max(pred_rise, 3):.1f}ms (基于模型估算，需实测验证)")
        if steady_error is not None and "稳态" in problem_desc:
            pred_error = steady_error * (1 - ki_change * 0.5)
            effect_lines.append(f"  预估稳态误差: {steady_error:.2f}% → 约 {max(pred_error, 0.01):.2f}% (基于模型估算，需实测验证)")

        if not effect_lines:
            effect_lines.append("  (缺少对应实测指标，无法量化预估效果，请写入后实测验证)")

        text = (
            f"{problem_desc}\n\n"
            f"输入数据:\n" + "\n".join(data_lines) + "\n\n"
            f"神经网络预测参数 (置信度: {confidence:.0%}):\n"
            f"  Kp: {kp:.3f} → {new_kp:.3f} (变化 {kp_change:+.0%})\n"
            f"  Ki: {ki:.1f} → {new_ki:.1f} (变化 {ki_change:+.0%})\n"
            f"  Kd: {kd:.3f} → {new_kd:.3f}\n\n"
            f"预估效果:\n" + "\n".join(effect_lines) + f"\n\n"
            f"风险等级: {risk}\n"
        )

        if risk == "高":
            text += "  ⚠ 参数变化较大，建议分两步调整，先调一半观察响应。\n"
        elif risk == "中":
            text += "  建议写入后观察 2-3 个周期再决定是否继续调整。\n"
        else:
            text += "  变化幅度在安全范围。\n"

        # 如果缺少关键指标，诚实提示置信度低
        missing = []
        if overshoot is None: missing.append("超调量")
        if rise_time is None: missing.append("上升时间")
        if missing:
            text += f"\n⚠ 缺少实测数据: {', '.join(missing)}\n"
            text += f"  提供完整实测指标可提高预测准确性。\n"
            text += f"  可在调参页面「实测指标输入」区填写，或在对话中描述。\n"

        text += "\n→ 建议参数已自动填入编辑框。\n"
        text += "  写入 MCU 后请实测验证，点击「效果好/差」反馈以在线学习。"

        return {
            "text": text,
            "params": {"kp": new_kp, "ki": new_ki, "kd": new_kd},
            "risk": risk,
            "intent": "predict",
            "confidence": confidence,
        }

    def _no_metrics_response(self, feature: str, hint: str) -> dict:
        """未提供实测指标时的诚实回复"""
        return {
            "text": (
                f"⚠ 无法执行{feature}：缺少实测指标数据\n\n"
                f"神经网络需要系统响应指标（超调/上升时间等）才能预测参数。\n\n"
                f"{hint}\n\n"
                f"或者连接真实 MCU 后点击「触发阶跃响应」自动采集。"
            ),
            "params": {}, "risk": "", "intent": "no_metrics", "confidence": 0.0,
        }

    def _greet_response(self):
        return {
            "text": (
                "您好！我是基于神经网络的调参助手。\n\n"
                "我通过训练控制理论数据学会了 PID 参数优化，可以：\n"
                "  • 根据系统响应指标预测最优 PI/PID 参数\n"
                "  • 支持自然语言描述需求（超调/响应速度/稳态误差）\n"
                "  • 在线学习：您反馈结果后我会自动改进模型\n\n"
                "试试说：\n"
                "  - 「超调18%太大，帮我降到5%」\n"
                "  - 「系统响应太慢」\n"
                "  - 「Kp=0.85 Ki=120 怎么优化」\n"
                "  - 「训练模型」(重新训练神经网络)"
            ),
            "params": {}, "risk": "", "intent": "greet", "confidence": 1.0,
        }

    def _vsg_response(self, ctx):
        j = ctx.get("vsg_J", 2.0)
        d = ctx.get("vsg_D", 5.0)
        return {
            "text": (
                f"VSG 参数调整建议：\n\n"
                f"当前: J={j}, D={d}\n\n"
                f"建议：\n"
                f"  虚拟惯量 J: {j} → {j*1.2:.2f} (增大20%，增强抗扰)\n"
                f"  阻尼系数 D: {d} → {d*1.5:.1f} (增大50%，抑制频率波动)\n\n"
                f"预期效果：频率波动减小约40%，功率响应略变慢。\n"
                f"风险: 中 (VSG参数影响电网交互，建议小步调整)"
            ),
            "params": {"J": j*1.2, "D": d*1.5},
            "risk": "中", "intent": "vsg", "confidence": 0.8,
        }

    def _analyze_response(self, overshoot, rise_time, settling_time, steady_error):
        # 性能评价
        issues = []
        if overshoot > 15: issues.append(f"超调 {overshoot:.1f}% 偏大 (>15%)")
        if rise_time > 20: issues.append(f"上升时间 {rise_time:.1f}ms 偏慢 (>20ms)")
        if steady_error > 1: issues.append(f"稳态误差 {steady_error:.2f}% 偏大 (>1%)")

        if not issues:
            evaluation = "系统性能良好，各项指标在正常范围内。"
        else:
            evaluation = "发现以下问题:\n  • " + "\n  • ".join(issues)

        return {
            "text": (
                f"阶跃响应分析 (基于您提供的实测数据)：\n\n"
                f"  上升时间 Tr: {rise_time:.1f}ms\n"
                f"  超调量 Mp: {overshoot:.1f}%\n"
                f"  调节时间 Ts: {settling_time:.1f}ms\n"
                f"  稳态误差: {steady_error:.2f}%\n\n"
                f"{evaluation}\n\n"
                f"{'请描述您想优化哪个指标，我会用神经网络预测参数。' if issues else '如需进一步优化，请描述具体需求。'}"
            ),
            "params": {}, "risk": "", "intent": "analyze", "confidence": 1.0,
        }

    def _train_response(self):
        X_train, y_train, X_val, y_val = generate_training_data(n_samples=2000)
        loss = self.nn.train_on_data(X_train, y_train, epochs=200, verbose=True)
        if X_val:
            self._val_loss = self.nn.evaluate(X_val, y_val)
            self.nn.set_val_loss(self._val_loss)
        self.nn.save()
        return {
            "text": (
                f"神经网络重新训练完成！\n\n"
                f"  训练样本: 2000\n"
                f"  训练轮数: 200\n"
                f"  最终损失: {loss:.6f}\n"
                f"  总训练轮数: {self.nn.epochs}\n\n"
                f"模型已保存，预测置信度已提升。\n"
                f"现在可以继续提问调参需求。"
            ),
            "params": {}, "risk": "", "intent": "train", "confidence": 1.0,
        }

    def _specific_params_response(self, kp, ki, kd, overshoot, rise_time,
                                   settling_time, steady_error, target):
        # 分析当前参数是否在合理范围
        kp_eval = "偏低" if kp < 0.5 else "合理" if kp < 1.5 else "偏高"
        ki_eval = "偏低" if ki < 50 else "合理" if ki < 300 else "偏高"

        desc = f"当前参数 Kp={kp}, Ki={ki}, Kd={kd}。\nKp {kp_eval}，Ki {ki_eval}。"
        # 如果没有性能指标，只做参数评估不预测
        if overshoot is None and rise_time is None and steady_error is None:
            return {
                "text": (
                    f"{desc}\n\n"
                    f"参数范围评估:\n"
                    f"  Kp {kp_eval} (典型电流环: 0.5-2.0)\n"
                    f"  Ki {ki_eval} (典型电流环: 50-500)\n\n"
                    f"缺少系统响应指标，无法进行神经网络预测。\n"
                    f"请提供超调量/上升时间/稳态误差等实测数据，例如:\n"
                    f"  「Kp=0.85 Ki=120, 超调18%, 上升时间12ms」"
                ),
                "params": {}, "risk": "", "intent": "specific_params", "confidence": 0.5,
            }
        return self._predict_response(kp, ki, kd, overshoot, rise_time,
                                      settling_time, steady_error, target, desc)

    def _unknown_response(self, user_message):
        return {
            "text": (
                f"我理解您的输入：「{user_message}」\n\n"
                f"我是神经网络调参助手，擅长 PI/PID 参数优化。\n\n"
                f"请尝试：\n"
                f"  - 「超调太大，帮我降到5%」\n"
                f"  - 「系统响应太慢」\n"
                f"  - 「Kp=0.85 Ki=120 怎么优化」\n"
                f"  - 「分析阶跃响应」\n"
                f"  - 「训练模型」"
            ),
            "params": {}, "risk": "", "intent": "unknown", "confidence": 0.5,
        }

    def feedback(self, kp, ki, kd, overshoot, rise_time, settling_time,
                 steady_error, good_result: bool, target_overshoot=5.0):
        """用户反馈 — 在线学习"""
        features, target = generate_feedback_data(
            kp, ki, kd, overshoot, rise_time, settling_time, steady_error,
            good_result, target_overshoot
        )
        self.nn.online_learn(features, target, lr=0.01)
        return f"已{'记录好结果' if good_result else '记录需改进'}，模型已在线微调。总训练轮数: {self.nn.epochs}"
