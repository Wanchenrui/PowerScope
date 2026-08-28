"""EventBus — 轻量 Pub/Sub 事件总线

基于 PySide6 Signal 实现，确保线程安全。
所有跨模块通信通过事件总线进行，避免直接耦合。
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable, Any
from PySide6.QtCore import QObject, Signal, Qt


@dataclass
class FrameReceivedEvent:
    """调试协议帧接收事件"""
    protocol: str               # "debug" | "modbus" | "custom"
    cmd: int                    # 命令码
    seq: int                    # 序列号
    payload: bytes              # 载荷数据
    raw_frame: bytes            # 完整原始帧（含头+CRC）
    status: int = 0             # 响应状态（仅响应帧有效）
    timestamp: float = 0.0    # 接收时间戳


@dataclass
class VarUpdatedEvent:
    """变量更新事件 — 从 MCU 读取到的新值"""
    name: str                   # 变量名（如 Vdc_bus）
    raw_value: int | float      # 原始寄存器/内存值
    phys_value: float           # 物理量（经 scale + offset 转换）
    unit: str                   # 单位（如 V, A, Hz）
    timestamp: float            # 时间戳（秒，相对或绝对）
    source: str = "device"      # 数据来源：device / mock / user


@dataclass
class ParamWrittenEvent:
    """参数写入事件 — 用户或自动调参写入 MCU 的参数"""
    param_name: str             # 参数名（如 Kp_id, Ki_v）
    raw_value: float            # 写入的原始值
    phys_value: float | None = None  # 物理值（可选）
    source: str = "user"        # user / tuning_engine / llm


@dataclass
class ElfLoadedEvent:
    """ELF 加载完成事件 — 携带解析出的全局变量列表"""
    path: str
    variables: list


@dataclass
class ConnectionStateEvent:
    """连接状态变更事件"""
    state: str                  # "disconnected" | "connecting" | "connected" | "error"
    transport_type: str         # "serial" | "mock" | "tcp"
    info: str = ""              # 附加信息（如端口名、错误详情）


class _EventBusCore(QObject):
    """内部 QObject，持有 Signal"""
    _publish_signal = Signal(str, object)  # (topic, payload) — 保留兼容
    _flush_signal = Signal()               # 触发积压事件批量分发


class EventBus(QObject):
    """轻量事件总线 — 单例

    使用方式:
        bus = EventBus.instance()
        bus.subscribe("frame/received", on_frame)
        bus.publish("frame/received", FrameReceivedEvent(...))
    """
    _instance: EventBus | None = None

    def __init__(self) -> None:
        if EventBus._instance is not None:
            raise RuntimeError("Use EventBus.instance() to get the singleton")
        super().__init__()
        self._core = _EventBusCore()
        self._subscribers: dict[str, list[Callable[[Any], None]]] = {}
        self._core._publish_signal.connect(self._on_publish, type=Qt.QueuedConnection)
        self._core._flush_signal.connect(self._on_flush, type=Qt.QueuedConnection)
        # 合并冲刷队列：高频 topic（如流式 var/updated，可达数千条/秒）
        # 先入队，主线程按批分发，避免 Qt 事件队列被逐条信号打满。
        self._lock = threading.Lock()
        self._pending: list[tuple[str, Any]] = []
        self._flush_scheduled = False

    @classmethod
    def instance(cls) -> EventBus:
        """获取 EventBus 单例 — 异常安全的延迟初始化

        使用 cls.__new__ 分离实例创建与初始化，
        确保 __init__ 抛出异常时不会缓存半初始化对象。
        """
        if cls._instance is None:
            inst = cls.__new__(cls)
            try:
                inst.__init__()
                cls._instance = inst
            except Exception:
                # 初始化失败，不缓存不完整的实例
                # 下次调用 instance() 会重新尝试
                raise RuntimeError(
                    "EventBus 初始化失败，请确保 QApplication 已创建"
                ) from None
        return cls._instance

    def _on_publish(self, topic: str, payload: object) -> None:
        """Signal 槽 — 在主线程分发到所有订阅者"""
        self._dispatch(topic, payload)

    def _dispatch(self, topic: str, payload: object) -> None:
        handlers = self._subscribers.get(topic, [])
        for handler in list(handlers):
            try:
                handler(payload)
            except Exception:
                # 订阅者异常不应影响其他订阅者
                # 生产环境应记录日志
                pass

    def _on_flush(self) -> None:
        """主线程批量分发积压事件（保持 FIFO 顺序）。"""
        with self._lock:
            batch = self._pending
            self._pending = []
            self._flush_scheduled = False
        for topic, payload in batch:
            self._dispatch(topic, payload)

    def subscribe(self, topic: str, handler: Callable[[Any], None]) -> None:
        """订阅主题"""
        if topic not in self._subscribers:
            self._subscribers[topic] = []
        # 避免同一 handler 重复订阅
        if handler not in self._subscribers[topic]:
            self._subscribers[topic].append(handler)

    def unsubscribe(self, topic: str, handler: Callable[[Any], None]) -> None:
        """取消订阅"""
        if topic in self._subscribers and handler in self._subscribers[topic]:
            self._subscribers[topic].remove(handler)

    def publish(self, topic: str, payload: object) -> None:
        """发布事件（线程安全）。

        事件先入合并队列，并保证至多一个 queued flush 信号在途；
        主线程收到 flush 后按 FIFO 批量分发。订阅者 API 不变。
        """
        with self._lock:
            self._pending.append((topic, payload))
            if not self._flush_scheduled:
                self._flush_scheduled = True
                self._core._flush_signal.emit()

    # --- 测试辅助 ---

    def _reset_for_test(self) -> None:
        """测试隔离：清空所有订阅者并排空事件队列"""
        self._subscribers.clear()
        with self._lock:
            self._pending = []
            self._flush_scheduled = False
        # 排空 Qt 事件队列中可能积压的 publish 信号
        from PySide6.QtCore import QCoreApplication
        app = QCoreApplication.instance()
        if app is not None:
            for _ in range(5):
                app.processEvents()
