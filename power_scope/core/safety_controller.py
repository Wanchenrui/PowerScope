"""安全参数事务控制器：写入校验、短窗监测、自动回退与安全停机。"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable
from PySide6.QtCore import QObject, Signal
from power_scope.core.event_bus import EventBus, VarUpdatedEvent
from power_scope.debug.elf_parser import decode_value, encode_value, type_size


@dataclass
class AnomalyCriteria:
    limits: dict[str, tuple[float, float]] = field(default_factory=dict)
    fault_vars: set[str] = field(default_factory=set)
    severe_ratio: float = 5.0
    comms_timeout_s: float = 1.0
    window_s: float = 5.0

    @property
    def monitored_vars(self) -> set[str]:
        return set(self.limits) | set(self.fault_vars)


@dataclass
class _ParameterWrite:
    name: str
    channel: object
    value: float
    anchor: float | int | None = None
    written: bool = False


class SafetyController(QObject):
    """管理一组原子参数写入及写入后的短时安全观察窗口。"""

    state_changed = Signal(str)
    event = Signal(str, str)
    IDLE = "IDLE"
    MONITORING = "MONITORING"
    SAFE_STOP = "SAFE_STOP"

    def __init__(self, debug_service, guardrails,
                 criteria: AnomalyCriteria | None = None,
                 clock: Callable[[], float] | None = None, parent=None) -> None:
        super().__init__(parent)
        self._debug = debug_service
        self._guardrails = guardrails
        self.criteria = criteria or AnomalyCriteria()
        self._clock = clock or time.monotonic
        self._state = self.IDLE
        self._busy = False
        self._transaction: list[_ParameterWrite] = []
        self._started_at = 0.0
        self._last_sample_at = 0.0
        self._missing_monitors: set[str] = set()
        self._bus = EventBus.instance()
        self._bus.subscribe("var/updated", self._on_var_updated)

    @property
    def state(self) -> str:
        return self._state

    @property
    def anchors(self) -> dict[str, float | int]:
        return {item.name: item.anchor for item in self._transaction
                if item.anchor is not None}

    def _set_state(self, state: str) -> None:
        if state != self._state:
            self._state = state
            self.state_changed.emit(state)

    def set_stream_channels(self, names) -> set[str]:
        """登记实际流通道；缺少安全监测项时禁止开始调参事务。"""
        available = set(names)
        self._missing_monitors = self.criteria.monitored_vars - available
        if self._missing_monitors:
            missing = ", ".join(sorted(self._missing_monitors))
            self.event.emit("error", f"安全监测变量未进入流: {missing}")
        return set(self._missing_monitors)

    def begin(self, parameters) -> bool:
        """开始原子写入；元素为 (name, channel, value[, anchor])。"""
        if self._state != self.IDLE or self._busy:
            self.event.emit("warning", f"当前状态 {self._state} 不允许写入")
            return False
        if self._missing_monitors:
            missing = ", ".join(sorted(self._missing_monitors))
            self.event.emit("error", f"安全监测未就绪，拒绝写入: {missing}")
            return False
        normalized: list[_ParameterWrite] = []
        for entry in parameters:
            if len(entry) not in (3, 4):
                raise ValueError("参数写入项必须为 (name, channel, value[, anchor])")
            name, channel, value = entry[:3]
            anchor = entry[3] if len(entry) == 4 else self._guardrails.get_last_value(name)
            normalized.append(_ParameterWrite(str(name), channel, value, anchor))
        if not normalized:
            self.event.emit("warning", "没有可写参数")
            return False
        self._transaction = normalized
        self._busy = True
        self._read_anchor(0)
        return True

    def _read_anchor(self, index: int) -> None:
        if index >= len(self._transaction):
            self._write_next(0)
            return
        item = self._transaction[index]
        if item.anchor is not None:
            self._read_anchor(index + 1)
            return
        channel = item.channel
        size = type_size(channel.type_name) or int(channel.size)

        def on_read(response) -> None:
            if response.get("status", 0) != 0:
                self._abort_begin(f"读取 {item.name} 回退锚点失败")
                return
            value = decode_value(bytes(response.get("payload", b""))[:size],
                                 channel.type_name)
            if isinstance(value, (bytes, bytearray)):
                self._abort_begin(f"{item.name} 类型 {channel.type_name} 无法解码")
                return
            item.anchor = value
            self._read_anchor(index + 1)

        try:
            self._debug.read_memory(int(channel.address), size, callback=on_read)
        except Exception as exc:
            self._abort_begin(f"读取 {item.name} 回退锚点异常: {exc}")

    def _write_next(self, index: int) -> None:
        if index >= len(self._transaction):
            self._busy = False
            now = self._clock()
            self._started_at = now
            self._last_sample_at = now
            self._set_state(self.MONITORING)
            self.event.emit("info", f"参数写入已校验，进入 {self.criteria.window_s:g}s 看门狗")
            return
        item = self._transaction[index]
        try:
            data = encode_value(item.value, item.channel.type_name)
        except (TypeError, ValueError, OverflowError) as exc:
            self._rollback([x for x in self._transaction if x.written],
                           self.IDLE, f"{item.name} 编码失败: {exc}")
            return

        def on_verified(ok: bool, _readback: bytes) -> None:
            if not ok:
                # 响应超时/读回失败时当前写入结果不确定，保守恢复其锚点。
                attempted = [x for x in self._transaction if x.written]
                if item not in attempted:
                    attempted.append(item)
                self._rollback(attempted, self.IDLE,
                               f"{item.name} 写入结果不可确认，已回退本组")
                return
            item.written = True
            self._write_next(index + 1)

        try:
            self._debug.write_and_verify(int(item.channel.address), data, len(data),
                                         callback=on_verified)
        except Exception as exc:
            self._rollback([x for x in self._transaction if x.written],
                           self.IDLE, f"{item.name} 写入异常: {exc}")

    def _abort_begin(self, message: str) -> None:
        self._busy = False
        self._transaction = []
        self.event.emit("error", message)

    def confirm(self) -> bool:
        if self._state != self.MONITORING or self._busy:
            return False
        self._commit("用户确认参数")
        return True

    def revert(self) -> bool:
        if self._state != self.MONITORING or self._busy:
            return False
        self._rollback(list(self._transaction), self.IDLE, "用户请求回退参数")
        return True

    def clear_safe_stop(self) -> bool:
        if self._state != self.SAFE_STOP or self._busy:
            return False
        self._transaction = []
        self._set_state(self.IDLE)
        self.event.emit("info", "安全停机锁定已解除；设备保持停机")
        return True

    def on_tick(self) -> None:
        if self._state != self.MONITORING or self._busy:
            return
        now = self._clock()
        if now - self._started_at >= self.criteria.window_s:
            self._commit("看门狗窗口通过，参数已提交")
            return
        if (self.criteria.monitored_vars and
                now - self._last_sample_at > self.criteria.comms_timeout_s):
            self._severe("监测数据通信超时")

    def _on_var_updated(self, update: VarUpdatedEvent) -> None:
        if self._state != self.MONITORING or self._busy:
            return
        name = update.name
        if name not in self.criteria.monitored_vars:
            return
        self._last_sample_at = self._clock()
        value = float(update.phys_value)
        if name in self.criteria.fault_vars and value != 0.0:
            self._severe(f"故障变量 {name}={value:g}")
            return
        bounds = self.criteria.limits.get(name)
        if bounds is None:
            return
        low, high = bounds
        if low <= value <= high:
            return
        width = max(abs(high - low), 1e-12)
        severe = (value < low - width * self.criteria.severe_ratio or
                  value > high + width * self.criteria.severe_ratio)
        if severe:
            self._severe(f"{name}={value:g} 严重越界 [{low:g}, {high:g}]")
        else:
            self._rollback(list(self._transaction), self.IDLE,
                           f"{name}={value:g} 越界，已自动回退参数")

    def _severe(self, reason: str) -> None:
        if self._state != self.MONITORING or self._busy:
            return
        # UART 按发送顺序处理：先发停机，再发回退。不能等待 ACK 后才回退，
        # 否则停机响应丢失会把事务永久卡在 MONITORING。
        try:
            self._debug.device_control(False)
        except Exception:
            pass
        self._rollback(list(self._transaction), self.SAFE_STOP,
                       f"{reason}；设备已停机并回退参数")
    def _rollback(self, items, target_state: str, message: str) -> None:
        self._busy = True
        rollback_items = [item for item in items if item.anchor is not None]

        def write_at(index: int, failures: list[str]) -> None:
            if index >= len(rollback_items):
                self._busy = False
                final_state = target_state
                if failures and target_state != self.SAFE_STOP:
                    # 参数状态已不可确认：升级为安全停机，禁止继续写入。
                    try:
                        self._debug.device_control(False)
                    except Exception:
                        pass
                    final_state = self.SAFE_STOP
                self._set_state(final_state)
                if final_state == self.IDLE:
                    self._transaction = []
                level = "error" if failures or final_state == self.SAFE_STOP else "warning"
                suffix = f"；回退校验失败: {', '.join(failures)}" if failures else ""
                self.event.emit(level, message + suffix)
                return
            item = rollback_items[index]
            try:
                data = encode_value(item.anchor, item.channel.type_name)
            except (TypeError, ValueError, OverflowError):
                failures.append(item.name)
                write_at(index + 1, failures)
                return

            def on_verified(ok: bool, _readback: bytes) -> None:
                if not ok:
                    failures.append(item.name)
                write_at(index + 1, failures)
            try:
                self._debug.write_and_verify(int(item.channel.address), data, len(data),
                                             callback=on_verified)
            except Exception:
                failures.append(item.name)
                write_at(index + 1, failures)
        write_at(0, [])

    def _commit(self, message: str) -> None:
        for item in self._transaction:
            self._guardrails.record(item.name, float(item.value))
        self._transaction = []
        self._set_state(self.IDLE)
        self.event.emit("info", message)

    def close(self) -> None:
        self._bus.unsubscribe("var/updated", self._on_var_updated)






