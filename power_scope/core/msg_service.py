"""B017 MSG protocol support and low-rate dashboard polling.

MSG words are transmitted big-endian.  A normal frame contains
``start, command, data_word_count, data...``; ACK/NACK frames contain only
``start, command``.  The firmware's inquiry commands use zero-filled data
words to declare the expected response length.
"""
from __future__ import annotations

import struct
import time
from collections import defaultdict, deque
from dataclasses import dataclass

from PySide6.QtCore import QCoreApplication, QObject, QTimer, Signal


FRAME_START = 0xEFEF
FRAME_ACK = 0xDFDF
FRAME_NACK = 0xCFCF
MAX_DATA_WORDS = 32


@dataclass(frozen=True)
class MsgCommandSpec:
    command: int
    label: str
    direction: str
    data_words: int | None


# The firmware command table carries IDs and callbacks, but no payload length.
# Lengths below are therefore limited to commands whose layouts are defined by
# the current single-MCU adapter.  Unknown ELF-discovered commands stay manual.
KNOWN_MSG_COMMANDS = {
    0x2001: MsgCommandSpec(0x2001, "开关机指令", "write", 1),
    0x2002: MsgCommandSpec(0x2002, "运行模式", "write", 1),
    0x2101: MsgCommandSpec(0x2101, "读取开关机指令", "read", 1),
    0x2102: MsgCommandSpec(0x2102, "读取运行模式", "read", 1),
    0x2108: MsgCommandSpec(0x2108, "电网电压", "read", 1),
    0x2109: MsgCommandSpec(0x2109, "电网频率", "read", 1),
    0x210A: MsgCommandSpec(0x210A, "功率因数", "read", 1),
    0x210B: MsgCommandSpec(0x210B, "电网电流", "read", 1),
    0x210C: MsgCommandSpec(0x210C, "有功功率", "read", 4),
    0x210D: MsgCommandSpec(0x210D, "无功功率", "read", 2),
    0x211E: MsgCommandSpec(0x211E, "PV 输入", "read", 3),
    0x2128: MsgCommandSpec(0x2128, "逆变器状态", "read", 1),
    0x2130: MsgCommandSpec(0x2130, "告警组 1", "read", 5),
    0x2131: MsgCommandSpec(0x2131, "告警组 2", "read", 5),
    0x2135: MsgCommandSpec(0x2135, "主/子状态机", "read", 2),
}


@dataclass(frozen=True)
class MsgFrame:
    start: int
    command: int
    words: tuple[int, ...]
    raw: bytes

    @property
    def kind(self) -> str:
        if self.start == FRAME_ACK:
            return "ack"
        if self.start == FRAME_NACK:
            return "nack"
        return "data"


def build_msg_frame(command: int, words=()) -> bytes:
    """Build a normal MSG frame from a command and 16-bit words."""
    command = int(command)
    normalized = tuple(int(word) for word in words)
    if not 0 <= command <= 0xFFFF:
        raise ValueError("MSG 命令字必须在 0x0000..0xFFFF")
    if len(normalized) > MAX_DATA_WORDS:
        raise ValueError(f"MSG 数据字数不能超过 {MAX_DATA_WORDS}")
    if any(word < 0 or word > 0xFFFF for word in normalized):
        raise ValueError("MSG 数据必须是 16 位无符号字")
    return struct.pack(">HHH", FRAME_START, command, len(normalized)) + b"".join(
        struct.pack(">H", word) for word in normalized)


class MsgStreamParser:
    """Extract MSG frames from a mixed debug/MSG byte stream."""

    _START_BYTES = (b"\xEF\xEF", b"\xDF\xDF", b"\xCF\xCF")

    def __init__(self, max_buffer: int = 8192):
        self._buffer = bytearray()
        self._max_buffer = max_buffer

    def reset(self):
        self._buffer.clear()

    def feed(self, data: bytes, accepted_commands=None) -> list[MsgFrame]:
        if data:
            self._buffer.extend(data)
        if len(self._buffer) > self._max_buffer:
            self._buffer = self._buffer[-self._max_buffer:]

        frames = []
        while True:
            start_index = self._find_start()
            if start_index < 0:
                self._buffer = self._buffer[-1:]
                break
            if start_index:
                del self._buffer[:start_index]
            if len(self._buffer) < 4:
                break

            start, command = struct.unpack_from(">HH", self._buffer)
            if accepted_commands is not None and command not in accepted_commands:
                # Debug frames share this byte stream.  Reject a coincidental
                # EF/DF/CF marker unless its command is one we are waiting for.
                del self._buffer[0]
                continue
            if start in (FRAME_ACK, FRAME_NACK):
                raw = bytes(self._buffer[:4])
                del self._buffer[:4]
                frames.append(MsgFrame(start, command, (), raw))
                continue

            if len(self._buffer) < 6:
                break
            word_count = struct.unpack_from(">H", self._buffer, 4)[0]
            if word_count > MAX_DATA_WORDS:
                del self._buffer[0]
                continue
            frame_size = 6 + word_count * 2
            if len(self._buffer) < frame_size:
                break
            raw = bytes(self._buffer[:frame_size])
            del self._buffer[:frame_size]
            words = struct.unpack_from(f">{word_count}H", raw, 6) if word_count else ()
            frames.append(MsgFrame(start, command, tuple(words), raw))
        return frames

    def _find_start(self) -> int:
        indices = [self._buffer.find(marker) for marker in self._START_BYTES]
        valid = [index for index in indices if index >= 0]
        return min(valid) if valid else -1


