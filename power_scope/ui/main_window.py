"""配置驱动的主窗口 — 所有交互均有完整反馈"""
import os
import sys
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QTabWidget, QComboBox, QFrame,
    QStatusBar, QMessageBox, QFileDialog, QLineEdit, QDialog,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction
from .theme import build_stylesheet, get_theme
from .serial_monitor_view import SerialMonitorView
from .variable_inspector_view import VariableInspectorView
from .tuning_view import TuningView
from .dashboard_view import DashboardView
from .scope_view import ScopeView
from .dialogs import AboutDialog
from ..config.device_profile import DeviceProfile


class MainWindow(QMainWindow):
    def __init__(self, profile: DeviceProfile):
        super().__init__()
        self._profile = profile
        self.setWindowTitle(f"PowerScope — {profile.name}")
        self.setMinimumSize(920, 600)
        self._apply_initial_geometry(1280, 800)
        self.setStyleSheet(build_stylesheet(profile.theme))
        from .theme import apply_pyqtgraph_theme
        apply_pyqtgraph_theme(profile.theme)  # 之后新建的 pyqtgraph 图表跟随主题

        # 会话控制器 — 统一管理 Transport + ProtocolEngine + EventBus
        from ..session.session_controller import SessionController
        self._session = SessionController(parent=self)

        # 安全护栏 — 参数写入安全检查与回退
        from ..core.guardrails import Guardrails
        self._guardrails = Guardrails(profile)

        # 调试会话服务 — 协议事务 + 流解码（真实数据闭环）
        from ..core.debug_service import DebugService
        self._debug = DebugService(session=self._session, profile=profile, parent=self)
        self._symbols = {}          # elf_symbol(符号名) -> ElfVariable，加载 ELF 后填充
        from ..core.streaming_manager import StreamingManager
        self._stream = StreamingManager()  # 采样通道集合(状态+纯逻辑，可单测)
        self._wave_capture = None
        self._wave_live_active = False
        self._wave_live_pending = False
        self._wave_live_status_pending = False
        self._last_wave_live_diagnostics = {}
        self._last_wave_capture = None
        self._wave_status_timer = QTimer(self)
        self._wave_status_timer.setSingleShot(True)
        self._wave_status_timer.setInterval(20)
        self._wave_status_timer.timeout.connect(self._poll_wave_status)
        self._wave_live_status_timer = QTimer(self)
        self._wave_live_status_timer.setSingleShot(True)
        self._wave_live_status_timer.setInterval(500)
        self._wave_live_status_timer.timeout.connect(self._poll_wave_live_status)

        self._build_menu()
        self._build_toolbar()
        self._build_tabs()          # 视图必须先于事件订阅创建
        self._build_statusbar()

        self._subscribe_events()    # 在所有视图就绪后订阅事件
        # 此时 _serial_view, _var_view, _tune_view 均已创建，事件处理安全

        # 模拟数据定时器
        self._sim_timer = QTimer(self)
        self._sim_timer.timeout.connect(self._on_sim_tick)
        self._sim_counter = 0
        self._log_status(f"就绪 — 设备配置: {profile.name} | 请点击「连接设备」开始")

    # 流式采集状态委托给 StreamingManager（保持既有属性名与外部/测试兼容）
    @property
    def _streaming(self): return self._stream.streaming
    @_streaming.setter
    def _streaming(self, v): self._stream.streaming = v
    @property
    def _stream_list_id(self): return self._stream.stream_list_id
    @_stream_list_id.setter
    def _stream_list_id(self, v): self._stream.stream_list_id = v
    @property
    def _profile_channels(self): return self._stream.profile_channels
    @_profile_channels.setter
    def _profile_channels(self, v): self._stream.profile_channels = v
    @property
    def _extra_channels(self): return self._stream.extra_channels
    @_extra_channels.setter
    def _extra_channels(self, v): self._stream.extra_channels = v

    def _subscribe_events(self):
        """订阅 EventBus 事件统一驱动 UI 状态"""
        from ..core.event_bus import EventBus
        EventBus.instance().subscribe("connection/state", self._on_connection_state)
        EventBus.instance().subscribe("elf/loaded", self._on_elf_loaded)
        EventBus.instance().subscribe("wave/data", self._on_wave_data)

    def _on_connection_state(self, event):
        """连接状态变更 → 统一更新所有视图"""
        is_connected = event.state == "connected"
        is_mock = event.transport_type == "mock"
        self._serial_view.set_connected(is_connected)
        self._var_view.set_connected(is_connected)
        self._tune_view.set_connected(is_connected)
        if event.state == "connected":
            self._connect_btn.setText("  断开设备  ")
            self._connect_btn.setObjectName("btn_danger")
            self._connect_btn.style().unpolish(self._connect_btn)
            self._connect_btn.style().polish(self._connect_btn)
            self._log_status(f"✓ 已连接 ({event.info}) — 设备: {self._profile.name}")
            if is_mock:
                # 模拟模式：无真实硬件，用演示数据驱动界面
                self._sim_timer.start(200)
            else:
                # 真机模式优先自动加载 profile 指定 ELF；事件回调只启动一次采样。
                if not self._symbols:
                    elf_path = getattr(self._profile, "elf_file", "")
                    if elf_path and os.path.exists(elf_path):
                        self._log_status(f"→ 自动加载 profile ELF: {elf_path}")
                        if self._var_view.load_elf(elf_path, show_error=False):
                            return
                    elif elf_path:
                        self._log_status(f"⚠ ELF 文件不存在: {elf_path}")
                    else:
                        self._log_status("⚠ profile 未配置 ELF 文件")
                    self._log_status("ℹ 串口已连接，等待手动加载 ELF 后启动采集")
                    return
                self._start_streaming()
        elif event.state == "disconnected":
            self._connect_btn.setText("  连接设备  ")
            self._connect_btn.setObjectName("btn_success")
            self._connect_btn.style().unpolish(self._connect_btn)
            self._connect_btn.style().polish(self._connect_btn)
            self._sim_timer.stop()
            self._stop_streaming()
            self._wave_status_timer.stop()
            self._wave_live_status_timer.stop()
            self._wave_capture = None
            self._wave_live_active = False
            self._wave_live_pending = False
            self._wave_live_status_pending = False
            self._scope.set_record_status("录波已停止：设备断开", False)
            self._scope.set_live_status("Live已停止：设备断开", False)
            self._debug.clear_pending()
            self._log_status("✓ 已断开连接")
        elif event.state == "connecting":
            self._connect_btn.setText("  连接中...  ")
            self._connect_btn.setEnabled(False)
            self._log_status(f"⏳ 正在连接 {event.info}...")
        elif event.state == "error":
            self._connect_btn.setText("  连接设备  ")
            self._connect_btn.setObjectName("btn_success")
            self._connect_btn.setEnabled(True)
            self._connect_btn.style().unpolish(self._connect_btn)
            self._connect_btn.style().polish(self._connect_btn)
            self._sim_timer.stop()
            self._stop_streaming()
            self._wave_status_timer.stop()
            self._wave_live_status_timer.stop()
            self._wave_capture = None
            self._wave_live_active = False
            self._wave_live_pending = False
            self._wave_live_status_pending = False
            self._scope.set_record_status("录波已停止：连接错误", False)
            self._scope.set_live_status("Live已停止：连接错误", False)
            self._log_status(f"✗ 连接失败: {event.info}")
            QMessageBox.warning(self, "连接失败", event.info)

    def _apply_initial_geometry(self, width, height):
        """按可用屏幕裁剪初始尺寸，避免在小屏/低分辨率下超出可视区域导致标题栏或底部不可见。"""
        from PySide6.QtGui import QGuiApplication
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry()
            width = min(width, avail.width() - 40)
            height = min(height, avail.height() - 60)
        width = max(width, self.minimumWidth())
        height = max(height, self.minimumHeight())
        self.resize(width, height)

    def _build_menu(self):
        mb = self.menuBar()

        file_menu = mb.addMenu("文件")
        file_menu.addAction(QAction("加载设备配置...", self, triggered=self._on_load_profile))
        file_menu.addAction(QAction("加载ELF文件...", self, triggered=self._on_load_elf))
        file_menu.addSeparator()
        file_menu.addAction(QAction("导出数据...", self, triggered=lambda: self._log_status("导出功能: 选择保存路径...")))
        file_menu.addSeparator()
        file_menu.addAction(QAction("退出", self, triggered=self.close))

        device_menu = mb.addMenu("设备")
        device_menu.addAction(QAction("连接", self, triggered=self._on_connect))
        device_menu.addAction(QAction("断开", self, triggered=self._on_disconnect))
        device_menu.addSeparator()
        device_menu.addAction(QAction("读取设备信息", self, triggered=self._on_get_info))
        device_menu.addAction(QAction("软复位", self, triggered=self._on_reset))

        view_menu = mb.addMenu("视图")
        from PySide6.QtGui import QActionGroup
        self._theme_group = QActionGroup(self)
        self._theme_group.setExclusive(True)
        self._theme_actions = {}
        for theme_name in ["dark", "light", "solar"]:
            act = QAction(f"主题: {theme_name}", self, checkable=True)
            act.setChecked(theme_name == self._profile.theme)
            act.triggered.connect(lambda checked, t=theme_name: self._on_theme_change(t))
            self._theme_group.addAction(act)
            view_menu.addAction(act)
            self._theme_actions[theme_name] = act
        view_menu.addSeparator()
        view_menu.addAction(QAction("编辑仪表盘布局...", self, triggered=self._open_dashboard_editor))

        help_menu = mb.addMenu("帮助")
        help_menu.addAction(QAction("使用指南", self, triggered=self._on_show_guide))
        help_menu.addAction(QAction("关于", self, triggered=self._on_about))

    def _build_toolbar(self):
        tb = self.addToolBar("主工具栏"); tb.setMovable(False)

        self._connect_btn = QPushButton("  连接设备  ")
        self._connect_btn.setObjectName("btn_success")
        self._connect_btn.clicked.connect(self._on_connect)
        tb.addWidget(self._connect_btn)

        tb.addSeparator()
        lbl = QLabel(f"  设备: {self._profile.name}  ")
        lbl.setObjectName("strong")
        tb.addWidget(lbl)

        tb.addSeparator()
        tb.addWidget(QLabel("  主题: "))
        tc = QComboBox(); tc.addItems(["dark","light","solar"])
        tc.setCurrentText(self._profile.theme)
        tc.currentTextChanged.connect(self._on_theme_change)
        tb.addWidget(tc)
        self._theme_combo = tc

        tb.addSeparator()
        prof_btn = QPushButton("切换设备...")
        prof_btn.clicked.connect(self._on_load_profile)
        tb.addWidget(prof_btn)

    def _build_safety_criteria(self):
        """从 profile 构造调参观察窗判据。"""
        from ..core.safety_controller import AnomalyCriteria
        tuning = getattr(self._profile, "tuning", {}) or {}
        cfg = tuning.get("safety", {}) or {}
        limits = {}
        for name, bounds in (cfg.get("limits", {}) or {}).items():
            if isinstance(bounds, (list, tuple)) and len(bounds) == 2:
                limits[str(name)] = (float(bounds[0]), float(bounds[1]))
        return AnomalyCriteria(
            limits=limits,
            fault_vars=set(cfg.get("fault_vars", []) or []),
            severe_ratio=float(cfg.get("severe_ratio", 5.0)),
            comms_timeout_s=float(cfg.get("comms_timeout_s", 1.0)),
            window_s=float(cfg.get("window_s", 5.0)),
        )
    def _build_tabs(self):
        from .widgets.sidebar_tabbar import SideTabBar
        self._tabs = QTabWidget()
        self._nav_bar = SideTabBar()
        self._tabs.setTabBar(self._nav_bar)
        self._tabs.setTabPosition(QTabWidget.West)
        self._tabs.setObjectName('nav_tabs')

        self._dashboard = DashboardView(self._profile)
        self._dashboard.button_clicked.connect(self._on_button_click)
        self._dashboard.param_written.connect(self._on_param_write)
        self._tabs.addTab(self._dashboard, "仪表盘")

        self._scope = ScopeView(self._profile)
        self._scope.set_available_variables([v.name for v in self._profile.variables])
        self._scope.channels_added.connect(self._on_scope_channels_added)
        self._scope.channels_removed.connect(self._on_scope_channels_removed)
        self._scope.record_requested.connect(self._on_wave_record_requested)
        self._scope.triggered_record_requested.connect(
            lambda points, tap, pre: self._on_wave_record_requested(
                points, tap, 1, pre))
        self._scope.wave_trigger_requested.connect(self._on_wave_trigger_requested)
        self._scope.live_start_requested.connect(self._on_wave_live_requested)
        self._scope.live_stop_requested.connect(self._on_wave_live_stop_requested)
        self._scope.record_abort_requested.connect(self._on_wave_abort_requested)
        self._scope.export_completed.connect(self._on_scope_export_completed)
        self._tabs.addTab(self._scope, "波形")

        self._serial_view = SerialMonitorView(session_controller=self._session)
        self._tabs.addTab(self._serial_view, "串口监控")

        self._var_view = VariableInspectorView(self._profile)
        self._var_view.set_debug_service(self._debug)
        self._var_view.plot_requested.connect(self._on_inspector_plot)
        self._tabs.addTab(self._var_view, "变量查看")

        self._tune_view = TuningView(self._profile)
        self._tune_view.set_debug_service(self._debug)
        self._tune_view.set_channel_resolver(self._resolve_channel)
        self._tune_view.set_stream_check(lambda: set(self._stream_set().keys()))
        from ..core.safety_controller import SafetyController
        self._safety = SafetyController(
            self._debug, self._tune_view._guardrails,
            self._build_safety_criteria(), parent=self)
        self._tune_view.set_safety_controller(self._safety)
        self._safety_timer = QTimer(self)
        self._safety_timer.timeout.connect(self._safety.on_tick)
        self._safety_timer.start(100)
        self._tabs.addTab(self._tune_view, "调参")

        # AI 助手 — 真实副驾驶面板（对话 + 工具调用 + 参数回填）
        from .ai_copilot_view import AICopilotView
        from .ai_tool_context import MainWindowToolContext
        self._ai_view = AICopilotView()
        self._ai_ctx = MainWindowToolContext(self)
        self._ai_view.set_tool_context(self._ai_ctx)
        self._ai_view.param_suggested.connect(self._on_ai_params)
        self._ai_view.status.connect(self._log_status)
        self._tabs.addTab(self._ai_view, "AI助手")

        # 侧边导航字形图标（不污染 tabText）
        for _i, _g in enumerate(["▦", "∿", "⇅", "≣", "⚙", "✦"]):
            self._nav_bar.set_glyph(_i, _g)

        self.setCentralWidget(self._tabs)

    def _build_statusbar(self):
        self.statusBar().showMessage("就绪")
        from .widgets.stats_bar import StatsBarWidget
        self._stats_bar = StatsBarWidget()
        self.statusBar().addPermanentWidget(self._stats_bar)
        self._last_rx = 0
        self._last_rx_t = 0.0
        self._stats_timer = QTimer(self)
        self._stats_timer.timeout.connect(self._update_stats_bar)
        self._stats_timer.start(500)

    def _update_stats_bar(self):
        """每 500ms 从 DebugService 拉取统计并刷新状态条（含 RX 速率）"""
        import time
        snap = self._debug.stats_snapshot()
        now = time.time()
        rate = 0
        if self._last_rx_t:
            dt = now - self._last_rx_t
            if dt > 0:
                rate = max(0, (snap["bytes_received"] - self._last_rx) / dt)
        self._last_rx = snap["bytes_received"]
        self._last_rx_t = now
        self._stats_bar.update_stats(
            snap, connected=self._session.is_connected, rate_bps=rate)

    # ===== 交互处理 =====

    def _on_connect(self):
        if self._session.is_connected:
            self._stop_streaming()
            self._session.disconnect()
        elif self._session.state == "connecting":
            self._log_status("⏳ 连接进行中，请等待...")
            return
        else:
            # 检查串口监控视图的模拟模式开关
            if hasattr(self._serial_view, '_sim_check') and self._serial_view._sim_check.isChecked():
                self._session.connect_mock()
            else:
                # 从串口监控视图获取配置
                port_text = self._serial_view._port_combo.currentText().strip()
                port = port_text.split(" - ")[0] if " - " in port_text else port_text
                baudrate = int(self._serial_view._baud_combo.currentText())
                # 数据位/校验/停止位同步传给会话层（此前被忽略，永远是 8N1）
                bytesize = int(self._serial_view._data_bits.currentText())
                parity = {"None": "N", "Even": "E", "Odd": "O",
                          "Mark": "M", "Space": "S"}.get(
                    self._serial_view._parity.currentText(), "N")
                stopbits = float(self._serial_view._stop_bits.currentText())
                if not port:
                    self._log_status("⚠ 请选择串口端口")
                    QMessageBox.warning(self, "提示", "请先在「串口监控」标签页选择端口")
                    return
                self._session.connect_serial(
                    port=port,
                    baudrate=baudrate,
                    bytesize=bytesize,
                    parity=parity,
                    stopbits=stopbits,
                )

    def _on_disconnect(self):
        self._stop_streaming()
        self._session.disconnect()

    def _on_get_info(self):
        if not self._session.is_connected:
            self._info("提示", "请先连接设备")
            return
        if self._session._transport_type() != "serial":
            self._info("设备信息", "模拟模式：无真实设备信息。\n请连接真实串口后再读取。")
            return
        from ..core.debug_service import DebugService

        def on_info(resp):
            if resp.get("status", 0) != 0:
                self._info("设备信息", f"GET_INFO 失败: status={resp.get('status')}")
                return
            d = DebugService.parse_device_info(resp.get("payload", b""))
            if not d:
                self._info("设备信息", "GET_INFO 响应无法解析")
                return
            self._info("设备信息",
                f"型号: {d['model']}\n"
                f"主频: {d['cpu_freq_hz'] / 1e6:.0f} MHz\n"
                f"协议版本: 0x{d['protocol_ver']:04X}\n"
                f"固件版本: {d['fw_version']}\n"
                f"ELF CRC: 0x{d['elf_crc']:08X}")

        self._debug.get_info(callback=on_info)
        self._log_status("→ 读取设备信息 (GET_INFO)...")

    def _on_reset(self):
        if not self._session.is_connected:
            self._log_status("⚠ 设备未连接")
            return
        reply = QMessageBox.question(self, "确认复位", "确定要软复位MCU吗?\n设备将重启。", QMessageBox.Yes|QMessageBox.No)
        if reply == QMessageBox.Yes:
            if self._session._transport_type() == "serial":
                try:
                    self._debug.reset()
                    self._log_status("✓ 已发送复位命令")
                except Exception as e:
                    self._log_status(f"✗ 复位失败: {e}")
            else:
                self._log_status("✓ 已发送复位命令 (模拟)")

    def apply_profile(self, profile):
        """热重载设备配置：更新标题/主题/护栏并尽力刷新各视图，无需重启。"""
        self._profile = profile
        self.setWindowTitle(f"PowerScope — {profile.name}")
        self._on_theme_change(profile.theme)  # 样式表 + pyqtgraph + 图表重着色一并处理
        from ..core.guardrails import Guardrails
        self._guardrails = Guardrails(profile)
        # 仪表盘：换 profile 并热重建
        self._dashboard._profile = profile
        if hasattr(self._dashboard, 'rebuild'):
            self._dashboard.rebuild()
        # 波形可选变量
        self._scope.set_available_variables([v.name for v in profile.variables])
        # 调参/变量视图更新 profile 引用
        for _v in ("_tune_view", "_var_view"):
            _view = getattr(self, _v, None)
            if _view is not None:
                setattr(_view, '_profile', profile)
        if hasattr(self._tune_view, 'refresh_loop_values'):
            try:
                self._tune_view.refresh_loop_values()
            except Exception:
                pass
        # 安全判据随新 profile 更新
        try:
            self._safety.criteria = self._build_safety_criteria()
        except Exception:
            pass
        # AI 上下文指向新 profile（ctx 持有 self.mw，自然生效）
        self._log_status(f"✓ 已热重载设备配置: {profile.name}")

    def _on_load_profile(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择设备配置文件", "", "YAML 配置 (*.yaml *.yml);;所有文件 (*)")
        if not path:
            return
        try:
            from ..config.device_profile import load_profile
            new_profile = load_profile(path)
            self.apply_profile(new_profile)
            self._info("配置已热重载", f"设备: {new_profile.name}\n类型: {new_profile.device_type}\n变量: {len(new_profile.variables)} 个\n按钮: {len(new_profile.control_buttons)} 个\n\n仪表盘/波形/调参/主题已即时刷新，无需重启。")
        except Exception as e:
            self._info("加载失败", f"无法加载配置文件:\n{e}")

    def _on_load_elf(self):
        self._tabs.setCurrentWidget(self._var_view)
        self._var_view._on_load_elf()

    def _open_dashboard_editor(self):
        """打开可视化仪表盘编辑器；应用后热重建仪表盘页。"""
        from .editor.editor_window import DashboardEditor
        self._editor = DashboardEditor(self._profile, parent=self)
        self._editor.saved.connect(self._on_dashboard_saved)
        self._editor.show()

    def _on_dashboard_saved(self, profile):
        self._profile = profile
        if hasattr(self._dashboard, 'rebuild'):
            self._dashboard.rebuild()
        self._log_status("✓ 仪表盘布局已更新")

    def _on_theme_change(self, theme):
        if theme not in ("dark", "light", "solar"):
            return
        from .theme import apply_pyqtgraph_theme, set_current_theme
        set_current_theme(theme)
        self.setStyleSheet(build_stylesheet(theme))
        apply_pyqtgraph_theme(theme)
        # 菜单勾选与工具栏下拉双向同步（blockSignals 防递归）
        act = getattr(self, "_theme_actions", {}).get(theme)
        if act is not None and not act.isChecked():
            act.setChecked(True)
        combo = getattr(self, "_theme_combo", None)
        if combo is not None and combo.currentText() != theme:
            combo.blockSignals(True)
            combo.setCurrentText(theme)
            combo.blockSignals(False)
        # 已存在的图表/组件重着色
        scope = getattr(self, "_scope", None)
        if scope is not None:
            scope._plot.apply_theme(theme)
        dash = getattr(self, "_dashboard", None)
        if dash is not None:
            for w in dash._widgets.values():
                if hasattr(w, "apply_theme"):
                    w.apply_theme(theme)
        self._log_status(f"主题已切换: {theme}")

    def _on_button_click(self, btn_id, action, value):
        btn = next((b for b in self._profile.control_buttons if b.id == btn_id), None)
        if not btn:
            return
        if not self._session.is_connected:
            self._info("提示", f"请先连接设备后再执行操作:\n\n按钮: {btn.label}\n动作: {action}")
            return
        if action == "device_control":
            if self._session._transport_type() == "serial":
                running = str(value).lower() in ("1", "start", "true", "on")
                self._debug.device_control(running)
                self._log_status(f"✓ {btn.label} → 设备{'启动' if running else '停止'}命令已下发")
            else:
                self._log_status(f"✓ {btn.label} → 设备控制 (模拟)")
        elif action == "write_var":
            self._write_var_to_device(self._profile.find_var(btn.target_var), value)
            self._log_status(f"✓ {btn.label} → 写入 {btn.target_var} = {value}")
        elif action == "run_script":
            self._log_status(f"✓ {btn.label} → 执行脚本: {value}")
        else:
            self._log_status(f"✓ {btn.label} → {action}")

    def _on_param_write(self, var_name, raw_value):
        if not self._session.is_connected:
            self._info("提示", "请先连接设备后再写入参数")
            return
        var = self._profile.find_var(var_name)
        display = var.display_name if var else var_name

        # 安全护栏检查
        result = self._guardrails.validate(var_name, raw_value)
        if not result.allowed:
            self._log_status(f"✗ 写入被拒绝: {display}")
            return

        final_value = result.clamped_value
        if result.message != "OK":
            self._log_status(f"⚠ 写入修正: {display} {result.message}")

        # 真实下发到 MCU（串口模式且符号地址已解析）
        self._write_var_to_device(var, final_value)
        # 记录写入
        self._guardrails.record(var_name, final_value)
        self._log_status(f"✓ 写入参数 {display} = {final_value}")

    def _write_var_to_device(self, var, value):
        """已连真实串口且符号地址已解析时，把值真正写入 MCU 内存"""
        if var is None or self._session._transport_type() != "serial":
            return
        sym = self._symbols.get(var.elf_symbol)
        if sym is None:
            self._log_status(f"⚠ {var.elf_symbol} 未在 ELF 解析到地址，未下发（仅本地记录）")
            return
        from ..debug.elf_parser import encode_value
        try:
            data = encode_value(value, sym.type_name)
            self._debug.write_memory(int(sym.address), data)
        except Exception as e:
            self._log_status(f"✗ 下发失败: {e}")

    def _on_show_guide(self):
        guide_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))), "docs", "user_guide.md")
        if getattr(sys, 'frozen', False):
            guide_path = os.path.join(os.path.dirname(sys.executable), "_internal", "docs", "user_guide.md")
        if os.path.exists(guide_path):
            with open(guide_path, 'r', encoding='utf-8') as f:
                content = f.read()
            dlg = QDialog(self)
            dlg.setWindowTitle("使用指南"); dlg.resize(700, 600)
            from PySide6.QtWidgets import QTextEdit
            te = QTextEdit(); te.setReadOnly(True)
            te.setPlainText(content)
            lay = QVBoxLayout(dlg); lay.addWidget(te)
            dlg.exec()
        else:
            self._info("使用指南", "指南文件未找到，请参考 docs/user_guide.md")

    def _on_about(self):
        AboutDialog(self).exec()

    def _on_elf_loaded(self, event):
        """ELF 加载完成 → 缓存符号表；若已连真实串口则（重新）启动数据流"""
        variables = getattr(event, "variables", None) or []
        self._symbols = {v.name: v for v in variables}
        self._log_status(f"✓ ELF 符号已就绪: {len(self._symbols)} 个，可用于实时采集")
        self._scope.set_available_variables(
            [v.name for v in self._profile.variables] + sorted(self._symbols.keys()))
        self._tune_view.refresh_loop_values()
        if (self._session.is_connected
                and self._session._transport_type() == "serial"):
            self._start_streaming()

    def _start_streaming(self):
        """连接真实设备后：把 profile 变量解析为采样通道并启动数据流。"""
        from ..core.debug_service import build_sample_channels
        if not self._symbols:
            self._log_status("⚠ 未加载 ELF：无法采集真实变量，请先「加载ELF文件」")
            return
        channels = build_sample_channels(self._profile, self._symbols)
        self._profile_channels = {c.name: c for c in channels}
        missing = self._safety.set_stream_channels(self._profile_channels)
        if missing:
            self._log_status(
                "⚠ 安全监测变量未进入流，调参已禁用: "
                + ", ".join(sorted(missing)))
        if not self._safety.criteria.limits:
            self._log_status(
                "⚠ 未配置模拟量安全限值；当前仅故障码与通信超时保护有效")
        if not self._stream_set():
            self._log_status("⚠ 配置变量均无法在 ELF 中解析地址，未启动采集")
            return
        self._apply_stream_channels()

    def _stream_set(self):
        """慢速 List 0；高速示波器通道由 Wave 会话独立配置。"""
        return self._stream.stream_set()

    def _stream_period_us(self):
        from ..core.streaming_manager import StreamingManager
        return StreamingManager.compute_period_us(self._profile.variables)

    def _apply_stream_channels(self):
        """把当前通道集合下发为采样列表并启动流（串口模式，ACK 串行）。可重复调用以更新通道。"""
        if not self._session.is_connected or self._session._transport_type() != "serial":
            return
        channels = list(self._stream_set().values())
        if not channels:
            return
        if len(channels) > 32:
            self._log_status(f"⚠ 采样通道 {len(channels)} 超过单列表上限 32，仅取前 32 个")
            channels = channels[:32]
        period_us = self._stream_period_us()
        lid = self._stream_list_id
        n = len(channels)

        def on_started(resp):
            if resp.get("status", 0) == 0:
                self._streaming = True
                self._log_status(f"✓ 实时采集运行中: {n} 通道 @ {period_us}us")
            else:
                self._log_status(f"✗ START_STREAM 被拒: status={resp.get('status')}")

        def on_setup(resp):
            if resp.get("status", 0) != 0:
                self._log_status(f"✗ SET_SAMPLE 被拒: status={resp.get('status')}")
                return
            self._debug.start_stream(lid, callback=on_started)

        try:
            self._debug.setup_sample_list(lid, period_us, channels, callback=on_setup)
            self._log_status(f"→ 已下发采样列表 ({n} 通道 @ {period_us}us)，等待确认...")
        except Exception as e:
            self._log_status(f"✗ 启动采集失败: {e}")

    def _resolve_channel(self, name):
        """通道名 -> SampleChannel：优先使用已选高速通道，再解析 profile/ELF。"""
        from ..core.debug_service import SampleChannel, build_sample_channels
        if name in self._extra_channels:
            return self._extra_channels[name]
        if name in self._profile_channels:
            return self._profile_channels[name]
        chans = build_sample_channels(self._profile, self._symbols, names={name})
        if chans:
            return chans[0]
        sym = self._symbols.get(name)
        if sym is not None and getattr(sym, "size", 0) in (1, 2, 4, 8):
            return SampleChannel(name=name, address=int(sym.address), size=int(sym.size),
                                 type_name=getattr(sym, "type_name", "uint32_t") or "uint32_t")
        return None

    def _on_scope_channels_added(self, names):
        """解析并登记高速 Wave 通道，不改写慢速 List 0。"""
        for name in names:
            if name in self._extra_channels:
                continue
            ch = self._resolve_channel(name)
            if ch is None:
                self._log_status(f"⚠ 波形通道 {name} 无法解析地址（需加载匹配 ELF）")
                continue
            self._extra_channels[name] = ch

    def _on_inspector_plot(self, specs):
        """变量查看器「选中→波形」：按规格纳入采样集合、加入示波器并切换到波形页。"""
        from ..core.debug_service import SampleChannel
        names = []
        for sp in specs:
            name = sp.get("name")
            if not name:
                continue
            self._extra_channels[name] = SampleChannel(
                name=name, address=int(sp["address"]), size=int(sp["size"]),
                type_name=sp.get("type_name", "uint32_t") or "uint32_t")
            names.append(name)
        if names:
            self._scope.add_channels_external(names)
            self._tabs.setCurrentWidget(self._scope)

    def _on_scope_channels_removed(self, names):
        for name in names:
            self._extra_channels.pop(name, None)

    def _on_scope_export_completed(self, csv_path):
        """Write exact Recorder bytes and self-describing metadata beside CSV."""
        capture = self._last_wave_capture
        if not capture:
            return
        import json
        from pathlib import Path

        csv_path = Path(csv_path)
        raw_path = csv_path.with_suffix(".wave.bin")
        meta_path = csv_path.with_suffix(".wave.json")
        metadata = {
            "format": "PowerScope Wave Recorder v2",
            "raw_file": raw_path.name,
            "endianness": "little",
            "layout": "sample-major interleaved channel raw bytes",
            "capture_id": capture["capture_id"],
            "mode": capture.get("mode", 0),
            "tap_id": capture["tap_id"],
            "period_us": capture["period_us"],
            "points": capture["points"],
            "trigger_index": capture.get("trigger_index", 0),
            "diagnostics": capture.get("diagnostics", {}),
            "channels": [
                {
                    "name": channel.name,
                    "address": channel.address,
                    "size": channel.size,
                    "type_name": channel.type_name,
                    "scale": channel.scale,
                    "offset": channel.offset,
                    "unit": channel.unit,
                    "sequence_address": channel.sequence_address,
                }
                for channel in capture["channels"]
            ],
        }
        try:
            raw_path.write_bytes(capture["raw"])
            meta_path.write_text(
                json.dumps(metadata, ensure_ascii=False, indent=2),
                encoding="utf-8")
            self._log_status(
                f"✓ 已导出 CSV、原始录波 {raw_path.name} 和元数据 {meta_path.name}")
        except Exception as exc:
            QMessageBox.warning(self, "录波原始数据导出失败", str(exc))

    def _on_wave_live_requested(self, tap_id):
        if not self._session.is_connected:
            self._scope.set_live_status("Live失败：设备未连接", False)
            return
        if self._wave_capture is not None or self._wave_live_pending:
            self._scope.set_live_status("Live失败：已有 Wave 会话", False)
            return
        channels = []
        for name in self._scope.plotted_channels():
            channel = self._resolve_channel(name)
            if channel is None:
                self._scope.set_live_status(f"Live失败：{name} 无法解析", False)
                return
            channels.append(channel)
        if not channels or len(channels) > 16:
            self._scope.set_live_status("Live要求 1..16 个显式波形通道", False)
            return
        row_bytes = sum(channel.size for channel in channels)
        if row_bytes <= 0 or row_bytes > 64:
            self._scope.set_live_status("Live单点宽度必须为 1..64 字节", False)
            return
        points = min(4096, (128 * 1024) // (row_bytes + 4) - 1)
        self._wave_live_pending = True
        self._scope.set_live_status(
            f"正在配置无损Live：{len(channels)}通道 @ 25us", False)

        def on_arm(resp):
            self._wave_live_pending = False
            if resp.get("status") != 0:
                self._scope.set_live_status(
                    f"Live ARM被拒：status={resp.get('status')}", False)
                return
            self._wave_live_active = True
            self._scope.set_live_status(
                "无损Live运行中；不可压缩时RAW回退，缺口会显式报告", True)
            self._wave_live_status_timer.start()

        def on_config(resp):
            if resp.get("status") != 0:
                self._wave_live_pending = False
                self._scope.set_live_status(
                    f"Live CONFIG被拒：status={resp.get('status')}", False)
                return
            self._debug.arm_wave(callback=on_arm)

        try:
            from ..core.debug_service import WAVE_MODE_LIVE
            self._debug.configure_wave(
                channels, points, tap_id=int(tap_id), period_us=25,
                callback=on_config, mode=WAVE_MODE_LIVE)
        except Exception as exc:
            self._wave_live_pending = False
            self._scope.set_live_status(f"Live失败：{exc}", False)

    def _on_wave_live_stop_requested(self):
        if not self._wave_live_active and not self._wave_live_pending:
            self._scope.set_live_status("Live未运行", False)
            return
        self._debug.abort_wave(callback=lambda _resp: None)
        self._wave_live_status_timer.stop()
        self._wave_live_active = False
        self._wave_live_pending = False
        self._wave_live_status_pending = False
        self._scope.set_live_status("Live已停止", False)

    def _poll_wave_live_status(self):
        if not self._wave_live_active or self._wave_live_status_pending:
            return
        self._wave_live_status_pending = True

        def on_status(resp):
            self._wave_live_status_pending = False
            if not self._wave_live_active:
                return
            if resp.get("status") != 0:
                self._scope.set_live_status(
                    f"Live运行中；状态查询失败 status={resp.get('status')}", True)
                self._wave_live_status_timer.start()
                return
            status = self._debug.parse_wave_status(resp.get("payload", b""))
            if status is None or status.state != 7:
                self._wave_live_active = False
                self._scope.set_live_status("Live已由设备停止", False)
                return
            processed_points = (status.live_raw_bytes / status.row_bytes
                                if status.row_bytes else 0.0)
            bits_per_point = (status.live_encoded_bytes * 8.0 / processed_points
                              if processed_points else 0.0)
            isr_us = status.capture_isr_max_cycles / 240.0
            self._last_wave_live_diagnostics = {
                "capture_id": status.capture_id,
                "captured_points": status.captured_points,
                "overflow_count": status.overflow_count,
                "bits_per_sample_time": bits_per_point,
                "tx_high_water": status.tx_high_water,
                "tx_low_water": status.tx_low_water,
                "tx_high_overflow": status.tx_high_overflow,
                "tx_low_overflow": status.tx_low_overflow,
                "capture_isr_max_cycles": status.capture_isr_max_cycles,
                "atomic_retries": status.atomic_retries,
                "atomic_failures": status.atomic_failures,
                "non_atomic_mask": status.non_atomic_mask,
            }
            self._scope.set_live_status(
                f"无损Live：{bits_per_point:.2f} bit/采样时刻；"
                f"丢点 {status.overflow_count}；低FIFO峰值 {status.tx_low_water}，"
                f"溢出 {status.tx_low_overflow}；采样路径最大 {isr_us:.2f} us",
                True)
            self._wave_live_status_timer.start()

        try:
            self._debug.get_wave_status(callback=on_status)
        except Exception as exc:
            self._wave_live_status_pending = False
            self._scope.set_live_status(f"Live状态查询失败：{exc}", True)
            self._wave_live_status_timer.start()

    def _on_wave_record_requested(self, points, tap_id,
                                  mode=0, pretrigger_points=0):
        """只录示波器中显式选择的通道，不合并慢速 profile 列表。"""
        if not self._session.is_connected:
            self._scope.set_record_status("录波失败：设备未连接", False)
            return
        if self._wave_capture is not None:
            return
        if self._wave_live_active or self._wave_live_pending:
            self._scope.set_record_status("录波失败：请先停止Live", False)
            return
        channels = []
        for name in self._scope.plotted_channels():
            channel = self._resolve_channel(name)
            if channel is None:
                self._scope.set_record_status(f"录波失败：{name} 无法从匹配 ELF 解析", False)
                return
            channels.append(channel)
        if not channels:
            self._scope.set_record_status("录波失败：请先添加至少一个波形通道", False)
            return
        if len(channels) > 16:
            self._scope.set_record_status("录波失败：高速录波最多 16 个通道", False)
            return
        row_bytes = sum(channel.size for channel in channels)
        if row_bytes <= 0 or row_bytes > 64:
            self._scope.set_record_status("录波失败：单点总宽度必须为 1..64 字节", False)
            return
        requested_points = int(points)
        max_points = (128 * 1024) // row_bytes
        actual_points = min(requested_points, max_points)
        if actual_points != requested_points:
            self._log_status(f"⚠ 录波点数按 MCU 128KB 缓冲区限幅为 {actual_points} 点")
        if int(mode) == 1:
            pretrigger_points = min(
                actual_points - 1,
                max(0, int(pretrigger_points) * actual_points // requested_points))
        self._wave_capture = {
            "channels": channels, "tap_id": int(tap_id), "period_us": 25,
            "points": actual_points, "row_bytes": row_bytes,
            "mode": int(mode), "pretrigger_points": int(pretrigger_points),
            "capture_id": None, "raw": bytearray(), "request_pending": True,
            "auto_upload": False, "next_block_seq": 1, "status": None,
        }
        self._scope.set_record_status(
            f"正在配置：{len(channels)} 通道，{actual_points} 点，{row_bytes} B/点", True)

        def on_arm(resp):
            capture = self._wave_capture
            if capture is None:
                return
            capture["request_pending"] = False
            if resp.get("status") != 0:
                self._finish_wave_error(f"WAVE_ARM 被拒：status={resp.get('status')}")
                return
            if capture["mode"] == 1:
                self._scope.set_trigger_enabled(True)
                self._scope.set_record_status(
                    f"已布防前触发；目标前触发 {capture['pretrigger_points']} 点", True)
            else:
                self._scope.set_record_status(
                    f"正在采集 0/{capture['points']} 点（25us）", True)
            self._wave_status_timer.start()

        def on_config(resp):
            capture = self._wave_capture
            if capture is None:
                return
            capture["request_pending"] = False
            if resp.get("status") != 0:
                self._finish_wave_error(f"WAVE_CONFIG 被拒：status={resp.get('status')}")
                return
            config = self._debug.parse_wave_config(resp.get("payload", b""))
            if not config:
                self._finish_wave_error("WAVE_CONFIG 响应长度错误")
                return
            capture["capture_id"] = config["capture_id"]
            capture["request_pending"] = True
            self._debug.arm_wave(callback=on_arm)

        try:
            options = {"mode": int(mode)}
            if int(mode) == 1:
                options.update({
                    "pretrigger_points": int(pretrigger_points),
                    "posttrigger_points": actual_points - int(pretrigger_points),
                })
            self._debug.configure_wave(
                channels, actual_points, tap_id=int(tap_id), period_us=25,
                callback=on_config, **options)
        except Exception as exc:
            self._finish_wave_error(str(exc))

    def _poll_wave_status(self):
        capture = self._wave_capture
        if capture is None or capture.get("request_pending"):
            return
        capture["request_pending"] = True

        def on_status(resp):
            current = self._wave_capture
            if current is None:
                return
            current["request_pending"] = False
            if resp.get("status") != 0:
                self._finish_wave_error(f"WAVE_STATUS 失败：status={resp.get('status')}")
                return
            status = self._debug.parse_wave_status(resp.get("payload", b""))
            if status is None or status.capture_id != current["capture_id"]:
                self._finish_wave_error("WAVE_STATUS 元数据不匹配")
                return
            if status.state == 6:
                self._scope.set_trigger_enabled(True)
                self._scope.set_record_status(
                    f"已布防：前触发已有 {status.pretrigger_points}/"
                    f"{current['pretrigger_points']} 点；点击‘触发’", True)
                self._wave_status_timer.start()
            elif status.state == 2:
                if current.get("mode") == 1:
                    message = (f"触发后采集 {status.posttrigger_points}/"
                               f"{status.total_points - current['pretrigger_points']} 点")
                else:
                    message = f"正在采集 {status.captured_points}/{status.total_points} 点（25us）"
                self._scope.set_record_status(message, True)
                self._wave_status_timer.start()
            elif status.state in (3, 4, 5):
                self._scope.set_trigger_enabled(False)
                current["points"] = status.captured_points
                current["status"] = status
                self._scope.set_record_status(
                    f"采集完成，正在读取 0/{status.captured_points * status.row_bytes} 字节", True)
                self._begin_wave_upload()
            else:
                self._finish_wave_error(f"录波状态异常：state={status.state}")

        self._debug.get_wave_status(callback=on_status)

    def _begin_wave_upload(self):
        capture = self._wave_capture
        if capture is None or capture.get("request_pending"):
            return
        capture["request_pending"] = True
        capture["auto_upload"] = True

        def on_started(resp):
            current = self._wave_capture
            if current is None:
                return
            current["request_pending"] = False
            if resp.get("status") != 0:
                # Compatibility fallback for v1 firmware without automatic upload.
                current["auto_upload"] = False
                self._download_wave_chunk()

        self._debug.start_wave_upload(
            offset=len(capture["raw"]), callback=on_started)

    def _on_wave_data(self, block):
        capture = self._wave_capture
        if (capture is None or not capture.get("auto_upload") or
                getattr(block, "encoding", -1) != 0 or
                block.capture_id != capture.get("capture_id")):
            return
        if (block.offset != len(capture["raw"]) or not block.data or
                block.block_seq != capture["next_block_seq"]):
            self._finish_wave_error("自动上传分片偏移、序号或长度不匹配")
            return
        capture["next_block_seq"] = (block.block_seq + 1) & 0xFFFF
        capture["raw"].extend(block.data)
        total = capture["points"] * capture["row_bytes"]
        self._scope.set_record_status(
            f"采集完成，正在读取 {len(capture['raw'])}/{total} 字节", True)
        if len(capture["raw"]) >= total:
            capture["auto_upload"] = False
            QTimer.singleShot(0, self._download_wave_chunk)

    def _download_wave_chunk(self):
        capture = self._wave_capture
        if capture is None or capture.get("request_pending"):
            return
        expected_bytes = capture["points"] * capture["row_bytes"]
        if capture.get("auto_upload") and len(capture["raw"]) < expected_bytes:
            return
        if len(capture["raw"]) >= expected_bytes:
            try:
                decoded = self._debug.decode_wave_capture(
                    bytes(capture["raw"]), capture["channels"], capture["period_us"])
            except Exception as exc:
                self._finish_wave_error(f"录波解码失败：{exc}")
                return
            status = capture.get("status")
            diagnostics = {
                "capture_isr_max_cycles": getattr(
                    status, "capture_isr_max_cycles", 0),
                "atomic_retries": getattr(status, "atomic_retries", 0),
                "atomic_failures": getattr(status, "atomic_failures", 0),
                "non_atomic_mask": getattr(status, "non_atomic_mask", 0),
                "tx_high_overflow": getattr(status, "tx_high_overflow", 0),
                "tx_low_overflow": getattr(status, "tx_low_overflow", 0),
                "overflow_count": getattr(status, "overflow_count", 0),
                "pretrigger_points": getattr(status, "pretrigger_points", 0),
                "posttrigger_points": getattr(status, "posttrigger_points", 0),
            }
            self._last_wave_capture = {
                "raw": bytes(capture["raw"]), "channels": list(capture["channels"]),
                "tap_id": capture["tap_id"], "period_us": capture["period_us"],
                "points": capture["points"], "capture_id": capture["capture_id"],
                "mode": capture.get("mode", 0),
                "trigger_index": diagnostics["pretrigger_points"],
                "diagnostics": diagnostics,
            }
            self._scope.show_record_capture(decoded)
            max_cycles = diagnostics["capture_isr_max_cycles"]
            timing = (f"；采样路径最大 {max_cycles} cycles/"
                      f"{max_cycles / 240.0:.2f} us" if max_cycles else "")
            self._scope.set_record_status(
                f"录波完成：{capture['points']} 点，{len(capture['raw'])} 字节{timing}",
                False)
            self._log_status(
                f"✓ 25us 录波完成：capture={capture['capture_id']}，"
                f"{capture['points']} 点，tap={capture['tap_id']}")
            self._wave_capture = None
            return
        capture["request_pending"] = True
        offset = len(capture["raw"])

        def on_data(resp):
            current = self._wave_capture
            if current is None:
                return
            current["request_pending"] = False
            if resp.get("status") != 0:
                self._finish_wave_error(f"WAVE_UPLOAD 失败：status={resp.get('status')}")
                return
            block = self._debug.parse_wave_data(resp.get("payload", b""))
            if (block is None or block.capture_id != current["capture_id"]
                    or block.offset != len(current["raw"]) or block.encoding != 0
                    or block.block_seq != current["next_block_seq"]):
                self._finish_wave_error("录波分片序号、偏移或编码不匹配")
                return
            if not block.data:
                self._finish_wave_error("录波分片为空")
                return
            current["next_block_seq"] = (block.block_seq + 1) & 0xFFFF
            current["raw"].extend(block.data)
            total = current["points"] * current["row_bytes"]
            self._scope.set_record_status(
                f"采集完成，正在读取 {len(current['raw'])}/{total} 字节", True)
            QTimer.singleShot(0, self._download_wave_chunk)

        self._debug.read_wave_chunk(offset, 112, callback=on_data)

    def _on_wave_trigger_requested(self):
        capture = self._wave_capture
        if capture is None or capture.get("mode") != 1:
            return
        self._scope.set_trigger_enabled(False)

        def on_trigger(resp):
            if resp.get("status") != 0:
                self._finish_wave_error(
                    f"WAVE_TRIGGER被拒：status={resp.get('status')}")

        self._debug.trigger_wave(callback=on_trigger)

    def _on_wave_abort_requested(self):
        self._wave_status_timer.stop()
        if self._wave_capture is None:
            return
        self._debug.abort_wave(callback=lambda _resp: None)
        self._scope.set_trigger_enabled(False)
        self._wave_capture = None
        self._scope.set_record_status("录波已由用户取消", False)

    def _finish_wave_error(self, message):
        self._wave_status_timer.stop()
        self._scope.set_trigger_enabled(False)
        self._wave_capture = None
        self._scope.set_record_status(f"录波失败：{message}", False)
        self._log_status(f"✗ 录波失败：{message}")

    def _stop_streaming(self):
        """停止数据流（断开/出错时调用）"""
        if not self._streaming:
            return
        try:
            self._debug.stop_stream(self._stream_list_id)
        except Exception:
            pass
        self._streaming = False

    def _on_sim_tick(self):
        """模拟数据更新 — 通过 EventBus 发布 var/updated 事件"""
        self._sim_counter += 1
        import random, math
        from ..core.event_bus import EventBus, VarUpdatedEvent
        for var in self._profile.variables:
            if var.update_rate == 0:
                continue
            base_val = 0
            if "voltage" in var.name or "vd" in var.name: base_val = 220
            elif "current" in var.name or "id" in var.name: base_val = 10
            elif "power" in var.name: base_val = 850
            elif "freq" in var.name: base_val = 50
            elif "duty" in var.name: base_val = 50
            elif "soc" in var.name: base_val = 65
            elif "temp" in var.name: base_val = 35
            val = base_val + random.uniform(-base_val*0.05, base_val*0.05) + math.sin(self._sim_counter * 0.1) * 2
            EventBus.instance().publish("var/updated", VarUpdatedEvent(
                name=var.name,
                raw_value=val,
                phys_value=val * var.scale + var.offset,
                unit=var.unit,
                timestamp=self._sim_counter * 0.2,
                source="mock",
            ))

    def _on_ai_params(self, params):
        """AI 建议参数回填到调参页编辑框。"""
        tv = getattr(self, "_tune_view", None)
        if tv is None:
            return
        if "Kp" in params and hasattr(tv, "_kp_input"): tv._kp_input.setValue(float(params["Kp"]))
        if "Ki" in params and hasattr(tv, "_ki_input"): tv._ki_input.setValue(float(params["Ki"]))
        if "Kd" in params and hasattr(tv, "_kd_input"): tv._kd_input.setValue(float(params["Kd"]))
        self._log_status("→ AI 建议参数已填入调参页")

    def _log_status(self, msg):
        """输出状态信息到状态栏 + 持久化日志文件"""
        self.statusBar().showMessage(msg, 5000)
        # 浮层通知：仅错误/警告级别（避免 info 刷屏）
        from .widgets.toast import Toast, level_from_message
        _lvl = level_from_message(msg)
        if _lvl in ("error", "warning"):
            try:
                Toast.show_message(self, msg, _lvl)
            except Exception:
                pass
        # 同步写入日志文件（分级：✗→ERROR, ⚠→WARNING, 其他→INFO）
        from ..core.log_manager import LogManager
        log = LogManager()
        if msg.startswith("✗"):
            log.error(msg)
        elif msg.startswith("⚠"):
            log.warning(msg)
        else:
            log.info(msg)

    def _info(self, title, msg):
        QMessageBox.information(self, title, msg)

    def _cleanup(self):
        """停止全部定时器并退订 EventBus（窗口关闭时调用，确保无定时器跨测试/长期运行泄漏）。"""
        for name in (
                "_sim_timer", "_stats_timer", "_safety_timer",
                "_wave_status_timer", "_wave_live_status_timer"):
            timer = getattr(self, name, None)
            if timer is not None:
                try:
                    timer.stop()
                except Exception:
                    pass
        try:
            from ..core.event_bus import EventBus
            bus = EventBus.instance()
            bus.unsubscribe("connection/state", self._on_connection_state)
            bus.unsubscribe("elf/loaded", self._on_elf_loaded)
            bus.unsubscribe("wave/data", self._on_wave_data)
        except Exception:
            pass
        scope = getattr(self, "_scope", None)
        if scope is not None and hasattr(scope, "cleanup"):
            scope.cleanup()
        ai_ctx = getattr(self, "_ai_ctx", None)
        if ai_ctx is not None:
            ai_ctx.close()
        safety = getattr(self, "_safety", None)
        if safety is not None:
            safety.close()

    def closeEvent(self, event):
        """停止定时器/退订事件、停止采样并断开会话，确保窗口退出后串口立即释放。"""
        self._cleanup()
        try:
            self._stop_streaming()
        except Exception:
            pass
        try:
            if self._session.is_connected:
                self._session.disconnect()
        except Exception:
            pass
        super().closeEvent(event)



