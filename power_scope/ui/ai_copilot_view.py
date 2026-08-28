"""ai_copilot_view.py — AI 调试副驾驶面板

集成本地神经网络 / DeepSeek(默认) / OpenAI / Claude / Ollama。支持：
  - 自然语言对话 + 实时上下文注入（超调/上升时间/当前PID/故障码）
  - function-calling：LLM 读实时数据、提议写参数/触发阶跃
  - 安全红线：写类工具只"提议"，经护栏校验后必须人工点「确认下发」
  - 建议参数一键回填调参页

LLM 调用在 QThread 中执行，避免阻塞 UI。tool_context 可注入，便于测试。
"""
from __future__ import annotations
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QLineEdit,
    QPushButton, QTextEdit, QFrame, QCheckBox,
)
from PySide6.QtCore import Qt, QThread, Signal

from ..llm.llm_engine import LLMEngine, LLMConfig, LLMResponse
from ..llm.tools import ToolExecutor
from .theme import ui_color


_PROVIDER_MAP = {
    "DeepSeek (默认)": "deepseek",
    "本地神经网络": "neural",
    "OpenAI (GPT)": "openai",
    "Anthropic (Claude)": "claude",
    "本地 Ollama": "ollama",
    "本地规则引擎": "local",
}
_TOOL_PROVIDERS = {"deepseek", "openai"}  # 支持 function-calling 的云端


class _ChatWorker(QThread):
    done = Signal(object)  # LLMResponse

    def __init__(self, engine, message, context, parent=None):
        super().__init__(parent)
        self._engine = engine
        self._message = message
        self._context = context

    def run(self):
        try:
            resp = self._engine.chat(self._message, self._context)
        except Exception as e:  # noqa: BLE001
            resp = LLMResponse(text=f"调用异常: {e}", success=False, error=str(e))
        self.done.emit(resp)