@dataclass
class _PendingRequest:
    callback: object
    started: float
    deadline: float


class MsgService(QObject):
    """MSG request/response service sharing the application's serial session."""

    frame_received = Signal(object)

    def __init__(self, session=None, writer=None, parent=None,
                 timeout_s: float = 1.0, clock=None):
        super().__init__(parent)
        self._session = session
        self._writer = writer or (session.write if session is not None else None)
        self._parser = MsgStreamParser()
        self._pending = defaultdict(deque)
        self._timeout_s = max(0.05, float(timeout_s))
        self._clock = clock or time.monotonic
        self._latencies_ms = deque(maxlen=4096)
        self._response_count = 0
        self._timeout_count = 0
        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self.expire_pending)
        if session is not None and hasattr(session, "data_received"):
            session.data_received.connect(self.feed)

    def request_read(self, command: int, response_words: int, callback=None) -> bytes:
        count = int(response_words)
        if not 0 <= count <= MAX_DATA_WORDS:
            raise ValueError(f"MSG 返回字数必须在 0..{MAX_DATA_WORDS}")
        return self._send_request(command, (0,) * count, callback)

    def request_write(self, command: int, words, callback=None) -> bytes:
        return self._send_request(command, tuple(words), callback)

    def _send_request(self, command: int, words, callback) -> bytes:
        if self._writer is None:
            raise RuntimeError("MSG 服务没有可用的串口发送通道")
        frame = build_msg_frame(command, words)
        pending = None
        if callback is not None:
            started = self._clock()
            pending = _PendingRequest(
                callback, started, started + self._timeout_s)
            self._pending[int(command)].append(pending)
            if not self._timer.isActive() and QCoreApplication.instance() is not None:
                self._timer.start()
        try:
            self._writer(frame)
        except Exception:
            if pending is not None:
                queue = self._pending[int(command)]
                try:
                    queue.remove(pending)
                except ValueError:
                    pass
            raise
        return frame

    def feed(self, data: bytes):
        from .event_bus import EventBus

        accepted_commands = set(self._pending)
        for frame in self._parser.feed(data, accepted_commands):
            self.frame_received.emit(frame)
            EventBus.instance().publish("msg/frame", frame)
            queue = self._pending.get(frame.command)
            if not queue:
                continue
            pending = queue.popleft()
            if not queue:
                self._pending.pop(frame.command, None)
            self._record_latency((self._clock() - pending.started) * 1000.0)
            pending.callback({
                "cmd": frame.command,
                "ok": frame.kind != "nack",
                "kind": frame.kind,
                "words": frame.words,
                "raw": frame.raw,
            })
        if not self._pending:
            self._timer.stop()

    def expire_pending(self):
        now = self._clock()
        expired = []
        for command, queue in list(self._pending.items()):
            while queue and queue[0].deadline <= now:
                expired.append((command, queue.popleft()))
            if not queue:
                self._pending.pop(command, None)
        for command, pending in expired:
            self._timeout_count += 1
            pending.callback({
                "cmd": command, "ok": False, "kind": "timeout",
                "words": (), "raw": b"",
            })
        if not self._pending:
            self._timer.stop()

    def _record_latency(self, latency_ms: float):
        from .event_bus import EventBus

        self._latencies_ms.append(max(0.0, float(latency_ms)))
        self._response_count += 1
        EventBus.instance().publish("msg/latency", self.latency_stats())

    @staticmethod
    def _percentile(sorted_values, percentile: float) -> float:
        if not sorted_values:
            return 0.0
        index = max(0, min(len(sorted_values) - 1,
                           int((percentile * len(sorted_values) + 0.999999)) - 1))
        return float(sorted_values[index])

    def latency_stats(self) -> dict:
        values = sorted(self._latencies_ms)
        count = len(values)
        return {
            "sample_count": count,
            "response_count": self._response_count,
            "timeout_count": self._timeout_count,
            "min_ms": float(values[0]) if values else 0.0,
            "mean_ms": (sum(values) / count) if count else 0.0,
            "p50_ms": self._percentile(values, 0.50),
            "p95_ms": self._percentile(values, 0.95),
            "p99_ms": self._percentile(values, 0.99),
            "max_ms": float(values[-1]) if values else 0.0,
        }

    def reset_latency_stats(self):
        self._latencies_ms.clear()
        self._response_count = 0
        self._timeout_count = 0

    def clear_pending(self):
        pending = [
            (command, item)
            for command, queue in self._pending.items()
            for item in queue
        ]
        self._pending.clear()
        self._parser.reset()
        self._timer.stop()
        for command, item in pending:
            item.callback({
                "cmd": command, "ok": False, "kind": "cancelled",
                "words": (), "raw": b"",
            })


