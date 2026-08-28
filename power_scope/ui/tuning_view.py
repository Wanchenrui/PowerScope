"""调参视图 — 传统计算法 + LLM 辅助"""
import struct
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox,
    QPushButton, QLabel, QDoubleSpinBox, QComboBox, QTextEdit,
    QTabWidget, QProgressBar, QMessageBox, QSplitter, QLineEdit,
    QScrollArea,
)
from PySide6.QtCore import Qt, Signal, QThread
from ..llm.llm_engine import LLMEngine, LLMConfig, LLMResponse
from .theme import ui_color, chart_color


class _LLMChatWorker(QThread):
    """LLM 对话后台线程（参考 ai_copilot_view._ChatWorker），避免阻塞 UI。"""
    done = Signal(object, object)   # (LLMResponse, context)

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
        self.done.emit(resp, self._context)


class _SimWorker(QThread):
    """单次离线仿真后台线程。done 携带 metrics 对象或 Exception。"""
    done = Signal(object)

    def __init__(self, plant, kp, ki, kd, amp, duration, parent=None):
        super().__init__(parent)
        self._args = (plant, kp, ki, kd, amp, duration)

    def run(self):
        from ..core.power_simulator import simulate_and_analyze
        try:
            self.done.emit(simulate_and_analyze(*self._args, dt=1e-4))
        except Exception as e:  # noqa: BLE001
            self.done.emit(e)


