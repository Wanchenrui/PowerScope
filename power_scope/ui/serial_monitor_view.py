"""串口监控视图 — Hex/ASCII 数据收发

通过可选的 session_controller 参数委托所有串口操作：
  有 session_controller → 委托连接/发送/接收
  无 session_controller → 向后兼容旧模式（直接操作串口）
"""
import time
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox,
    QTextEdit, QPushButton, QLabel, QComboBox, QCheckBox,
    QLineEdit, QSpinBox, QMessageBox
)
from PySide6.QtCore import Qt, QTimer, Signal
from .theme import ui_color, TYPOGRAPHY


class SerialMonitorView(QWidget):
    """串口监控视图: 配置 + 收发数据 + 发送区"""

    data_sent = Signal(bytes)
    data_received = Signal(bytes)

    def __init__(self, parent=None, session_controller=None):
        super().__init__(parent)
        self._session = session_controller
        self._connected = False
        self._hex_display = True
        self._hex_send = True
        self._rx_count = 0
        self._tx_count = 0
        self._serial = None
        # 显示合并冲刷: HTML 片段先进缓冲，下一事件循环回合一次性 append
        # (避免高频 RX 打爆 QTextEdit 文档; 与 EventBus 合并冲刷同一模式)
        self._pending_html = []
        self._rx_dirty = False
        self._tx_dirty = False
        self._flush_timer = QTimer(self)
        self._flush_timer.setSingleShot(True)
        self._flush_timer.setInterval(0)
        self._flush_timer.timeout.connect(self._flush_display)
        self._build_ui()
        self._setup_session_signals()
        self._log("系统就绪，请配置串口参数后点击「连接」")

    def _setup_session_signals(self):
        """连接 SessionController 的 data_sent / data_received 信号"""
        if self._session is not None:
            self._session.data_sent.connect(self._on_data_sent)
            self._session.data_received.connect(self._on_data_received)
            # 订阅连接状态事件: 恢复「连接中...」中间态 / 同步外部连接操作
            from ..core.event_bus import EventBus
            EventBus.instance().subscribe("connection/state", self._on_connection_state_event)
            self.destroyed.connect(self._unsubscribe_events)

    def _unsubscribe_events(self):
        """视图销毁时退订 EventBus，避免悬挂引用"""
        try:
            from ..core.event_bus import EventBus
            EventBus.instance().unsubscribe("connection/state", self._on_connection_state_event)
        except Exception:
            pass

    def _on_connection_state_event(self, event):
        """EventBus connection/state → 同步连接 UI（连接中 → 已连接/失败）"""
        state = getattr(event, "state", "")
        if state == "connected":
            self.set_connected(True)
            info = event.info or (
                "模拟模式" if getattr(event, "transport_type", "") == "mock" else "")
            if info:
                self._status_label.setText(f"状态: 已连接 ({info})")
        elif state == "error":
            self.set_connected(False)
            self._status_label.setText("状态: 连接失败")
        elif state == "disconnected":
            self.set_connected(False)
        # "connecting" → 保持「连接中...」中间态，由后续事件恢复

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        # ===== 串口配置区 =====
        config_group = QGroupBox("串口配置")
        config_layout = QGridLayout(config_group)
        config_layout.setSpacing(6)

        config_layout.addWidget(QLabel("端口:"), 0, 0)
        self._port_combo = QComboBox()
        self._port_combo.setEditable(True)
        self._refresh_ports()
        config_layout.addWidget(self._port_combo, 0, 1)

        refresh_btn = QPushButton("刷新")
        refresh_btn.setMinimumWidth(60)
        refresh_btn.clicked.connect(self._refresh_ports)
        config_layout.addWidget(refresh_btn, 0, 2)

        config_layout.addWidget(QLabel("波特率:"), 0, 3)
        self._baud_combo = QComboBox()
        self._baud_combo.addItems(["9600", "19200", "38400", "57600", "115200", "230400", "460800", "921600"])
        self._baud_combo.setCurrentText("115200")
        config_layout.addWidget(self._baud_combo, 0, 4)

        config_layout.addWidget(QLabel("数据位:"), 1, 0)
        self._data_bits = QComboBox()
        self._data_bits.addItems(["8", "7", "6", "5"])
        config_layout.addWidget(self._data_bits, 1, 1)

        config_layout.addWidget(QLabel("校验:"), 1, 3)
        self._parity = QComboBox()
        self._parity.addItems(["None", "Even", "Odd", "Mark", "Space"])
        config_layout.addWidget(self._parity, 1, 4)

        config_layout.addWidget(QLabel("停止位:"), 2, 0)
        self._stop_bits = QComboBox()
        self._stop_bits.addItems(["1", "1.5", "2"])
        config_layout.addWidget(self._stop_bits, 2, 1)

        # 连接按钮单独一行右对齐，避免与停止位行控件视觉断裂
        self._connect_btn = QPushButton("连接")
        self._connect_btn.setObjectName("btn_success")
        self._connect_btn.setMinimumWidth(100)
        self._connect_btn.clicked.connect(self._on_connect)
        config_layout.addWidget(self._connect_btn, 3, 0, 1, 5, Qt.AlignRight)

        layout.addWidget(config_group)

        # ===== 模拟模式开关 =====
        sim_row = QHBoxLayout()
        self._sim_check = QCheckBox("模拟模式 (无需真实设备，使用内置模拟 MCU)")
        self._sim_check.setChecked(False)  # 真机联调默认连接真实设备
        self._sim_check.stateChanged.connect(self._on_sim_toggle)
        sim_row.addWidget(self._sim_check)
        sim_row.addStretch()
        self._status_label = QLabel("状态: 未连接")
        self._status_label.setProperty("role", "err")
        sim_row.addWidget(self._status_label)
        layout.addLayout(sim_row)

        # ===== 发送区 =====
        send_group = QGroupBox("数据发送")
        send_layout = QVBoxLayout(send_group)

        send_opt = QHBoxLayout()
        self._hex_tx_check = QCheckBox("Hex发送")
        self._hex_tx_check.setChecked(True)
        send_opt.addWidget(self._hex_tx_check)

        self._repeat_check = QCheckBox("定时发送")
        self._repeat_check.stateChanged.connect(self._on_repeat_toggle)
        send_opt.addWidget(self._repeat_check)

        send_opt.addWidget(QLabel("间隔(ms):"))
        self._repeat_interval = QSpinBox()
        self._repeat_interval.setRange(10, 60000)
        self._repeat_interval.setValue(1000)
        send_opt.addWidget(self._repeat_interval)

        send_opt.addStretch()
        send_layout.addLayout(send_opt)

        input_row = QHBoxLayout()
        self._send_input = QLineEdit()
        self._send_input.setPlaceholderText("输入要发送的数据 (Hex模式: A5 5A 01 02...)")
        self._send_input.returnPressed.connect(self._on_send)
        input_row.addWidget(self._send_input)

        send_btn = QPushButton("发送")
        send_btn.setObjectName("btn_primary")
        send_btn.setMinimumWidth(80)
        send_btn.clicked.connect(self._on_send)
        input_row.addWidget(send_btn)

        send_layout.addLayout(input_row)

        quick_row = QHBoxLayout()
        quick_row.addWidget(QLabel("快捷:"))
        for label, cmd in self.ns800rt_quick_commands():
            btn = QPushButton(label)
            btn.setMinimumWidth(90)
            btn.clicked.connect(lambda checked, c=cmd: self._send_quick(c))
            quick_row.addWidget(btn)
        quick_row.addStretch()
        send_layout.addLayout(quick_row)

        layout.addWidget(send_group)

        # ===== 数据显示区（占据剩余拉伸空间） =====
        display_group = QGroupBox("数据接收")
        display_layout = QVBoxLayout(display_group)

        opt_row = QHBoxLayout()
        self._hex_rx_check = QCheckBox("Hex显示")
        self._hex_rx_check.setChecked(True)
        self._hex_rx_check.stateChanged.connect(self._on_hex_display_change)
        opt_row.addWidget(self._hex_rx_check)

        self._timestamp_check = QCheckBox("显示时间戳")
        self._timestamp_check.setChecked(True)
        opt_row.addWidget(self._timestamp_check)

        self._direction_check = QCheckBox("显示收发方向")
        self._direction_check.setChecked(True)
        opt_row.addWidget(self._direction_check)

        opt_row.addStretch()

        clear_btn = QPushButton("清空")
        clear_btn.setMinimumWidth(80)
        clear_btn.clicked.connect(self._clear_display)
        opt_row.addWidget(clear_btn)

        display_layout.addLayout(opt_row)

        self._display = QTextEdit()
        self._display.setReadOnly(True)
        self._display.setMinimumHeight(200)
        # 文档块数上限，避免长会话无界增长
        self._display.document().setMaximumBlockCount(5000)
        # display styling via QSS
        display_layout.addWidget(self._display)

        self._rx_label = QLabel("RX: 0 字节")
        self._tx_label = QLabel("TX: 0 字节")
        display_layout.addWidget(self._rx_label)
        display_layout.addWidget(self._tx_label)

        # stretch=1: 接收区占据剩余垂直空间，配置/发送区固定在上
        layout.addWidget(display_group, 1)

        self._repeat_timer = QTimer(self)
        self._repeat_timer.timeout.connect(self._on_send)

    # ------------------------------------------------------------------
    # 连接/断开 — 委托给 SessionController（如有）
    # ------------------------------------------------------------------

    def _on_connect(self):
        if self._connected:
            self._disconnect()
        else:
            self._connect()

    def _connect(self):
        if self._session is not None:
            self._connect_with_session()
        else:
            self._connect_legacy()

    def _connect_with_session(self):
        """使用 SessionController 连接"""
        try:
            if self._sim_check.isChecked():
                self._session.connect_mock()
                self._update_ui_connected("模拟模式")
                self._log("✓ 模拟模式已启动 — 无需真实硬件即可调试界面")
                self._log("  模拟设备: STM32G474 @ 170MHz, 固件 v1.0.0")
                self._log("  可使用「快捷命令」按钮发送调试帧")
            else:
                port_text = self._port_combo.currentText()
                port = port_text.split(" - ")[0] if " - " in port_text else port_text
                baudrate = int(self._baud_combo.currentText())
                # 数据位/校验/停止位同步传给会话层（此前被忽略，永远是 8N1）
                bytesize = int(self._data_bits.currentText())
                parity = {"None": "N", "Even": "E", "Odd": "O",
                          "Mark": "M", "Space": "S"}.get(
                              self._parity.currentText(), "N")
                stopbits = float(self._stop_bits.currentText())
                # 中间态: 发起连接后先置「连接中...」并禁用，
                # 最终状态由 connection/state 事件(_on_connection_state_event)恢复
                self._connect_btn.setText("连接中...")
                self._connect_btn.setEnabled(False)
                self._session.connect_serial(
                    port, baudrate,
                    bytesize=bytesize, parity=parity, stopbits=stopbits)
                # connect_serial 内部捕获异常并发布 error 事件(不抛出)，
                # 同步结果直接落定；仍为 connecting 则等待事件恢复
                if self._session.is_connected:
                    self._update_ui_connected(f"{port} @ {baudrate}")
                    self._log(f"✓ 串口已连接: {port} @ {baudrate} baud")
                elif self._session.state == "error":
                    self._update_ui_disconnected()
                    self._log(f"✗ 连接失败: {self._session.state_info}")
        except Exception as e:
            self._update_ui_disconnected()
            QMessageBox.critical(self, "连接失败", f"无法连接:\n{e}")
            self._log(f"✗ 连接失败: {e}")

    def _connect_legacy(self):
        """向后兼容：直接操作串口"""
        if self._sim_check.isChecked():
            self._update_ui_connected("模拟模式")
            self._log("✓ 模拟模式已启动 — 无需真实硬件即可调试界面")
            self._log("  模拟设备: STM32G474 @ 170MHz, 固件 v1.0.0")
            self._log("  可使用「快捷命令」按钮发送调试帧")
            self.data_received.emit(b"\xA5\x5A\x01\x07\x01\x00")
        else:
            try:
                import serial
                port_text = self._port_combo.currentText()
                port = port_text.split(" - ")[0] if " - " in port_text else port_text
                baudrate = int(self._baud_combo.currentText())
                self._serial = serial.Serial(
                    port, baudrate,
                    bytesize=int(self._data_bits.currentText()),
                    parity={
                        "None": serial.PARITY_NONE, "Even": serial.PARITY_EVEN,
                        "Odd": serial.PARITY_ODD, "Mark": serial.PARITY_MARK,
                        "Space": serial.PARITY_SPACE,
                    }.get(self._parity.currentText(), serial.PARITY_NONE),
                    stopbits=float(self._stop_bits.currentText()),
                    timeout=0.1
                )
                self._update_ui_connected(f"{port} @ {baudrate}")
                self._log(f"✓ 串口已连接: {port} @ {baudrate} baud")
                self._rx_timer = QTimer()
                self._rx_timer.timeout.connect(self._poll_serial)
                self._rx_timer.start(50)
            except Exception as e:
                QMessageBox.critical(self, "连接失败", f"无法打开串口:\n{e}")
                self._log(f"✗ 连接失败: {e}")

    def _disconnect(self):
        if self._session is not None:
            self._session.disconnect()
        self._update_ui_disconnected()
        if self._serial:
            self._serial.close()
            self._serial = None
        if hasattr(self, '_rx_timer'):
            self._rx_timer.stop()
        self._log("✓ 已断开连接")

    def _update_ui_connected(self, info):
        self.set_connected(True)
        self._status_label.setText(f"状态: 已连接 ({info})")

    def _update_ui_disconnected(self):
        self.set_connected(False)

    def set_connected(self, connected: bool):
        """同步连接状态到 UI: 按钮文本/样式 + 状态标签 + 使能"""
        self._connected = connected
        self._connect_btn.setEnabled(True)
        if connected:
            self._connect_btn.setText("断开")
            self._connect_btn.setObjectName("btn_danger")
            self._status_label.setText("状态: 已连接")
            self._status_label.setProperty("role", "ok")
        else:
            self._connect_btn.setText("连接")
            self._connect_btn.setObjectName("btn_success")
            self._status_label.setText("状态: 未连接")
            self._status_label.setProperty("role", "err")
        self._connect_btn.style().unpolish(self._connect_btn)
        self._connect_btn.style().polish(self._connect_btn)
        self._status_label.style().unpolish(self._status_label)
        self._status_label.style().polish(self._status_label)

    # ------------------------------------------------------------------
    # 数据收发
    # ------------------------------------------------------------------

    def _on_send(self):
        text = self._send_input.text().strip()
        if not text:
            self._log("⚠ 请输入要发送的数据")
            return

        if self._hex_tx_check.isChecked():
            try:
                clean = text.replace(" ", "").replace("\n", "")
                data = bytes.fromhex(clean)
            except ValueError:
                self._log(f"✗ Hex 格式错误: '{text}'")
                QMessageBox.warning(self, "格式错误", "Hex 数据格式不正确，请输入如: A5 5A 01 02")
                return
        else:
            data = text.encode('ascii')

        if not self._connected:
            self._log("⚠ 未连接设备，数据未发送 (请先点击「连接」)")
            return

        if self._session is not None:
            try:
                self._session.write(data)
                self._log(f"→ 已发送 {len(data)} 字节")
                if self._sim_check.isChecked():
                    QTimer.singleShot(100, lambda: self._simulate_response(data))
            except Exception as e:
                self._log(f"✗ 发送失败: {e}")
        else:
            if self._sim_check.isChecked():
                self._display_data(data, "TX")
                self._tx_count += len(data)
                self._tx_dirty = True
                self.data_sent.emit(data)
                QTimer.singleShot(100, lambda: self._simulate_response(data))
            else:
                if self._serial:
                    try:
                        self._serial.write(data)
                        self._display_data(data, "TX")
                        self._tx_count += len(data)
                        self._tx_dirty = True
                        self.data_sent.emit(data)
                    except Exception as e:
                        self._log(f"✗ 发送失败: {e}")

    def _on_data_sent(self, data: bytes):
        """SessionController 发送数据后触发 — 更新 TX 显示"""
        self._tx_count += len(data)
        self._tx_dirty = True  # 标签随合并冲刷统一刷新，不每包 setText
        self._display_data(data, "TX")
        self.data_sent.emit(data)

    def _on_data_received(self, data: bytes):
        """SessionController 收到数据后触发 — 更新 RX 显示"""
        self._rx_count += len(data)
        self._rx_dirty = True  # 标签随合并冲刷统一刷新，不每包 setText
        self._display_data(data, "RX")
        self.data_received.emit(data)

    def _display_data(self, data: bytes, direction: str):
        """格式化一帧数据为 HTML 并入缓冲（保留 Hex/时间戳/方向 格式逻辑）"""
        ts = time.strftime("%H:%M:%S.") + f"{int(time.time() * 1000) % 1000:03d}"
        prefix = ""
        if self._timestamp_check.isChecked():
            prefix += f"[{ts}] "
        if self._direction_check.isChecked():
            color = ui_color("rx") if direction == "RX" else ui_color("tx")
            prefix += f'<span style="color:{color};font-weight:bold;">{direction}</span> '

        if self._hex_rx_check.isChecked():
            hex_str = " ".join(f"{b:02X}" for b in data)
            mono = TYPOGRAPHY["font_mono"].replace('"', "'")
            text = f'{prefix}<span style="font-family:{mono};">{hex_str}</span>'
        else:
            ascii_str = data.decode('ascii', errors='replace')
            text = f'{prefix}{ascii_str}'

        self._queue_display_html(text)

    def _queue_display_html(self, html: str):
        """HTML 片段入缓冲，由定时器在下一事件循环回合合并冲刷。

        高频 RX 时同一回合内的多个 chunk 合并为一次 append，
        避免每个 chunk 一次 QTextEdit.append 打爆文档/布局。
        """
        self._pending_html.append(html)
        if not self._flush_timer.isActive():
            self._flush_timer.start()

    def _flush_display(self):
        """合并冲刷: 缓冲的 HTML 一次性 append，RX/TX 计数标签统一刷新"""
        if self._pending_html:
            self._display.append("<br />".join(self._pending_html))
            self._pending_html.clear()
        if self._rx_dirty:
            self._rx_label.setText(f"RX: {self._rx_count} 字节")
            self._rx_dirty = False
        if self._tx_dirty:
            self._tx_label.setText(f"TX: {self._tx_count} 字节")
            self._tx_dirty = False

    # ------------------------------------------------------------------
    # 模拟响应
    # ------------------------------------------------------------------

    def _simulate_response(self, request: bytes):
        if len(request) < 4:
            return
        if request[0] == 0xA5 and request[1] == 0x5A:
            cmd = request[3] if len(request) > 3 else 0
            if cmd == 0x07:
                resp = bytes([0xA5, 0x5A, 0x01, 0x07, request[4], request[5], 0x00, 0x3C, 0x00])
                resp += b"STM32G474" + b"\x00" * 23
                resp += (170000000).to_bytes(4, 'little')
                resp += (0x12345678).to_bytes(4, 'little')
                resp += (0x0001).to_bytes(2, 'little')
                resp += b"1.0.0" + b"\x00" * 11
                from ..core.cffi_loader import CRC16
                crc = CRC16.calc(resp)
                resp += crc.to_bytes(2, 'little')
                self._on_data_received(resp)
                self._log("← 收到设备信息响应 (STM32G474, 170MHz, v1.0.0)")
            elif cmd == 0x08:
                resp = bytes([0xA5, 0x5A, 0x01, 0x08, request[4], request[5], 0x00, 0x00, 0x00])
                from ..core.cffi_loader import CRC16
                crc = CRC16.calc(resp)
                resp += crc.to_bytes(2, 'little')
                self._on_data_received(resp)
                self._log("← 参数写入成功 (模拟)")

    # ------------------------------------------------------------------
    # 轮询（仅旧模式使用）
    # ------------------------------------------------------------------

    def _poll_serial(self):
        if not self._serial or not self._connected:
            return
        try:
            n = self._serial.in_waiting
            if n > 0:
                data = self._serial.read(n)
                if data:
                    self._on_data_received(data)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------

    def _refresh_ports(self):
        self._port_combo.clear()
        try:
            import serial.tools.list_ports
            ports = serial.tools.list_ports.comports()
            if ports:
                for p in ports:
                    self._port_combo.addItem(f"{p.device} - {p.description}")
            else:
                self._port_combo.addItem("COM1")
                self._log("未检测到串口设备，已填入默认 COM1")
        except Exception:
            self._port_combo.addItem("COM1")
            self._log("无法枚举串口（pyserial 未安装？），已填入默认 COM1")

    @staticmethod
    def ns800rt_quick_commands():
        """生成带正确 CRC 的 NS800RT 调试黄金帧（供快捷按钮）。

        命令码与固件 debug_monitor 对齐：GET_INFO=0x07、STOP_STREAM=0x06、
        DEVICE_CONTROL=0x0C(payload 01=开机/00=关机)。每帧均含正确 CRC16-Modbus。
        """
        from ..core.cffi_loader import DebugProtocol as _DP

        def hx(b):
            return _DP.build_frame(*b).hex(" ").upper()

        return [
            ("读设备信息", hx((0x07, 1, 0, b""))),
            ("停止采样", hx((0x06, 1, 0, b"\x00"))),
            ("关机", hx((0x0C, 1, 0, b"\x00"))),
            ("开机", hx((0x0C, 1, 0, b"\x01"))),
        ]

    def _send_quick(self, hex_cmd: str):
        self._send_input.setText(hex_cmd)
        self._on_send()

    def _on_hex_display_change(self):
        self._hex_display = self._hex_rx_check.isChecked()

    def _on_sim_toggle(self):
        if self._sim_check.isChecked():
            self._log("已切换到模拟模式 — 无需真实设备")
        else:
            self._log("已切换到真实串口模式 — 需要连接硬件设备")

    def _on_repeat_toggle(self):
        if self._repeat_check.isChecked():
            self._repeat_timer.start(self._repeat_interval.value())
            self._log(f"定时发送已启动，间隔 {self._repeat_interval.value()}ms")
        else:
            self._repeat_timer.stop()
            self._log("定时发送已停止")

    def _clear_display(self):
        self._pending_html.clear()  # 丢弃未冲刷的片段，避免清空后又被刷回
        self._rx_dirty = False
        self._tx_dirty = False
        self._display.clear()
        self._rx_count = 0
        self._tx_count = 0
        self._rx_label.setText("RX: 0 字节")
        self._tx_label.setText("TX: 0 字节")
        self._log("显示已清空")

    def _log(self, msg: str):
        if not hasattr(self, '_display') or self._display is None:
            return
        ts = time.strftime("%H:%M:%S")
        self._queue_display_html(
            f'<span style="color:{ui_color("user")};">[{ts}]</span> '
            f'<span style="color:{ui_color("log_dim")};">{msg}</span>')