def _signed16(value: int) -> int:
    return value - 0x10000 if value & 0x8000 else value


def _signed32(high: int, low: int) -> int:
    value = (high << 16) | low
    return value - 0x100000000 if value & 0x80000000 else value


class MsgTelemetryPoller(QObject):
    """Poll the business protocol and publish dashboard ``var/updated`` events."""

    POLL_COMMANDS = (
        0x211E, 0x2108, 0x210B, 0x2109, 0x210C, 0x210D, 0x210A,
        0x2135, 0x2102, 0x2101, 0x2130, 0x2131,
    )

    def __init__(self, service: MsgService, parent=None, interval_ms: int = 80):
        super().__init__(parent)
        self._service = service
        self._timer = QTimer(self)
        self._timer.setInterval(max(20, int(interval_ms)))
        self._timer.timeout.connect(self._poll_next)
        self._index = 0
        self._waiting = False
        self._values = {}

    @property
    def is_running(self) -> bool:
        return self._timer.isActive()

    def start(self):
        if self._timer.isActive():
            return
        self._index = 0
        self._waiting = False
        self._timer.start()
        self._poll_next()

    def stop(self):
        self._timer.stop()
        self._waiting = False

    def _poll_next(self):
        if self._waiting:
            return
        command = self.POLL_COMMANDS[self._index]
        spec = KNOWN_MSG_COMMANDS[command]
        self._waiting = True
        try:
            self._service.request_read(
                command, spec.data_words,
                callback=lambda response, cmd=command: self._on_response(cmd, response))
        except Exception:
            self._waiting = False
            self._advance()

    def _on_response(self, command: int, response: dict):
        self._waiting = False
        if response.get("ok") and response.get("kind") == "data":
            words = tuple(response.get("words", ()))
            expected = KNOWN_MSG_COMMANDS[command].data_words
            if len(words) == expected:
                self._decode(command, words)
        self._advance()

    def _advance(self):
        self._index = (self._index + 1) % len(self.POLL_COMMANDS)

    def _publish(self, name: str, value, unit: str = ""):
        from .event_bus import EventBus, VarUpdatedEvent

        self._values[name] = value
        EventBus.instance().publish("var/updated", VarUpdatedEvent(
            name=name,
            raw_value=value,
            phys_value=value,
            unit=unit,
            timestamp=time.time(),
            source="msg",
        ))

    def _decode(self, command: int, words: tuple[int, ...]):
        if command == 0x211E:
            self._publish("pv_voltage", _signed16(words[0]) / 100.0, "V")
            self._publish("pv_current_a", _signed16(words[1]) / 100.0, "A")
            self._publish("pv_current_b", _signed16(words[2]) / 100.0, "A")
        elif command == 0x2108:
            self._publish("grid_voltage", words[0] / 10.0, "V")
        elif command == 0x210B:
            self._publish("grid_current", _signed16(words[0]) / 100.0, "A")
        elif command == 0x2109:
            self._publish("grid_frequency", words[0] / 1000.0, "Hz")
        elif command == 0x210C:
            self._publish("active_power", _signed32(words[0], words[1]), "W")
        elif command == 0x210D:
            self._publish("reactive_power", _signed32(words[0], words[1]), "var")
        elif command == 0x210A:
            self._publish("power_factor", _signed16(words[0]) / 1000.0)
        elif command == 0x2135:
            self._publish("fsm_main_state", words[0])
            self._publish("fsm_sub_state", words[1])
        elif command == 0x2102:
            self._publish("run_mode", words[0])
        elif command == 0x2101:
            self._publish("command_state", words[0])
        elif command == 0x2130:
            for index, value in enumerate(words):
                self._publish(f"alarm_group_{index}", value)
        elif command == 0x2131:
            for index, value in enumerate(words, 5):
                self._publish(f"alarm_group_{index}", value)
        self._publish_inverter_state()

    def _publish_inverter_state(self):
        main = self._values.get("fsm_main_state")
        mode = self._values.get("run_mode")
        command = self._values.get("command_state")
        alarm_active = any(
            self._values.get(f"alarm_group_{index}", 0)
            for index in range(10)
        )
        if main == 3:
            state = {0: 1, 1: 4, 2: 5}.get(mode, 0)
        elif main == 4 and alarm_active:
            state = 3
        elif command == 0:
            state = 2
        else:
            state = 0
        self._publish("inverter_state", state)
