"""测试 EventBus — 轻量 Pub/Sub 事件总线

TDD 流程:
  1. RED: 测试先写，运行应失败（EventBus 未实现）
  2. GREEN: 实现最小代码让测试通过
  3. REFACTOR: 清理，确保类型安全
"""
from __future__ import annotations

import pytest
from PySide6.QtCore import QCoreApplication, Qt

from power_scope.core.event_bus import EventBus, FrameReceivedEvent, VarUpdatedEvent


# 确保 QCoreApplication 存在（测试需要事件循环）
@pytest.fixture(scope="module", autouse=True)
def _ensure_qapp():
    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication([])
    yield app


class TestEventBus:
    """EventBus 单元测试"""

    def _pump(self, count: int = 3) -> None:
        """处理 Qt 事件循环，让 QueuedConnection 信号送达"""
        app = QCoreApplication.instance()
        for _ in range(count):
            app.processEvents()

    def test_singleton(self):
        """EventBus 应为单例，多次获取返回同一实例"""
        bus1 = EventBus.instance()
        bus2 = EventBus.instance()
        assert bus1 is bus2

    def test_subscribe_and_publish(self):
        """订阅后发布，接收者应收到数据"""
        bus = EventBus.instance()
        bus._reset_for_test()
        received: list = []

        def handler(data):
            received.append(data)

        bus.subscribe("test/topic", handler)
        bus.publish("test/topic", {"value": 42})
        self._pump()

        assert len(received) == 1
        assert received[0] == {"value": 42}

    def test_unsubscribe(self):
        """取消订阅后不应再收到数据"""
        bus = EventBus.instance()
        bus._reset_for_test()
        received: list = []

        def handler(data):
            received.append(data)

        bus.subscribe("test/topic", handler)
        bus.unsubscribe("test/topic", handler)
        bus.publish("test/topic", {"value": 99})
        self._pump()

        assert len(received) == 0

    def test_multiple_subscribers(self):
        """同一 topic 多个订阅者应各自收到"""
        bus = EventBus.instance()
        bus._reset_for_test()
        received_a: list = []
        received_b: list = []

        bus.subscribe("multi", lambda d: received_a.append(d))
        bus.subscribe("multi", lambda d: received_b.append(d))

        bus.publish("multi", "hello")
        self._pump()

        assert len(received_a) == 1
        assert len(received_b) == 1
        assert received_a[0] == "hello"
        assert received_b[0] == "hello"

    def test_no_subscribers_no_crash(self):
        """无订阅者的 topic 发布不应崩溃"""
        bus = EventBus.instance()
        bus._reset_for_test()
        # 不应抛异常
        bus.publish("nobody/listening", "orphan")
        self._pump()
        assert True  # 如果到了这里没抛异常就成功

    def test_typed_events(self):
        """类型化事件：帧接收事件应包含正确字段"""
        bus = EventBus.instance()
        bus._reset_for_test()
        received: list = []

        def handler(event: FrameReceivedEvent):
            received.append(event)

        bus.subscribe("frame/received", handler)

        event = FrameReceivedEvent(
            protocol="debug",
            cmd=0x07,
            seq=1,
            payload=b"\x01\x02\x03",
            raw_frame=b"\xA5\x5A\x01\x07\x00\x01\x01\x02\x03\x00\x00",
        )
        bus.publish("frame/received", event)
        self._pump()

        assert len(received) == 1
        ev = received[0]
        assert ev.protocol == "debug"
        assert ev.cmd == 0x07
        assert ev.payload == b"\x01\x02\x03"

    def test_var_updated_event(self):
        """变量更新事件应包含变量名和物理值"""
        bus = EventBus.instance()
        bus._reset_for_test()
        received: list = []

        def handler(event: VarUpdatedEvent):
            received.append(event)

        bus.subscribe("var/updated", handler)

        event = VarUpdatedEvent(
            name="Vdc_bus",
            raw_value=0x1234,
            phys_value=380.5,
            unit="V",
            timestamp=1.0,
        )
        bus.publish("var/updated", event)
        self._pump()

        assert len(received) == 1
        ev = received[0]
        assert ev.name == "Vdc_bus"
        assert ev.phys_value == 380.5
        assert ev.unit == "V"

    def test_isolated_instance_for_test(self):
        """测试隔离：每个测试前应获得干净实例"""
        bus = EventBus.instance()
        bus._reset_for_test()
        # 确认内部状态为空
        assert len(bus._subscribers) == 0

    def test_subscribe_same_handler_twice(self):
        """同一 handler 订阅两次应只生效一次"""
        bus = EventBus.instance()
        bus._reset_for_test()
        received: list = []

        def handler(data):
            received.append(data)

        bus.subscribe("dup", handler)
        bus.subscribe("dup", handler)
        bus.publish("dup", "once")
        self._pump()

        assert len(received) == 1  # 不应触发两次