class _AutoTuneWorker(QThread):
    """自动整定（临界比例法二分搜索）后台线程，支持进度回调与取消。"""
    progress = Signal(int, int, float)  # 迭代序号, 总迭代数, 当前试探 Ku
    done = Signal(object)               # {"Ku":..,"Tu":..} / {"error":..} / {"cancelled":True}

    def __init__(self, plant, amp, duration, parent=None):
        super().__init__(parent)
        self._plant = plant
        self._amp = amp
        self._duration = duration
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        import numpy as np
        from ..core.power_simulator import simulate_step

        Ku_lo, Ku_hi = 0.0, 200.0
        Ku = 0.0
        Tu = 0.0
        converged = False

        for i in range(20):
            if self._cancelled:
                self.done.emit({"cancelled": True})
                return
            Ku = (Ku_lo + Ku_hi) / 2.0
            self.progress.emit(i + 1, 20, Ku)
            try:
                t, y = simulate_step(self._plant, Ku, 0, 0,
                                     self._amp, self._duration, dt=1e-4)
            except Exception:  # noqa: BLE001
                Ku_hi = Ku
                continue

            if np.isnan(y).any() or np.isinf(y).any() or np.max(np.abs(y)) > 1e4:
                Ku_hi = Ku
                continue

            n = len(y)
            tail = y[n - n // 4:]
            ybar = np.mean(tail)
            crossings = np.sum(np.diff(np.sign(tail - ybar)) != 0)
            if crossings >= 3:
                Ku_lo = Ku
                peaks = []
                for k in range(1, n - 1):
                    if k > n // 2 and y[k - 1] < y[k] > y[k + 1] and y[k] > 0:
                        peaks.append(t[k])
                Tu = peaks[-1] - peaks[-2] if len(peaks) >= 2 else 1e-3
            else:
                Ku_lo = Ku

            if Ku_hi - Ku_lo < 0.1:
                converged = True
                break

        if not converged and Ku < 0.01:
            self.done.emit({
                "error": "> 未找到临界增益 Ku。\n"
                         "> 请改用二阶欠阻尼预设，或将仿真时长增加到 500ms 以上。"
            })
            return
        self.done.emit({"Ku": Ku, "Tu": Tu})


class TuningView(QWidget):
    """双模调参视图"""

    def __init__(self, profile=None, parent=None):
        super().__init__(parent)
        self._profile = profile
        self._connected = False
        self._llm_engine = LLMEngine(LLMConfig(provider="neural"))
        self._last_prediction = None  # 上次预测结果 (用于反馈)
        self._debug = None            # DebugService（主窗口注入）
        self._resolve = None          # name -> SampleChannel|None（主窗口注入）
        self._safety = None           # SafetyController（主窗口注入）
        self._loop_defs = list((getattr(profile, "tuning", {}) or {}).get("loops", []))
        self._stream_check = None      # callable()->set[str]，当前流中通道名(主窗口注入)
        self._step_capture = None      # 进行中的 StepCaptureController
        self._step_ctx = None          # 阶跃上下文 baseline/amp/cfg/setpoint_ch
        self._llm_worker = None        # 进行中的 LLM 对话线程
        self._sim_worker = None        # 进行中的单次仿真线程
        self._auto_tune_worker = None  # 进行中的自动整定线程
        # 调参策略引擎
        from ..core.tuning_engine import TuningEngine
        self._tuning_engine = TuningEngine()
        # 安全护栏
        from ..core.guardrails import Guardrails
        self._guardrails = Guardrails(profile)
        self._build_ui()

    def _build_ui(self):
        _content = QWidget()
        layout = QVBoxLayout(_content)

        # 模式选择
        mode_tabs = QTabWidget()

        # ===== 传统计算法 =====
        trad_tab = QWidget()
        trad_layout = QVBoxLayout(trad_tab)

        # 参数选择
        param_group = QGroupBox("调参目标")
        param_grid = QGridLayout(param_group)

        param_grid.addWidget(QLabel("控制环路:"), 0, 0)
        self._loop_combo = QComboBox()
        if self._loop_defs:
            self._loop_combo.addItems([loop.get("label", loop.get("id", "环路")) for loop in self._loop_defs])
        else:
            self._loop_combo.addItems(["电流内环 (d轴)", "电流内环 (q轴)", "电压外环", "功率环", "VSG频率环"])
        self._loop_combo.currentIndexChanged.connect(self._on_loop_changed)
        param_grid.addWidget(self._loop_combo, 0, 1)

        param_grid.addWidget(QLabel("Kp:"), 1, 0)
        self._kp_input = QDoubleSpinBox()
        self._kp_input.setRange(0, 100)
        self._kp_input.setDecimals(4)
        self._kp_input.setSingleStep(0.01)
        param_grid.addWidget(self._kp_input, 1, 1)

        self._ki_label = QLabel("Ki:")
        param_grid.addWidget(self._ki_label, 1, 2)
        self._ki_input = QDoubleSpinBox()
        self._ki_input.setRange(0, 10000)
        self._ki_input.setDecimals(2)
        self._ki_input.setSingleStep(1.0)
        param_grid.addWidget(self._ki_input, 1, 3)

        self._kd_label = QLabel("Kd:")
        param_grid.addWidget(self._kd_label, 2, 0)
        self._kd_input = QDoubleSpinBox()
        self._kd_input.setRange(0, 100)
        self._kd_input.setDecimals(4)
        param_grid.addWidget(self._kd_input, 2, 1)

        trad_layout.addWidget(param_group)

        # ---- 仿真 / 在线阶跃 双模式 tabs ----
        self._sim_mode_tabs = QTabWidget()

        # ===== Tab 1: 离线仿真 =====
        sim_tab = QWidget()
        sim_layout = QVBoxLayout(sim_tab)
        sim_layout.setContentsMargins(8, 8, 8, 8)
        sim_layout.setSpacing(6)

        # 被控对象预设
        plant_row = QHBoxLayout()
        plant_row.addWidget(QLabel("被控对象:"))
        self._plant_preset_combo = QComboBox()
        from ..core.power_simulator import PRESET_PLANTS
        self._plant_preset_combo.addItems(list(PRESET_PLANTS.keys()))
        self._plant_preset_combo.currentTextChanged.connect(self._on_plant_preset_changed)
        plant_row.addWidget(self._plant_preset_combo)
        sim_layout.addLayout(plant_row)

        # 被控对象参数显示（只读标签）
        self._plant_params_label = QLabel("")
        self._plant_params_label.setObjectName("dim")
        self._plant_params_label.setWordWrap(True)
        sim_layout.addWidget(self._plant_params_label)

        sim_layout.addSpacing(4)

        # 仿真参数行：幅值 + 时长
        sim_param_row = QHBoxLayout()
        sim_param_row.addWidget(QLabel("阶跃幅值:"))
        self._sim_amp = QDoubleSpinBox()
        self._sim_amp.setRange(0.01, 100)
        self._sim_amp.setValue(1.0)
        sim_param_row.addWidget(self._sim_amp)
        sim_param_row.addWidget(QLabel("仿真时长(ms):"))
        self._sim_dur = QDoubleSpinBox()
        self._sim_dur.setRange(10, 5000)
        self._sim_dur.setValue(300)
        sim_param_row.addWidget(self._sim_dur)
        sim_param_row.addStretch()
        sim_layout.addLayout(sim_param_row)

        # 仿真按钮
        sim_btn_row = QHBoxLayout()
        self._sim_run_btn = QPushButton("▶ 运行仿真并分析")
        self._sim_run_btn.setObjectName("btn_primary")
        self._sim_run_btn.clicked.connect(self._on_run_simulation)
        sim_btn_row.addWidget(self._sim_run_btn)

        self._sim_auto_tune_btn = QPushButton("⚡ 自动整定 (临界比例法)")
        self._sim_auto_tune_btn.setObjectName("btn_success")
        self._sim_auto_tune_btn.clicked.connect(self._on_sim_auto_tune)
        sim_btn_row.addWidget(self._sim_auto_tune_btn)

        self._sim_cancel_btn = QPushButton("取消")
        self._sim_cancel_btn.setObjectName("btn_danger")
        self._sim_cancel_btn.setVisible(False)
        self._sim_cancel_btn.clicked.connect(self._on_sim_cancel)
        sim_btn_row.addWidget(self._sim_cancel_btn)
        sim_btn_row.addStretch()
        sim_layout.addLayout(sim_btn_row)

        self._sim_mode_tabs.addTab(sim_tab, "离线仿真")

        # ===== Tab 2: 在线阶跃 =====
        real_tab = QWidget()
        real_layout = QVBoxLayout(real_tab)
        real_layout.setContentsMargins(8, 8, 8, 8)
        real_layout.setSpacing(6)

        ov_row = QHBoxLayout()
        ov_row.addWidget(QLabel("setpoint 变量:"))
        self._setpoint_edit = QLineEdit()
        self._setpoint_edit.setPlaceholderText("参考变量名(留空用profile)")
        ov_row.addWidget(self._setpoint_edit)
        ov_row.addWidget(QLabel("feedback 变量:"))
        self._feedback_edit = QLineEdit()
        self._feedback_edit.setPlaceholderText("反馈变量名(留空用profile)")
        ov_row.addWidget(self._feedback_edit)
        real_layout.addLayout(ov_row)

        # 阶跃参数行
        real_step_row = QHBoxLayout()
        real_step_row.addWidget(QLabel("阶跃幅值:"))
        self._step_amp = QDoubleSpinBox()
        self._step_amp.setRange(0.01, 100)
        self._step_amp.setValue(1.0)
        real_step_row.addWidget(self._step_amp)
        real_step_row.addWidget(QLabel("持续时间(ms):"))
        self._step_dur = QDoubleSpinBox()
        self._step_dur.setRange(10, 10000)
        self._step_dur.setValue(100)
        real_step_row.addWidget(self._step_dur)
        real_step_row.addStretch()
        real_layout.addLayout(real_step_row)

        trigger_btn = QPushButton("① 触发阶跃响应")
        trigger_btn.setObjectName("btn_primary")
        trigger_btn.clicked.connect(self._on_trigger_step)
        real_layout.addWidget(trigger_btn)

        self._sim_mode_tabs.addTab(real_tab, "在线阶跃")

        trad_layout.addWidget(self._sim_mode_tabs)

        # 整定方法选择（仿真/在线共用）
        method_group = QGroupBox("整定方法")
        method_layout = QVBoxLayout(method_group)

        method_row = QHBoxLayout()
        method_row.addWidget(QLabel("方法:"))
        self._method_combo = QComboBox()
        self._method_combo.addItems([
            "Ziegler-Nichols (临界比例法)",
            "Cohen-Coon (反应曲线法)",
            "频率响应法 (Bode图)",
            "IMC 内模控制法",
            "极点配置法",
            "全部方法对比 (推荐)",
        ])
        method_row.addWidget(self._method_combo)
        method_row.addStretch()
        method_layout.addLayout(method_row)

        calc_btn = QPushButton("② 计算推荐参数")
        calc_btn.setObjectName("btn_success")
        calc_btn.clicked.connect(self._on_calculate)
        method_layout.addWidget(calc_btn)

        self._apply_btn = QPushButton("③ 写入MCU")
        self._apply_btn.setObjectName("btn_warning")
        self._apply_btn.clicked.connect(self._on_apply)
        method_layout.addWidget(self._apply_btn)

        trad_layout.addWidget(method_group)

        # 手动输入实测指标 (无设备时可用示波器测量值)
        metrics_group = QGroupBox("实测指标输入 (无设备时手动填写示波器测量值)")
        metrics_layout = QGridLayout(metrics_group)
        metrics_layout.setSpacing(4)

        metrics_layout.addWidget(QLabel("超调量(%):"), 0, 0)
        self._manual_overshoot = QDoubleSpinBox()
        self._manual_overshoot.setRange(0, 100)
        self._manual_overshoot.setDecimals(1)
        self._manual_overshoot.setValue(0)
        self._manual_overshoot.setSpecialValueText("未测量")
        metrics_layout.addWidget(self._manual_overshoot, 0, 1)

        metrics_layout.addWidget(QLabel("上升时间(ms):"), 0, 2)
        self._manual_rise_time = QDoubleSpinBox()
        self._manual_rise_time.setRange(0, 1000)
        self._manual_rise_time.setDecimals(1)
        self._manual_rise_time.setValue(0)
        self._manual_rise_time.setSpecialValueText("未测量")
        metrics_layout.addWidget(self._manual_rise_time, 0, 3)

        metrics_layout.addWidget(QLabel("调节时间(ms):"), 1, 0)
        self._manual_settling_time = QDoubleSpinBox()
        self._manual_settling_time.setRange(0, 10000)
        self._manual_settling_time.setDecimals(1)
        self._manual_settling_time.setValue(0)
        self._manual_settling_time.setSpecialValueText("未测量")
        metrics_layout.addWidget(self._manual_settling_time, 1, 1)

        metrics_layout.addWidget(QLabel("稳态误差(%):"), 1, 2)
        self._manual_steady_error = QDoubleSpinBox()
        self._manual_steady_error.setRange(0, 100)
        self._manual_steady_error.setDecimals(2)
        self._manual_steady_error.setValue(0)
        self._manual_steady_error.setSpecialValueText("未测量")
        metrics_layout.addWidget(self._manual_steady_error, 1, 3)

        trad_layout.addWidget(metrics_group)

        # 结果显示
        result_group = QGroupBox("计算结果")
        result_layout = QVBoxLayout(result_group)
        self._result_text = QTextEdit()
        self._result_text.setReadOnly(True)
        self._result_text.setMinimumHeight(150)
        self._result_text.setPlainText("点击「触发阶跃响应」开始调参流程...")
        result_layout.addWidget(self._result_text, 1)
        # 整定前后闭环对比图（旧参数 vs 新参数阶跃响应）
        try:
            import pyqtgraph as pg
            self._compare_plot = pg.PlotWidget()
            self._compare_plot.setObjectName("card")
            self._compare_plot.setMinimumHeight(200)
            self._compare_plot.showGrid(x=True, y=True, alpha=0.3)
            self._compare_plot.addLegend(offset=(-10, 10))
            self._compare_plot.setLabel("bottom", "时间", units="s")
            self._compare_plot.setLabel("left", "输出")
            result_layout.addWidget(self._compare_plot, 1)
        except Exception:
            self._compare_plot = None
        trad_layout.addWidget(result_group, 1)

        mode_tabs.addTab(trad_tab, "传统计算法")

        # ===== LLM 辅助 =====
        llm_tab = QWidget()
        llm_layout = QVBoxLayout(llm_tab)

        llm_config = QGroupBox("LLM 配置")
        llm_config_layout = QGridLayout(llm_config)
        llm_config_layout.addWidget(QLabel("提供商:"), 0, 0)
        self._llm_provider = QComboBox()
        self._llm_provider.addItems([
            "本地神经网络(推荐)", "DeepSeek", "OpenAI (GPT-4)",
            "Anthropic (Claude)", "本地模型 (Ollama)", "本地规则引擎"
        ])
        self._llm_provider.setCurrentText("本地神经网络(推荐)")
        llm_config_layout.addWidget(self._llm_provider, 0, 1)

        connect_llm_btn = QPushButton("连接")
        connect_llm_btn.setObjectName("btn_primary")
        connect_llm_btn.setMinimumWidth(80)
        connect_llm_btn.clicked.connect(self._on_connect_llm)
        llm_config_layout.addWidget(connect_llm_btn, 0, 2)

        llm_config_layout.addWidget(QLabel("API Key:"), 1, 0)
        self._api_key = QLineEdit()
        self._api_key.setEchoMode(QLineEdit.Password)
        self._api_key.setPlaceholderText("输入 API Key (本地规则引擎和 Ollama 无需)")
        llm_config_layout.addWidget(self._api_key, 1, 1)

        self._llm_status = QLabel("LLM 状态: 本地规则引擎 (离线可用，基于光伏调参知识库)")
        self._llm_status.setProperty("role", "ok")
        llm_config_layout.addWidget(self._llm_status, 2, 0, 1, 3)

        llm_layout.addWidget(llm_config)

        # 对话区
        chat_group = QGroupBox("调参对话")
        chat_layout = QVBoxLayout(chat_group)
        self._chat_display = QTextEdit()
        self._chat_display.setReadOnly(True)
        self._chat_display.setHtml(
            f'<span style="color:{ui_color("ai")};font-weight:bold;">调参助手</span>: 您好！我是光伏微逆与储能系统的调参助手。\n\n'
            '我可以帮您：\n'
            '  • 分析控制环路性能（超调、响应时间、稳态误差）\n'
            '  • 给出 PI/PID 参数调整建议\n'
            '  • 评估参数修改的风险\n\n'
            '请描述您的需求，例如：\n'
            '  - 「超调太大，帮我降到5%以内」\n'
            '  - 「系统响应太慢」\n'
            '  - 「Kp=0.85 Ki=120 怎么优化」\n'
            '  - 「VSG频率波动大」'
        )
        chat_layout.addWidget(self._chat_display, 1)

        input_row = QHBoxLayout()
        self._chat_input = QLineEdit()
        self._chat_input.setPlaceholderText("输入调参需求...")
        self._chat_input.returnPressed.connect(self._on_llm_send)
        input_row.addWidget(self._chat_input)

        self._send_btn = QPushButton("发送")
        self._send_btn.setObjectName("btn_primary")
        self._send_btn.clicked.connect(self._on_llm_send)
        input_row.addWidget(self._send_btn)
        chat_layout.addLayout(input_row)

        # 反馈按钮 (在线学习)
        feedback_row = QHBoxLayout()
        feedback_row.addWidget(QLabel("调参反馈:"))
        good_btn = QPushButton("✓ 效果好")
        good_btn.setObjectName("btn_success")
        good_btn.setMinimumWidth(100)
        good_btn.clicked.connect(lambda: self._on_feedback(True))
        feedback_row.addWidget(good_btn)

        bad_btn = QPushButton("✗ 效果差")
        bad_btn.setObjectName("btn_danger")
        bad_btn.setMinimumWidth(100)
        bad_btn.clicked.connect(lambda: self._on_feedback(False))
        feedback_row.addWidget(bad_btn)

        feedback_row.addWidget(QLabel("(反馈后神经网络自动在线学习)"))
        feedback_row.addStretch()
        chat_layout.addLayout(feedback_row)

        llm_layout.addWidget(chat_group)
        mode_tabs.addTab(llm_tab, "LLM 辅助调参")

        layout.addWidget(mode_tabs, 1)

        # 安全护栏状态
        guard_group = QGroupBox("安全护栏状态")
        guard_layout = QGridLayout(guard_group)
        guards = ["绝对限幅", "单步增幅限制", "保底策略", "自动回退", "看门狗超时", "人工审批"]
        for i, g in enumerate(guards):
            cell = QWidget()
            cell_row = QHBoxLayout(cell)
            cell_row.setContentsMargins(0, 0, 0, 0)
            cell_row.setSpacing(4)
            led = QLabel("●")
            led.setProperty("role", "ok")
            cell_row.addWidget(led)
            cell_row.addWidget(QLabel(g))
            cell_row.addStretch()
            guard_layout.addWidget(cell, i // 3, i % 3)
        self._safety_status = QLabel("状态: IDLE（参数未处于观察窗口）")
        guard_layout.addWidget(self._safety_status, 2, 0)
        btn_box = QWidget()
        btn_row = QHBoxLayout(btn_box)
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.setSpacing(6)
        self._confirm_btn = QPushButton("确认并提交")
        self._confirm_btn.setEnabled(False)
        self._confirm_btn.clicked.connect(lambda: self._safety and self._safety.confirm())
        btn_row.addWidget(self._confirm_btn)
        self._revert_btn = QPushButton("立即回退")
        self._revert_btn.setEnabled(False)
        self._revert_btn.clicked.connect(lambda: self._safety and self._safety.revert())
        btn_row.addWidget(self._revert_btn)
        self._clear_safe_btn = QPushButton("解除安全停机锁定")
        self._clear_safe_btn.setVisible(False)
        self._clear_safe_btn.clicked.connect(
            lambda: self._safety and self._safety.clear_safe_stop())
        btn_row.addWidget(self._clear_safe_btn)
        guard_layout.addWidget(btn_box, 2, 1, 1, 2)
        layout.addWidget(guard_group)

        # 内容包裹进滚动区，避免整页最小高度撑爆窗口（小屏/最大化自适应）
        _scroll = QScrollArea()
        _scroll.setWidgetResizable(True)
        _scroll.setFrameShape(QScrollArea.NoFrame)
        _scroll.setWidget(_content)
        _outer = QVBoxLayout(self)
        _outer.setContentsMargins(0, 0, 0, 0)
        _outer.addWidget(_scroll)

        self._on_loop_changed(self._loop_combo.currentIndex())

    # === Simulation handlers ===

    def _on_plant_preset_changed(self, name: str):
        """预设切换时更新被控对象参数标签。"""
        from ..core.power_simulator import PRESET_PLANTS
        plant = PRESET_PLANTS.get(name)
        if plant is None:
            return
        self._plant_params_label.setText(plant.to_label())
        self._sim_plant = plant

    def _on_run_simulation(self):
        """离线仿真：用当前 PID 参数计算阶跃响应（后台线程执行，不阻塞 UI）。"""
        from ..core.power_simulator import PRESET_PLANTS

        plant_name = self._plant_preset_combo.currentText()
        plant = PRESET_PLANTS.get(plant_name)
        if plant is None:
            self._result_text.setPlainText("> 请先选择被控对象预设。")
            return
        if self._sim_busy():
            return

        Kp = self._kp_input.value()
        Ki = self._ki_input.value()
        Kd = self._kd_input.value()
        amp = self._sim_amp.value()
        dur_ms = self._sim_dur.value()
        duration = dur_ms / 1000.0

        self._set_sim_busy(True)
        self._result_text.setPlainText("> 仿真运行中，请稍候...")
        self._sim_ctx = {
            "plant_name": plant_name, "plant_label": plant.to_label(),
            "Kp": Kp, "Ki": Ki, "Kd": Kd, "amp": amp, "dur_ms": dur_ms,
        }
        worker = _SimWorker(plant, Kp, Ki, Kd, amp, duration, parent=self)
        worker.done.connect(self._on_sim_done)
        self._sim_worker = worker
        worker.start()

    def _on_sim_done(self, m):
        """单次仿真完成，回到主线程更新结果区。"""
        self._set_sim_busy(False)
        ctx = getattr(self, "_sim_ctx", {})

        if isinstance(m, Exception):
            self._result_text.setPlainText(f"> 仿真出错: {m}")
            return

        if not m.valid or m.rise_time_ms <= 0:
            self._result_text.setPlainText(
                f"> 分析无效: {m.info}\n"
                f"> 请尝试增大阶跃幅值/仿真时长，或调整 PID 增益"
            )
            return

        lines = [
            f"===== 仿真结果: {ctx.get('plant_name', '')} =====",
            "",
            f"  被控对象: {ctx.get('plant_label', '')}",
            f"  PID:   Kp={ctx.get('Kp', 0):.4g}  Ki={ctx.get('Ki', 0):.4g}  Kd={ctx.get('Kd', 0):.4g}",
            f"  阶跃:  幅值={ctx.get('amp', 0):.2f}  时长={ctx.get('dur_ms', 0):.0f}ms",
            "",
            "  --- 时域指标 ---",
            f"  超调量:      {m.overshoot_pct:.1f}%",
            f"  上升时间:    {m.rise_time_ms:.1f} ms",
            f"  调节时间:    {m.settling_time_ms:.1f} ms",
            f"  峰值时间:    {m.peak_time_ms:.1f} ms",
            f"  稳态误差:    {m.steady_error_pct:.2f}%",
            "  --- 辨识参数 ---",
            f"  等效增益 K: {m.K:.4f}",
            f"  等效时间常数 T: {m.T:.4f} s",
            f"  等效滞后 L: {m.L:.4f} s",
            "",
            "  >> 就绪 — 点击「② 计算推荐参数」进行整定",
        ]
        self._result_text.setPlainText("\n".join(lines))

        self._last_sim_metrics = m

        # 回填实测指标输入框，便于对比
        self._manual_overshoot.setValue(m.overshoot_pct)
        self._manual_rise_time.setValue(m.rise_time_ms)
        self._manual_settling_time.setValue(m.settling_time_ms)
        self._manual_steady_error.setValue(m.steady_error_pct)

    def _sim_busy(self):
        """仿真/自动整定是否有后台任务在跑。"""
        for w in (self._sim_worker, self._auto_tune_worker):
            if w is not None and w.isRunning():
                return True
        return False

    def _set_sim_busy(self, busy, cancellable=False):
        """仿真运行期间禁用相关按钮；自动整定时显示「取消」。"""
        self._sim_run_btn.setEnabled(not busy)
        self._sim_auto_tune_btn.setEnabled(not busy)
        self._sim_cancel_btn.setVisible(busy and cancellable)

    def _on_sim_cancel(self):
        """取消正在进行的自动整定搜索。"""
        if self._auto_tune_worker is not None and self._auto_tune_worker.isRunning():
            self._auto_tune_worker.cancel()
            self._sim_cancel_btn.setEnabled(False)

    def _on_sim_auto_tune(self):
        """自动整定：临界比例法仿真搜索（后台线程执行，带进度与取消）。"""
        from ..core.power_simulator import PRESET_PLANTS

        plant_name = self._plant_preset_combo.currentText()
        plant = PRESET_PLANTS.get(plant_name)
        if plant is None:
            self._result_text.setPlainText("> 请先选择被控对象预设。")
            return
        if self._sim_busy():
            return

        amp = self._sim_amp.value()
        dur_ms = self._sim_dur.value()
        duration = dur_ms / 1000.0

        self._auto_tune_ctx = {"plant_name": plant_name}
        self._set_sim_busy(True, cancellable=True)
        self._result_text.setPlainText(
            "正在搜索临界增益 Ku（纯比例振荡）...\n"
            "  （非自衡对象可能搜索失败——可适当增大仿真时长）"
        )

        worker = _AutoTuneWorker(plant, amp, duration, parent=self)
        worker.progress.connect(self._on_auto_tune_progress)
        worker.done.connect(self._on_auto_tune_done)
        self._auto_tune_worker = worker
        worker.start()

    def _on_auto_tune_progress(self, i, total, ku):
        """自动整定进度：迭代 i/total，当前试探增益 Ku。"""
        self._result_text.setPlainText(
            f"正在搜索临界增益 Ku（纯比例振荡）: 迭代 {i}/{total}，当前试探 K={ku:.2f}\n"
            "  （可点击「取消」中止搜索）"
        )

    def _on_auto_tune_done(self, result):
        """自动整定完成，回到主线程回填参数并输出结果。"""
        self._set_sim_busy(False)
        self._sim_cancel_btn.setEnabled(True)
        plant_name = self._auto_tune_ctx.get("plant_name", "")

        if result.get("cancelled"):
            self._result_text.setPlainText("> 自动整定已取消。")
            return
        if "error" in result:
            self._result_text.setPlainText(result["error"])
            return

        Ku = result["Ku"]
        Tu = result["Tu"]

        # ZN 临界比例法
        if Tu > 0:
            Kp = 0.6 * Ku
            Ki = 2.0 * Kp / Tu
            Kd = Kp * Tu / 8.0
        else:
            Kp = Ku
            Ki = 10.0
            Kd = 0.001

        self._kp_input.setValue(round(Kp, 4))
        self._ki_input.setValue(round(Ki, 2))
        self._kd_input.setValue(round(Kd, 6))

        self._result_text.setPlainText(
            f"===== ZN 自动整定: {plant_name} =====\n"
            f"\n"
            f"  临界增益 Ku:   {Ku:.2f}\n"
            f"  临界周期 Tu:   {Tu * 1000:.1f} ms\n"
            f"\n"
            f"  推荐 PID (ZN 临界比例法):\n"
            f"  Kp = 0.6*Ku     = {Kp:.4f}\n"
            f"  Ki = 2*Kp/Tu    = {Ki:.2f}\n"
            f"  Kd = Kp*Tu/8    = {Kd:.6f}\n"
            f"\n"
            f"  >> PID 参数已填入，点击「▶ 运行仿真并分析」验证。"
        )


    def _on_trigger_step(self):
        loop = self._loop_combo.currentText()
        amp_req = self._step_amp.value()
        dur_ms = self._step_dur.value()
        self._result_text.append("\n" + "=" * 50)
        self._result_text.append(
            f"阶跃响应测试:  环路 {loop} | 幅值 {amp_req} | 持续 {dur_ms}ms")

        cfg = self._active_step_loop_config()
        if not (self._connected and self._debug is not None and self._resolve is not None):
            self._result_text.append("  ⚠ 未连真机/未加载ELF — 不触发主动阶跃。")
            self._result_text.append("  → 可在「实测指标输入」手填示波器值后点②计算。")
            return
        if not cfg.ready_for_active_step:
            self._result_text.append("  ⚠ 该环路未配置 setpoint/feedback/step_max(>0) — 无法主动阶跃。")
            self._result_text.append("  → 在 profile 的 loop 里填(硬件负责人核定)，或在上方框指定，并确保 profile 配了 step_max 安全上限。")
            return
        setpoint_ch = self._resolve(cfg.setpoint)
        if setpoint_ch is None:
            self._result_text.append(f"  ✗ setpoint「{cfg.setpoint}」未在 ELF 解析到地址。")
            return
        streaming = set(self._stream_check()) if self._stream_check else set()
        if cfg.feedback not in streaming:
            self._result_text.append(f"  ✗ feedback「{cfg.feedback}」不在采样流中 — 请先在「波形」加入该变量再测。")
            return
        if self._safety is None or self._safety.state != "IDLE":
            st = self._safety.state if self._safety else "无"
            self._result_text.append(f"  ✗ 安全状态 {st}(需 IDLE)，暂不触发。")
            return
        if self._step_capture is not None:
            self._result_text.append("  ⚠ 上一次阶跃测试仍在进行，请稍候。")
            return
        amp = cfg.clamp_amplitude(amp_req)
        if amp == 0:
            self._result_text.append("  ✗ 阶跃幅值被钳为0(检查 step_max 与幅值)。")
            return
        if abs(amp - amp_req) > 1e-9:
            self._result_text.append(f"  ⚠ 幅值受 step_max={cfg.step_max} 限幅: {amp_req}→{amp}")

        from ..debug.elf_parser import decode_value, type_size
        size = type_size(setpoint_ch.type_name) or int(setpoint_ch.size)

        fb_ch = self._resolve(cfg.feedback)
        if fb_ch is None:
            self._result_text.append(f"  ✗ feedback「{cfg.feedback}」未在 ELF 解析到地址。")
            return
        fb_size = type_size(fb_ch.type_name) or int(fb_ch.size)
        dur_s = dur_ms / 1000.0

        def on_sp_base(resp):
            if resp.get("status", 0) != 0:
                self._result_text.append("  ✗ 读取 setpoint 基线失败，已中止。")
                return
            sp_base = decode_value(bytes(resp.get("payload", b""))[:size], setpoint_ch.type_name)
            if isinstance(sp_base, (bytes, bytearray)):
                self._result_text.append("  ✗ setpoint 基线无法解码，已中止。")
                return

            def on_fb_base(r2):
                if r2.get("status", 0) != 0:
                    self._result_text.append("  ✗ 读取 feedback 基线失败，已中止。")
                    return
                fb_base = decode_value(bytes(r2.get("payload", b""))[:fb_size], fb_ch.type_name)
                if isinstance(fb_base, (bytes, bytearray)):
                    self._result_text.append("  ✗ feedback 基线无法解码，已中止。")
                    return
                fb_phys = float(fb_base) * getattr(fb_ch, "scale", 1.0) + getattr(fb_ch, "offset", 0.0)
                self._launch_active_step(cfg, setpoint_ch, float(sp_base), fb_phys, amp, dur_s)

            self._debug.read_memory(int(fb_ch.address), fb_size, callback=on_fb_base)

        self._result_text.append("  → 读取 setpoint/feedback 基线...")
        self._debug.read_memory(int(setpoint_ch.address), size, callback=on_sp_base)

    def set_stream_check(self, fn):
        """注入"当前流中通道名集合"查询(主窗口提供)，用于阶跃前校验 feedback 在流中。"""
        self._stream_check = fn

    def _active_step_loop_config(self):
        """当前环路阶跃配置：profile loop 解析，再用上方 setpoint/feedback 框覆盖。"""
        from ..core.step_response import parse_step_loop
        cfg = parse_step_loop(self._current_loop() or {})
        sp = self._setpoint_edit.text().strip() if hasattr(self, "_setpoint_edit") else ""
        fb = self._feedback_edit.text().strip() if hasattr(self, "_feedback_edit") else ""
        if sp:
            cfg.setpoint = sp
        if fb:
            cfg.feedback = fb
        return cfg

    def _launch_active_step(self, cfg, setpoint_ch, sp_base, fb_base, amp, dur_s):
        """启采集 → 经 SafetyController 原子写阶跃(监视+异常自动回滚到基线)。"""
        from ..core.step_capture import StepCaptureController
        cap = StepCaptureController(cfg.feedback, dur_s, parent=self)
        self._step_capture = cap
        self._step_ctx = {"sp_base": sp_base, "fb_base": fb_base, "amp": amp,
                          "cfg": cfg, "setpoint_ch": setpoint_ch}
        cap.finished.connect(self._on_step_captured)
        cap.start()
        value = sp_base + amp
        ok = self._safety.begin([(cfg.setpoint, setpoint_ch, value, sp_base)])
        if not ok:
            cap.stop()
            self._clear_step_state()
            self._result_text.append("  ✗ 安全控制器拒绝写入(状态/监测未就绪)，已中止。")
            return
        self._result_text.append(
            f"  → 已写阶跃 {cfg.setpoint}={value:.6g}(基线 {sp_base:.6g}+{amp:.6g})，采集中...")

    def _on_step_captured(self, samples):
        """采集窗口结束：恢复基线 → 分析 → 回填指标。"""
        from ..core.step_response import analyze_step
        ctx = self._step_ctx or {}
        if self._safety is not None and self._safety.state == "MONITORING":
            self._safety.revert()
        if not samples:
            self._result_text.append("  ✗ 未采到 feedback 样本(是否在流中/已停流?)。基线已恢复。")
            self._clear_step_state()
            return
        m = analyze_step(samples, t_step=samples[0][0],
                         input_step=ctx.get("amp"), baseline=ctx.get("fb_base"))
        if not m.valid:
            self._result_text.append(f"  ✗ 阶跃分析无效: {m.info}。基线已恢复。")
            self._clear_step_state()
            return
        self._manual_overshoot.setValue(min(self._manual_overshoot.maximum(), m.overshoot_pct))
        self._manual_rise_time.setValue(min(self._manual_rise_time.maximum(), m.rise_time_ms))
        self._manual_settling_time.setValue(min(self._manual_settling_time.maximum(), m.settling_time_ms))
        self._manual_steady_error.setValue(min(self._manual_steady_error.maximum(), abs(m.steady_error_pct)))
        self._result_text.append(
            f"  ✓ 指标: 超调 {m.overshoot_pct:.1f}% | 上升 {m.rise_time_ms:.1f}ms | "
            f"调节 {m.settling_time_ms:.1f}ms | 稳态误差 {m.steady_error_pct:.2f}%")
        self._result_text.append(
            f"    等效FOPDT: K={m.K:.4g} T={m.T*1000:.1f}ms L={m.L*1000:.1f}ms。基线已恢复。")
        self._result_text.append("  → 指标已回填，点击②计算推荐参数。")
        self._clear_step_state()

    def _clear_step_state(self):
        cap = self._step_capture
        if cap is not None:
            try:
                cap.finished.disconnect(self._on_step_captured)
            except (RuntimeError, TypeError):
                pass
        self._step_capture = None
        self._step_ctx = None
    def _on_calculate(self):
        method = self._method_combo.currentText()
        self._result_text.append(f"\n{'='*50}")
        self._result_text.append(f"整定计算 ({method}):")

        overshoot = self._manual_overshoot.value() if hasattr(self, '_manual_overshoot') else 0
        rise_time = self._manual_rise_time.value() if hasattr(self, '_manual_rise_time') else 0

        if not self._connected and overshoot == 0 and rise_time == 0:
            self._result_text.append("  ⚠ 无法计算: 未连接设备且未输入实测指标")
            self._result_text.append("\n请选择以下方式之一:")
            self._result_text.append("  1. 连接真实 MCU 后触发阶跃响应")
            self._result_text.append("  2. 在「手动输入指标」区填写示波器测量值")
            self._result_text.append("  3. 切换到「LLM辅助调参」标签页描述需求")
            return

        # 组装 SystemMetrics，并判定辨识是否可信
        m = getattr(self, '_last_sim_metrics', None)
        if m is not None and m.valid:
            metrics = m.to_system_metrics()
            identified = metrics.identified
            self._result_text.append(
                f"  (仿真辨识模型: K={metrics.K:.4f}, T={metrics.T:.4f}s, L={metrics.L:.4f}s)")
        else:
            from ..core.tuning_engine import SystemMetrics
            metrics = SystemMetrics(
                overshoot=overshoot,
                rise_time_ms=rise_time,
                K=1.0,
                T=(rise_time / 1000.0 * 2.2) if rise_time > 0 else 0.025,
                L=(rise_time / 1000.0 * 2.2 * 0.15) if rise_time > 0 else 0.005,
                identified=False,   # 手填指标 + 假设增益，非严格 FOPDT 辨识
            )
            identified = False

        if not identified:
            self._result_text.append(
                "  ⚠ 未经严格 FOPDT 辨识（增益 K 为假设值），以下参数仅作起点，务必实测验证。")

        # 多方法一键对比
        if "全部方法" in method:
            self._calculate_all_methods(metrics)
            return

        strategy_map = {
            "Ziegler-Nichols (临界比例法)": "Ziegler-Nichols",
            "Cohen-Coon (反应曲线法)": "Cohen-Coon",
            "频率响应法 (Bode图)": "Frequency-Response",
            "IMC 内模控制法": "IMC",
            "极点配置法": "IMC",
        }
        strategy_name = strategy_map.get(method, "IMC")
        result = self._tuning_engine.compute(strategy_name, metrics)

        # 失败拦截：valid=False 时不出参数、不回填编辑框
        if not result.valid:
            self._result_text.append(f"  ✗ 整定失败: {result.info}")
            self._result_text.append("  → 需 K>0、T>0（Cohen-Coon/IMC 还需 L>0）。请重测阶跃或改用仿真辨识。")
            return

        self._result_text.append(f"  {result.info}")

        clamped = result.clamp()
        if clamped.kp != result.kp or clamped.ki != result.ki or clamped.kd != result.kd:
            self._result_text.append(f"  ⚠ 安全护栏限幅: Kp={result.kp:.3f}->{clamped.kp:.3f}, "
                                     f"Ki={result.ki:.1f}->{clamped.ki:.1f}, "
                                     f"Kd={result.kd:.4f}->{clamped.kd:.4f}")

        # 整定前后闭环对比（下发前预估改善）
        old_gains = (self._kp_input.value(), self._ki_input.value(), self._kd_input.value())
        self._show_before_after(metrics, old_gains, (clamped.kp, clamped.ki, clamped.kd))

        self._result_text.append(f"  → PID: Kp={clamped.kp:.3f}, Ki={clamped.ki:.1f}, Kd={clamped.kd:.4f}")
        self._kp_input.setValue(clamped.kp)
        self._ki_input.setValue(clamped.ki)
        self._kd_input.setValue(clamped.kd)
        self._result_text.append("\n→ 参数已填入上方编辑框，点击「写入MCU」生效")

    def _show_before_after(self, metrics, old_gains, new_gains):
        """用辨识模型仿真旧/新参数的闭环阶跃，输出指标对比并绘图。"""
        try:
            from ..core.power_simulator import PlantModel, compare_pid
            plant = PlantModel.first_order(metrics.K, metrics.T, metrics.L)
            cmp = compare_pid(plant, tuple(old_gains), tuple(new_gains), amplitude=1.0)
        except Exception as e:
            self._result_text.append(f"  ⚠ 前后对比仿真失败: {e}")
            return
        om, nm = cmp["old"]["metrics"], cmp["new"]["metrics"]
        self._result_text.append("  整定前后闭环对比（辨识模型仿真）:")
        self._result_text.append(
            f"    超调:     {om.overshoot_pct:6.2f}%  →  {nm.overshoot_pct:6.2f}%")
        self._result_text.append(
            f"    上升时间: {om.rise_time_ms:6.1f}ms →  {nm.rise_time_ms:6.1f}ms")
        self._result_text.append(
            f"    调节时间: {om.settling_time_ms:6.1f}ms →  {nm.settling_time_ms:6.1f}ms")
        self._render_compare(cmp)

    def _render_compare(self, cmp):
        """把旧/新参数阶跃曲线画到对比图（黄=旧, 青=新, 灰虚线=设定值）。"""
        plot = getattr(self, '_compare_plot', None)
        if plot is None:
            return
        try:
            import pyqtgraph as pg
            from PySide6.QtCore import Qt
            plot.clear()
            old, new = cmp["old"], cmp["new"]
            dur = cmp["duration"]
            plot.plot([0.0, dur], [1.0, 1.0],
                      pen=pg.mkPen(ui_color("text_dim"), width=1, style=Qt.DashLine))
            plot.plot(list(old["t"]), list(old["y"]),
                      pen=pg.mkPen(chart_color(2), width=2), name='旧参数')
            plot.plot(list(new["t"]), list(new["y"]),
                      pen=pg.mkPen(chart_color(0), width=2), name='新参数')
        except Exception:
            pass

    def _calculate_all_methods(self, metrics):
        """对所有整定策略各出一组参数并仿真对比，挑综合最优回填。"""
        from ..core.power_simulator import PlantModel, compare_pid
        results = self._tuning_engine.compute_all(metrics)
        plant = PlantModel.first_order(metrics.K, metrics.T, metrics.L)
        old_gains = (self._kp_input.value(), self._ki_input.value(), self._kd_input.value())
        self._result_text.append("  多方法对比 (Kp/Ki/Kd → 超调/上升/调节):")
        best = None  # (cost, name, clamped, cmp)
        for name, r in results.items():
            if not r.valid:
                self._result_text.append(f"    {name}: ✗ {r.info}")
                continue
            c = r.clamp()
            try:
                cmp = compare_pid(plant, old_gains, (c.kp, c.ki, c.kd), amplitude=1.0)
                nm = cmp["new"]["metrics"]
                self._result_text.append(
                    f"    {name}: {c.kp:.3f}/{c.ki:.1f}/{c.kd:.4f} → "
                    f"{nm.overshoot_pct:.1f}%/{nm.rise_time_ms:.1f}ms/{nm.settling_time_ms:.1f}ms")
                cost = nm.overshoot_pct + 0.05 * nm.settling_time_ms + 0.02 * nm.rise_time_ms
                if best is None or cost < best[0]:
                    best = (cost, name, c, cmp)
            except Exception as e:
                self._result_text.append(f"    {name}: ⚠ 仿真失败 {e}")
        if best is None:
            self._result_text.append("  ✗ 所有方法均无有效结果（检查 K/T/L）。")
            return
        _, bname, bc, bcmp = best
        self._result_text.append(f"  ★ 推荐: {bname} (综合最优)")
        self._render_compare(bcmp)
        self._kp_input.setValue(bc.kp)
        self._ki_input.setValue(bc.ki)
        self._kd_input.setValue(bc.kd)
        self._result_text.append("\n→ 最优参数已填入编辑框，点击「写入MCU」生效")

    def _current_loop(self):
        if not self._loop_defs:
            return None
        index = self._loop_combo.currentIndex()
        return self._loop_defs[index] if 0 <= index < len(self._loop_defs) else None

    def _parameter_bindings(self):
        loop = self._current_loop()
        if loop is None:
            return {"Kp": "Kp", "Ki": "Ki", "Kd": "Kd"}
        return dict(loop.get("params", {}))

    def _on_loop_changed(self, _index):
        inputs = {"Kp": self._kp_input, "Ki": self._ki_input, "Kd": self._kd_input}
        bindings = self._parameter_bindings()
        ki_name = bindings.get("Ki")
        ki_binding = self._profile.find_var(ki_name) if self._profile and ki_name else None
        is_kitc = bool(ki_binding and str(ki_binding.elf_symbol).endswith(".kiTc"))
        self._ki_label.setText("Ki（kiTc 原值）:" if is_kitc else "Ki:")
        self._ki_input.setToolTip(
            "直接写入固件 kiTc；连续域 Ki 必须先按本环路控制周期换算"
            if is_kitc else "")
        self._kd_label.setText(
            "Kd（固件无此项）:" if bindings.get("Kd") is None else "Kd:")
        for display_name, spin in inputs.items():
            binding_name = bindings.get(display_name)
            spin.setEnabled(binding_name is not None)
            if binding_name is None or self._profile is None:
                continue
            binding = self._profile.find_var(binding_name)
            if binding is None:
                continue
            spin.setRange(float(binding.min_val), float(binding.max_val))
            spin.setDecimals(max(0, int(binding.precision)))
            width = abs(float(binding.max_val) - float(binding.min_val))
            spin.setSingleStep(max(10 ** (-max(1, int(binding.precision))), width / 1000.0))
        if hasattr(self, "_setpoint_edit"):
            from ..core.step_response import parse_step_loop
            scfg = parse_step_loop(self._current_loop() or {})
            self._setpoint_edit.setText(scfg.setpoint)
            self._feedback_edit.setText(scfg.feedback)
        self.refresh_loop_values()

    def refresh_loop_values(self):
        """从 MCU 读取当前 PI 参数并填入编辑框。"""
        if not (self._connected and self._debug is not None and
                self._resolve is not None and hasattr(self._debug, "read_memory")):
            return
        from ..debug.elf_parser import decode_value, type_size
        inputs = {"Kp": self._kp_input, "Ki": self._ki_input, "Kd": self._kd_input}
        for display_name, binding_name in self._parameter_bindings().items():
            if binding_name is None:
                continue
            channel = self._resolve(binding_name)
            if channel is None:
                continue
            size = type_size(channel.type_name) or int(channel.size)

            def on_read(response, spin=inputs[display_name], tn=channel.type_name, sz=size):
                if response.get("status", 0) != 0:
                    return
                value = decode_value(bytes(response.get("payload", b""))[:sz], tn)
                if not isinstance(value, (bytes, bytearray)):
                    spin.setValue(float(value))
            self._debug.read_memory(int(channel.address), size, callback=on_read)
    def _on_apply(self):
        values = {
            "Kp": self._kp_input.value(),
            "Ki": self._ki_input.value(),
            "Kd": self._kd_input.value(),
        }
        bindings = self._parameter_bindings()
        active = {
            display_name: (binding_name, values[display_name])
            for display_name, binding_name in bindings.items()
            if binding_name is not None
        }

        if not self._connected:
            self._result_text.append("\n⚠ 未连接设备 — 参数未实际写入")
            self._result_text.append(
                "  拟写入: " + ", ".join(f"{name}={value}" for name, (_, value) in active.items()))
            self._result_text.append("  连接真实 MCU 后点击写入才会生效")
            return
        if not active:
            self._result_text.append("\n✗ 当前环路没有可写参数映射")
            return

        results = {
            display_name: self._guardrails.validate(binding_name, value)
            for display_name, (binding_name, value) in active.items()
        }
        for display_name, result in results.items():
            if not result.allowed:
                self._result_text.append(
                    f"\n✗ {display_name} 写入被拒绝: {result.message}")
                return

        clamped = {name: result.clamped_value for name, result in results.items()}
        warnings = [
            f"{name}: {result.message}" for name, result in results.items()
            if result.message != "OK"
        ]
        lines = "\n".join(f"{name} = {value:.10g}" for name, value in clamped.items())
        reply = QMessageBox.question(
            self, "确认写入",
            f"确认写入以下参数到MCU?\n\n{lines}"
            + (f"\n\n⚠ 安全护栏修正:\n" + "\n".join(warnings) if warnings else "")
            + "\n\n写后将进入看门狗观察窗；异常会自动回退，严重异常会先停机。",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        if warnings:
            self._result_text.append(f"\n⚠ 安全护栏: {'; '.join(warnings)}")

        if self._safety is not None:
            if self._resolve is None:
                self._result_text.append("\n✗ 未加载 ELF 地址解析器，安全事务未启动")
                return
            transaction = []
            for display_name, (binding_name, _requested) in active.items():
                channel = self._resolve(binding_name)
                if channel is None:
                    self._result_text.append(
                        f"\n✗ {display_name}: 无法解析 {binding_name} 的真实 ELF 地址，整组未写入")
                    return
                transaction.append(
                    (binding_name, channel, clamped[display_name]))
            if self._safety.begin(transaction):
                self._result_text.append("\n→ 参数组写入校验中...")
            return

        self._write_params_verified(clamped, bindings)
    def _on_connect_llm(self):
        """连接 LLM 提供商"""
        provider_text = self._llm_provider.currentText()
        api_key = self._api_key.text().strip()

        provider_map = {
            "本地神经网络(推荐)": "neural",
            "DeepSeek": "deepseek",
            "OpenAI (GPT-4)": "openai",
            "Anthropic (Claude)": "claude",
            "本地模型 (Ollama)": "ollama",
            "本地规则引擎": "local",
        }
        provider = provider_map.get(provider_text, "neural")

        if provider == "neural":
            self._llm_engine = LLMEngine(LLMConfig(provider="neural"))
            self._llm_status.setText("LLM 状态: 本地神经网络 (numpy MLP 8→32→16→3, 已训练)")
            self._llm_status.setProperty("role", "ok")
            self._chat_display.append("\n--- 已启动本地神经网络调参引擎 ---")
            self._chat_display.append(f'<span style="color:{ui_color("user")};">神经网络架构: 8输入→32→16→3输出 (纯numpy, 无外部依赖)</span>')
            self._chat_display.append(f'<span style="color:{ui_color("user")};">训练数据: 2000组控制理论仿真样本 (ZN/Cohen-Coon/IMC)</span>')
            self._chat_display.append(f'<span style="color:{ui_color("rx")};">支持在线学习: 调参后反馈结果，模型自动优化</span>')
        elif provider == "local":
            self._llm_engine = LLMEngine(LLMConfig(provider="neural"))
            self._llm_status.setText("LLM 状态: 本地神经网络 (numpy MLP 8→32→16→3)")
            self._llm_status.setProperty("role", "ok")
            self._chat_display.append("\n--- 已切换到本地神经网络 ---")
        elif provider == "ollama":
            self._llm_engine = LLMEngine(LLMConfig(provider="ollama"))
            self._llm_status.setText("LLM 状态: Ollama 本地模型 (需先启动 ollama serve)")
            self._llm_status.setProperty("role", "warn"); self._llm_status.style().unpolish(self._llm_status); self._llm_status.style().polish(self._llm_status)
            self._chat_display.append("\n--- 已连接 Ollama 本地模型 ---")
        elif not api_key:
            QMessageBox.warning(self, "需要 API Key", f"使用 {provider_text} 需要 API Key。\n请在上方输入框填入您的 API Key。")
            return
        else:
            self._llm_engine.set_provider(provider, api_key)
            self._llm_status.setText(f"LLM 状态: {provider_text} (已连接，模型: {self._llm_engine.config.model})")
            self._llm_status.setProperty("role", "ok")
            self._chat_display.append(f"\n--- 已连接 {provider_text} ---")

    def _on_llm_send(self):
        """发送消息到 LLM（QThread 后台执行，不阻塞 UI）"""
        text = self._chat_input.text().strip()
        if not text:
            return
        if self._llm_worker is not None and self._llm_worker.isRunning():
            return

        # 显示用户消息
        self._chat_display.append(f'\n<span style="color:{ui_color("user")};font-weight:bold;">用户</span>: {text}')
        self._chat_input.clear()

        # 确保引擎已初始化
        if not hasattr(self, '_llm_engine') or self._llm_engine is None:
            self._llm_engine = LLMEngine(LLMConfig(provider="neural"))

        # 构建上下文 — 使用实际输入值，未测量指标标注为 None
        context = {
            "current_kp": self._kp_input.value(),
            "current_ki": self._ki_input.value(),
            "current_kd": self._kd_input.value(),
            "overshoot": self._manual_overshoot.value() if hasattr(self, '_manual_overshoot') and self._manual_overshoot.value() > 0 else None,
            "rise_time": self._manual_rise_time.value() if hasattr(self, '_manual_rise_time') and self._manual_rise_time.value() > 0 else None,
            "settling_time": self._manual_settling_time.value() if hasattr(self, '_manual_settling_time') and self._manual_settling_time.value() > 0 else None,
            "steady_error": self._manual_steady_error.value() if hasattr(self, '_manual_steady_error') and self._manual_steady_error.value() > 0 else None,
        }

        # 禁用发送按钮，显示"思考中"，后台线程调用 LLM
        self._send_btn.setEnabled(False)
        self._chat_display.append(f'<span style="color:{ui_color("log_dim")};">助手思考中...</span>')

        worker = _LLMChatWorker(self._llm_engine, text, context, parent=self)
        worker.done.connect(self._on_llm_done)
        self._llm_worker = worker
        worker.start()

    def _on_llm_done(self, resp, context):
        """LLM 回复完成（主线程）：更新对话区并恢复发送按钮。"""
        self._send_btn.setEnabled(True)

        # 格式化回复
        provider_tag = f'[{resp.provider_used}]' if resp.provider_used else ''
        risk_color = {"低": ui_color("rx"), "中": ui_color("tx"), "高": ui_color("danger")}.get(resp.risk_level, ui_color("log_dim"))
        risk_tag = f' <span style="color:{risk_color};">风险:{resp.risk_level}</span>' if resp.risk_level else ''

        self._chat_display.append(
            f'\n<span style="color:{ui_color("ai")};font-weight:bold;">调参助手</span>{provider_tag}{risk_tag}:\n{resp.text}'
        )

        # 如果有建议参数，自动填入编辑框
        if resp.params_suggested:
            if "Kp" in resp.params_suggested:
                self._kp_input.setValue(resp.params_suggested["Kp"])
            if "Ki" in resp.params_suggested:
                self._ki_input.setValue(resp.params_suggested["Ki"])
            if "Kd" in resp.params_suggested:
                self._kd_input.setValue(resp.params_suggested["Kd"])
            self._chat_display.append(
                f'<span style="color:{ui_color("tx")};">→ 建议参数已自动填入上方编辑框，点击「写入MCU」生效</span>'
            )
            # 存储预测用于反馈
            self._last_prediction = {
                "context": context,
                "params": resp.params_suggested,
            }
            self._chat_display.append(
                f'<span style="color:{ui_color("user")};">💡 调参后请点击「效果好」或「效果差」反馈，神经网络会自动学习</span>'
            )

        # 如果有错误 (API 调用失败降级)
        if resp.error:
            self._chat_display.append(
                f'<span style="color:{ui_color("danger")};">⚠ {resp.error}</span>'
            )

    def _on_feedback(self, good: bool):
        """用户反馈 — 触发神经网络在线学习"""
        if not self._last_prediction:
            self._chat_display.append(
                f'<span style="color:{ui_color("tx")};">⚠ 请先获取调参建议后再反馈</span>'
            )
            return

        ctx = self._last_prediction["context"]
        params = self._last_prediction["params"]

        try:
            if self._llm_engine.config.provider == "neural" and hasattr(self._llm_engine, '_neural_tuner') and self._llm_engine._neural_tuner:
                msg = self._llm_engine._neural_tuner.feedback(
                    kp=params.get("Kp", ctx.get("current_kp", 0.85)),
                    ki=params.get("Ki", ctx.get("current_ki", 120.0)),
                    kd=params.get("Kd", ctx.get("current_kd", 0.0)),
                    overshoot=ctx.get("overshoot", 18.0),
                    rise_time=ctx.get("rise_time", 12.0),
                    settling_time=85.0,
                    steady_error=ctx.get("steady_error", 0.2),
                    good_result=good,
                )
                color = ui_color("rx") if good else ui_color("danger")
                icon = "✓" if good else "✗"
                self._chat_display.append(
                    f'\n<span style="color:{color};">{icon} {msg}</span>'
                )
            else:
                result_text = "好" if good else "差"
                self._chat_display.append(
                    f'\n<span style="color:{ui_color("log_dim")};">反馈已记录 ({result_text})。切换到「本地神经网络」模式可启用在线学习。</span>'
                )
            self._last_prediction = None
        except Exception as e:
            self._chat_display.append(
                f'\n<span style="color:{ui_color("danger")};">反馈处理错误: {e}</span>'
            )

    def set_debug_service(self, debug):
        """注入 DebugService，用于真实写入+读回。"""
        self._debug = debug

    def set_channel_resolver(self, resolver):
        """注入 name -> SampleChannel|None 解析器（主窗口基于 ELF 符号提供）。"""
        self._resolve = resolver

    def _write_params_verified(self, clamped, bindings=None):
        """兼容路径：逐项写入读回；安全控制器接入后由其接管原子事务。"""
        bindings = bindings or {name: name for name in clamped}
        if not (self._connected and self._debug is not None
                and self._resolve is not None
                and hasattr(self._debug, "write_and_verify")):
            self._result_text.append("\n✓ 参数已记录（未连接真实设备/未加载ELF，未下发）:")
            self._result_text.append(
                "  " + ", ".join(f"{name}={value:.10g}" for name, value in clamped.items()))
            return
        from ..debug.elf_parser import encode_value, type_size, decode_value
        self._result_text.append("\n→ 写参数并读回确认:")
        for display_name, value in clamped.items():
            binding_name = bindings.get(display_name)
            if binding_name is None:
                continue
            channel = self._resolve(binding_name)
            if channel is None:
                self._result_text.append(
                    f"  ⚠ {display_name}: 未在 ELF 解析到地址（profile 变量 {binding_name}）")
                continue
            try:
                data = encode_value(value, channel.type_name)
            except ValueError as exc:
                self._result_text.append(f"  ✗ {display_name}: 编码失败 {exc}")
                continue
            size = type_size(channel.type_name) or len(data)

            def on_done(ok, readback, nm=display_name, bn=binding_name,
                        val=value, tn=channel.type_name, sz=size):
                if ok:
                    got = decode_value(readback[:sz], tn)
                    self._guardrails.record(bn, val)
                    self._result_text.append(f"  ✓ {nm} = {got}（写入并读回一致）")
                else:
                    self._result_text.append(f"  ✗ {nm} 读回校验失败")

            self._debug.write_and_verify(
                int(channel.address), data, size, callback=on_done)

    def set_safety_controller(self, controller):
        """注入安全参数事务控制器。"""
        if self._safety is not None:
            try:
                self._safety.state_changed.disconnect(self._on_safety_state)
                self._safety.event.disconnect(self._on_safety_event)
            except (RuntimeError, TypeError):
                pass
        self._safety = controller
        if controller is not None:
            controller.state_changed.connect(self._on_safety_state)
            controller.event.connect(self._on_safety_event)
            self._on_safety_state(controller.state if hasattr(controller, "state") else "IDLE")

    def _on_safety_state(self, state):
        if (state == "SAFE_STOP" and self._step_capture is not None
                and self._step_capture.is_active):
            self._step_capture.stop()
            self._result_text.append("  ⚠ 安全停机触发：阶跃测试中止，setpoint 已回滚到基线。")
            self._clear_step_state()
        monitoring = state == "MONITORING"
        safe_stop = state == "SAFE_STOP"
        self._apply_btn.setEnabled(state == "IDLE")
        self._confirm_btn.setEnabled(monitoring)
        self._revert_btn.setEnabled(monitoring)
        self._clear_safe_btn.setVisible(safe_stop)
        labels = {
            "IDLE": "状态: IDLE（可写入）",
            "MONITORING": "状态: MONITORING（看门狗观察中）",
            "SAFE_STOP": "状态: SAFE_STOP（设备已停机，需人工检查）",
        }
        self._safety_status.setText(labels.get(state, f"状态: {state}"))

    def _on_safety_event(self, level, message):
        icons = {"info": "✓", "warning": "⚠", "error": "✗"}
        self._result_text.append(f"\n{icons.get(level, '•')} {message}")
    def set_connected(self, connected: bool):
        self._connected = connected
        if connected:
            self.refresh_loop_values()