class AICopilotView(QWidget):
    param_suggested = Signal(dict)   # 建议参数 {kp,ki,kd} → 调参页
    status = Signal(str)             # 状态信息 → 主窗口状态栏

    def __init__(self, parent=None):
        super().__init__(parent)
        self._engine = LLMEngine()
        self._ctx = None
        self._executor = None
        self._worker = None
        self._build_ui()

    # ---------- UI ----------
    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(8)

        title = QLabel("AI 调试副驾驶")
        title.setObjectName("title")
        lay.addWidget(title)

        cfg = QHBoxLayout()
        cfg.addWidget(QLabel("引擎:"))
        self._provider = QComboBox()
        self._provider.addItems(list(_PROVIDER_MAP.keys()))
        cfg.addWidget(self._provider)
        self._key = QLineEdit()
        self._key.setEchoMode(QLineEdit.Password)
        self._key.setPlaceholderText("API Key（本地引擎无需）")
        cfg.addWidget(self._key, 1)
        self._connect_btn = QPushButton("连接")
        self._connect_btn.setObjectName("btn_primary")
        self._connect_btn.clicked.connect(self._on_connect)
        cfg.addWidget(self._connect_btn)
        lay.addLayout(cfg)

        # 思考模式行（仅 DeepSeek v4 生效）
        cfg2 = QHBoxLayout()
        self._thinking_chk = QCheckBox("思考模式")
        self._thinking_chk.setChecked(True)
        self._thinking_chk.setToolTip("DeepSeek v4 深度推理，更强但更慢")
        self._thinking_chk.toggled.connect(lambda _c: self._update_thinking_enabled(self._provider.currentText()))
        cfg2.addWidget(self._thinking_chk)
        cfg2.addWidget(QLabel("强度:"))
        self._effort_combo = QComboBox()
        self._effort_combo.addItems(["high", "max"])
        self._effort_combo.setToolTip("high=标准推理  max=增强推理(更慢)")
        cfg2.addWidget(self._effort_combo)
        cfg2.addStretch()
        lay.addLayout(cfg2)
        self._provider.currentTextChanged.connect(self._update_thinking_enabled)
        self._update_thinking_enabled(self._provider.currentText())

        self._status_lbl = QLabel("引擎: 本地神经网络（离线可用）")
        self._status_lbl.setProperty("role", "ok")
        lay.addWidget(self._status_lbl)

        self._chat = QTextEdit()
        self._chat.setReadOnly(True)
        # 长会话内存防护：最多保留 2000 个文档块
        self._chat.document().setMaximumBlockCount(2000)
        lay.addWidget(self._chat, 1)

        # 待确认动作区
        self._pending_box = QFrame()
        self._pending_box.setObjectName("card")
        self._pending_layout = QVBoxLayout(self._pending_box)
        self._pending_layout.setContentsMargins(10, 6, 10, 6)
        self._pending_box.setVisible(False)
        lay.addWidget(self._pending_box)

        row = QHBoxLayout()
        self._input = QLineEdit()
        self._input.setPlaceholderText("描述需求，例如「超调18%，帮我降到5%」")
        self._input.returnPressed.connect(self._on_send)
        row.addWidget(self._input, 1)
        self._send_btn = QPushButton("发送")
        self._send_btn.setObjectName("btn_success")
        self._send_btn.clicked.connect(self._on_send)
        row.addWidget(self._send_btn)
        lay.addLayout(row)

        self._append_system(
            "您好！我是 AI 调试副驾驶。\n"
            "· 本地神经网络：离线可用，据实测指标预测 PID\n"
            "· DeepSeek/云端：可读实时数据、提议改参（写操作需您确认）\n"
            "试试：「超调18%太大，降到5%」")

    # ---------- 注入 ----------
    def set_tool_context(self, ctx):
        """注入工具上下文（桥接实时数据/护栏）。"""
        self._ctx = ctx
        self._executor = ToolExecutor(ctx) if ctx is not None else None

    def set_engine(self, engine):
        self._engine = engine

    # ---------- 交互 ----------
    def _on_connect(self):
        label = self._provider.currentText()
        provider = _PROVIDER_MAP.get(label, "neural")
        key = self._key.text().strip()
        self._engine.set_provider(provider, api_key=key)
        self._engine.config.thinking = self._thinking_chk.isChecked()
        self._engine.config.reasoning_effort = self._effort_combo.currentText()
        # 云端且有 key 且支持工具 → 启用 function-calling
        if provider in _TOOL_PROVIDERS and key and self._executor is not None:
            self._engine.set_tool_executor(self._executor)
            self._status_lbl.setText(f"引擎: {label}（已启用工具调用）")
        else:
            self._engine.set_tool_executor(None)
            self._status_lbl.setText(f"引擎: {label}")
        self.status.emit(f"AI 引擎已切换: {label}")

    def _update_thinking_enabled(self, label: str):
        """思考模式仅对 DeepSeek 有效，其它引擎禁用这两个控件。"""
        is_ds = _PROVIDER_MAP.get(label) == "deepseek"
        self._thinking_chk.setEnabled(is_ds)
        self._effort_combo.setEnabled(is_ds and self._thinking_chk.isChecked())

    def _current_context(self) -> dict:
        if self._ctx is None:
            return {}
        try:
            return self._ctx.current_metrics() or {}
        except Exception:
            return {}

    def _on_send(self):
        msg = self._input.text().strip()
        if not msg or (self._worker is not None and self._worker.isRunning()):
            return
        self._input.clear()
        self._append_user(msg)
        self._send_btn.setEnabled(False)
        if self._executor is not None:
            self._executor.clear_pending()
        self._worker = _ChatWorker(self._engine, msg, self._current_context(), self)
        self._worker.done.connect(self._on_done)
        self._worker.start()

    def _on_done(self, resp: LLMResponse):
        self._send_btn.setEnabled(True)
        if resp.error:
            self._append_system(f"⚠ {resp.error}")
        # 工具调用轨迹
        for t in getattr(resp, "tool_trace", []) or []:
            self._append_dim(f"🔧 {t['name']} → {t['result']}")
        self._append_ai(resp.text)
        if resp.params_suggested:
            self.param_suggested.emit(resp.params_suggested)
            self._append_dim(f"→ 建议参数已发往调参页: {resp.params_suggested}")
        self._render_pending()

    def _render_pending(self):
        # 清空旧行
        while self._pending_layout.count():
            it = self._pending_layout.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()
        pend = self._executor.pending if self._executor else []
        if not pend:
            self._pending_box.setVisible(False)
            return
        self._pending_layout.addWidget(QLabel("待确认操作（AI 提议，需人工确认）:"))
        for act in pend:
            row = QHBoxLayout()
            desc = (f"写 {act.name} = {act.value}"
                    + (f"（护栏限幅→{act.clamped}）" if act.clamped is not None
                       and act.clamped != act.value else "")
                    if act.kind == "param_write"
                    else f"阶跃测试 {act.name} 幅值 {act.value}")
            row.addWidget(QLabel(desc), 1)
            ok = QPushButton("确认下发")
            ok.setObjectName("btn_success")
            ok.clicked.connect(lambda _=False, a=act: self._confirm(a))
            row.addWidget(ok)
            skip = QPushButton("忽略")
            skip.clicked.connect(lambda _=False, a=act: self._reject(a))
            row.addWidget(skip)
            holder = QWidget()
            holder.setLayout(row)
            self._pending_layout.addWidget(holder)
        self._pending_box.setVisible(True)

    def _confirm(self, act):
        if self._ctx is not None and hasattr(self._ctx, "apply_pending"):
            try:
                msg = self._ctx.apply_pending(act)
                self._append_dim(f"✓ 已确认: {msg}")
                self.status.emit(f"✓ AI 提议已确认: {act.name}")
            except Exception as e:  # noqa: BLE001
                self._append_system(f"⚠ 下发失败: {e}")
        else:
            self._append_system("⚠ 未连接设备上下文，无法下发。")
        if self._executor and act in self._executor.pending:
            self._executor.pending.remove(act)
        self._render_pending()

    def _reject(self, act):
        if self._executor and act in self._executor.pending:
            self._executor.pending.remove(act)
        self._append_dim(f"已忽略提议: {act.name}")
        self._render_pending()

    # ---------- 渲染 ----------
    def _append_user(self, text):
        self._chat.append(f'<div style="color:{ui_color("primary")}"><b>你：</b>{_esc(text)}</div>')

    def _append_ai(self, text):
        self._chat.append(f'<div style="color:{ui_color("text")}"><b>AI：</b>{_esc(text)}</div>')

    def _append_system(self, text):
        self._chat.append(f'<div style="color:{ui_color("text_dim")}">{_esc(text)}</div>')

    def _append_dim(self, text):
        self._chat.append(f'<div style="color:{ui_color("log_dim")};font-size:12px">{_esc(text)}</div>')


def _esc(text) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace("\n", "<br>"))
