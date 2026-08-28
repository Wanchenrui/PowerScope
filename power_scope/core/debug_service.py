"""debug_service.py — 调试会话服务层 (协议事务 + 流解码)

这是连接「协议帧」与「UI 数值」之间缺失的一环。职责：

  • 发起命令：READ_MEM / READ_BATCH / WRITE_MEM / GET_INFO / RESET / SET_SAMPLE / START/STOP_STREAM
  • 按 seq 匹配请求与响应（解决“假读/假写”）
  • 解码 MCU 的 STREAM_DATA 流帧 → 按采样列表布局拆成各变量 →
    publish("var/updated")（解决“波形画固定值/不是按地址读”的根因）

帧定界说明
----------
PC 端从 SessionController.data_received 收到的是连续字节流，需自定界。本服务支持两类入站帧：

  • 响应帧 (9 字节头): SOF(2)+VER(1)+CMD(1)+SEQ(2)+STATUS(1)+LEN(2)+PAYLOAD+CRC(2)
        —— 有显式 LEN，自定界。
  • 流式帧 (12 字节头, cmd=0x10): SOF(2)+VER(1)+CMD(1)+SEQ(2)+TS(4)+LIST(1)+CNT(1)+DATA+CRC(2)
        —— **无显式 LEN**。长度 = 已注册采样列表布局的总字节数 × sample_count。
        因此必须先 register_sample_layout / setup_sample_list 才能解码对应 list 的流。

> 注：流式帧缺 LEN 字段是协议层设计缺陷（见分析文档 §4）。在固件加入 LEN 字段前，
>     这里用“布局感知定界”作为等效且无需改动固件的方案。
"""
from __future__ import annotations

import struct
import time
from dataclasses import dataclass

from PySide6.QtCore import QObject, QCoreApplication, QTimer

from .event_bus import EventBus, VarUpdatedEvent
from .cffi_loader import CRC16, DebugProtocol
from .wave_codec import CODEC_NAMES, bits_per_sample, decode_channel
from ..debug.elf_parser import decode_value, resolve_symbol_path


@dataclass
class SampleChannel:
    """采样通道 — 一个被周期性采集并上报的变量"""
    name: str
    address: int
    size: int
    type_name: str = "uint32_t"
    scale: float = 1.0
    offset: float = 0.0
    unit: str = ""
    sequence_address: int = 0


@dataclass(frozen=True)
class WaveStatus:
    state: int
    tap_id: int
    mode: int
    channel_count: int
    capture_id: int
    captured_points: int
    total_points: int
    row_bytes: int
    period_us: int
    buffer_high_water: int
    overflow_count: int
    compression_status: int
    pretrigger_points: int = 0
    posttrigger_points: int = 0
    tx_high_water: int = 0
    tx_low_water: int = 0
    tx_high_overflow: int = 0
    tx_low_overflow: int = 0
    atomic_retries: int = 0
    atomic_failures: int = 0
    non_atomic_mask: int = 0
    capture_isr_max_cycles: int = 0
    live_raw_bytes: int = 0
    live_encoded_bytes: int = 0


@dataclass(frozen=True)
class WaveDataBlock:
    capture_id: int
    block_seq: int
    offset: int
    first_sample_id: int
    sample_count: int
    encoding: int
    tap_id: int
    data: bytes


@dataclass
class DebugStats:
    """调试链路统计 — 供状态条实时展示"""
    bytes_received: int = 0
    frames_ok: int = 0
    crc_errors: int = 0
    responses: int = 0
    stream_frames: int = 0
    var_updates: int = 0
    request_timeouts: int = 0
    wave_blocks: int = 0
    wave_decode_errors: int = 0
    wave_gap_samples: int = 0
    wave_raw_bytes: int = 0
    wave_encoded_bytes: int = 0


@dataclass
class _PendingRequest:
    callback: callable
    deadline: float


# 采样列表条目在线序中的字节宽度: addr(4) + size(1) + reserved(1)。
# MCU 与 PC 均按显式 6 字节序列化，不依赖 C 结构体填充。
_SAMPLE_ITEM_FMT = "<IBB"
_WAVE_EXT_HEADER_FMT = "<IIHBB"
_WAVE_LIVE_CHANNEL_FMT = "<BBBBH"

WAVE_MODE_RECORDER = 0
WAVE_MODE_TRIGGERED = 1
WAVE_MODE_LIVE = 2

WAVE_STATE_IDLE = 0
WAVE_STATE_CONFIGURED = 1
WAVE_STATE_CAPTURING = 2
WAVE_STATE_FROZEN = 3
WAVE_STATE_UPLOADING = 4
WAVE_STATE_COMPLETE = 5
WAVE_STATE_ARMED = 6
WAVE_STATE_LIVE = 7

WAVE_ENCODING_RAW_INTERLEAVED = 0
WAVE_ENCODING_LIVE_CHANNEL = 1

WAVE_BUFFER_BYTES = 128 * 1024

WAVE_TYPE_RAW_BITS = 0
WAVE_TYPE_S8 = 1
WAVE_TYPE_U8 = 2
WAVE_TYPE_S16 = 3
WAVE_TYPE_U16 = 4
WAVE_TYPE_S32 = 5
WAVE_TYPE_U32 = 6
WAVE_TYPE_F32 = 7
WAVE_TYPE_S64 = 8
WAVE_TYPE_U64 = 9
WAVE_TYPE_F64 = 10
WAVE_TYPE_BOOL = 11
WAVE_TYPE_ENUM = 12
WAVE_TYPE_POINTER = 13


def wave_type_code(type_name: str, size: int) -> int:
    """把 DWARF/C 标量类型归一成 MCU 录波描述符类型码。"""
    name = " ".join((type_name or "").replace("const", " ").split()).lower()
    exact = {
        "int8_t": WAVE_TYPE_S8, "signed char": WAVE_TYPE_S8, "char": WAVE_TYPE_S8,
        "uint8_t": WAVE_TYPE_U8, "unsigned char": WAVE_TYPE_U8,
        "int16_t": WAVE_TYPE_S16, "short": WAVE_TYPE_S16,
        "short int": WAVE_TYPE_S16,
        "uint16_t": WAVE_TYPE_U16, "unsigned short": WAVE_TYPE_U16,
        "short unsigned int": WAVE_TYPE_U16,
        "int32_t": WAVE_TYPE_S32, "int": WAVE_TYPE_S32,
        "long int": WAVE_TYPE_S32,
        "uint32_t": WAVE_TYPE_U32, "unsigned int": WAVE_TYPE_U32,
        "long unsigned int": WAVE_TYPE_U32,
        "float": WAVE_TYPE_F32,
        "int64_t": WAVE_TYPE_S64, "long long int": WAVE_TYPE_S64,
        "uint64_t": WAVE_TYPE_U64, "long long unsigned int": WAVE_TYPE_U64,
        "double": WAVE_TYPE_F64,
        "_bool": WAVE_TYPE_BOOL, "bool": WAVE_TYPE_BOOL,
        "pointer": WAVE_TYPE_POINTER,
    }
    if name in exact:
        return exact[name]
    if name.startswith("enum "):
        return WAVE_TYPE_ENUM
    if "*" in name and int(size) == 4:
        return WAVE_TYPE_POINTER
    return WAVE_TYPE_RAW_BITS

SOF0 = 0xA5
SOF1 = 0x5A

# 防止流数据中的伪 SOF + 畸形长度让解析器长期等待不存在的大帧。
_MAX_FRAME_BYTES = 4096


def build_sample_channels(profile, symbol_lookup, names=None):
    """从设备 profile 的变量绑定 + ELF 符号表构造 SampleChannel 列表。

    把“工具内变量名 → elf_symbol → 真实地址/大小/类型”这条解析链集中在一处，
    供 MainWindow 在连接后下发采样列表使用。

    Args:
        profile: DeviceProfile，使用其 ``variables`` (VarBinding)。
        symbol_lookup: dict[str, sym] 或 callable(symbol_name)->sym|None；
            sym 需具备 ``address`` / ``size`` / ``type_name`` 属性 (如 ElfVariable)。
        names: 限定的工具内变量名集合。None 时取所有 ``update_rate > 0`` 的变量；
            指定时按名筛选并忽略 update_rate（显式选择优先）。

    Returns:
        list[SampleChannel]，跳过无法在符号表中解析的变量。
    """
    channels: list[SampleChannel] = []
    for var in profile.variables:
        if names is not None:
            if var.name not in names:
                continue
        elif getattr(var, "update_rate", 0) == 0:
            continue
        sym = resolve_symbol_path(symbol_lookup, var.elf_symbol)
        if sym is None:
            continue
        type_name = getattr(sym, "type_name", "") or "uint32_t"
        channels.append(SampleChannel(
            name=var.name,
            address=int(sym.address),
            size=int(sym.size),
            type_name=type_name,
            scale=var.scale,
            offset=var.offset,
            unit=var.unit,
        ))
    return channels


class DebugService(QObject):
    """调试会话服务 — 协议事务与流解码的单一入口。

    用法 (应用内)::

        svc = DebugService(session=session_controller, profile=profile)
        svc.setup_sample_list(0, period_us=2000, channels=[...])
        svc.start_stream(0)            # 之后 var/updated 自动产出真实数据

    用法 (测试/无 session)::

        svc = DebugService(writer=sent.append)
        svc.register_sample_layout(0, [...])
        svc.feed(raw_stream_frame_bytes)
    """

    # 命令码 (与 mcu_debug_stub 一致；DebugProtocol 未覆盖的在此补全)
    CMD_RESET = 0x0A
    CMD_DEVICE_CONTROL = 0x0C
    CMD_WAVE_CONFIG = 0x20
    CMD_WAVE_ARM = 0x21
    CMD_WAVE_STATUS = 0x22
    CMD_WAVE_UPLOAD = 0x23
    CMD_WAVE_DATA = 0x24
    CMD_WAVE_ABORT = 0x25
    CMD_WAVE_TRIGGER = 0x26
    CONTROL_STOP = 0x00
    CONTROL_START = 0x01
    MAX_BATCH_ITEMS = 32
    MAX_BATCH_DATA_SIZE = 256
    STATUS_CANCELLED = 0xFD
    STATUS_TIMEOUT = 0xFE

    def __init__(self, session=None, writer=None, profile=None,
                 parent: QObject | None = None, request_timeout_s: float = 1.0,
                 clock=None) -> None:
        super().__init__(parent)
        self._session = session
        self._profile = profile
        if writer is not None:
            self._writer = writer
        elif session is not None:
            self._writer = session.write
        else:
            self._writer = None
        self._buf = bytearray()
        self._seq = 0
        self._pending: dict[int, _PendingRequest] = {}
        self._layouts: dict[int, list[SampleChannel]] = {}
        self._periods_us: dict[int, int] = {}
        # 待 MCU 确认的采样布局，按 SET_SAMPLE 的 seq 暂存；仅在 status==0 的 ACK
        # 到达时提交到 _layouts。NACK/超时则丢弃并保留旧布局，使在线流持续可解码。
        self._pending_sample_layouts: dict[
            int, tuple[int, list[SampleChannel], int]
        ] = {}
        self._pending_wave_layouts: dict[
            int, tuple[list[SampleChannel], int, int]
        ] = {}
        self._wave_channels: list[SampleChannel] = []
        self._wave_period_us = 25
        self._wave_mode = WAVE_MODE_RECORDER
        self._wave_capture_id = 0
        self._wave_expected_sample: dict[int, int] = {}
        self._wave_expected_block: dict[int, int] = {}
        self._stats = DebugStats()
        self._max_buffer = 8192
        self._clock = clock or time.monotonic
        self._request_timeout_s = max(0.05, float(request_timeout_s))
        self._request_timer = QTimer(self)
        self._request_timer.setInterval(max(10, min(100, int(self._request_timeout_s * 250))))
        self._request_timer.timeout.connect(self._expire_pending)
        if session is not None and hasattr(session, "data_received"):
            session.data_received.connect(self.feed)

    # ------------------------------------------------------------------
    # 采样列表布局
    # ------------------------------------------------------------------

    def register_sample_layout(self, list_id: int, channels: list[SampleChannel],
                               period_us: int = 25) -> None:
        """登记某采样列表的通道布局（用于流帧定界与解码），不发送任何帧。"""
        self._layouts[list_id] = list(channels)
        self._periods_us[list_id] = max(1, int(period_us))

    def has_layout(self, list_id: int) -> bool:
        return list_id in self._layouts

    def clear_pending(self) -> None:
        """清理接收状态，并用取消响应收尾所有挂起事务。"""
        self._buf.clear()
        self._pending_sample_layouts.clear()
        self._pending_wave_layouts.clear()
        self._wave_capture_id = 0
        self._wave_expected_sample.clear()
        self._wave_expected_block.clear()
        pending = list(self._pending.items())
        self._pending.clear()
        self._request_timer.stop()
        for seq, request in pending:
            try:
                request.callback({
                    "cmd": 0, "seq": seq, "status": self.STATUS_CANCELLED,
                    "payload": b"", "cancelled": True,
                })
            except Exception:
                pass

    @property
    def stats(self) -> DebugStats:
        return self._stats

    def stats_snapshot(self) -> dict:
        s = self._stats
        return {
            "bytes_received": s.bytes_received, "frames_ok": s.frames_ok,
            "crc_errors": s.crc_errors, "responses": s.responses,
            "stream_frames": s.stream_frames, "var_updates": s.var_updates,
            "request_timeouts": s.request_timeouts,
            "wave_blocks": s.wave_blocks,
            "wave_decode_errors": s.wave_decode_errors,
            "wave_gap_samples": s.wave_gap_samples,
            "wave_raw_bytes": s.wave_raw_bytes,
            "wave_encoded_bytes": s.wave_encoded_bytes,
        }

    # ------------------------------------------------------------------
    # 命令发起
    # ------------------------------------------------------------------

    def _next_seq(self) -> int:
        self._seq = (self._seq + 1) & 0xFFFF
        if self._seq == 0:  # sequence 0 is reserved for unsolicited Wave data
            self._seq = 1
        return self._seq

    def _register_pending(self, seq: int, callback) -> None:
        if callback is None:
            return
        self._pending[seq] = _PendingRequest(
            callback=callback,
            deadline=self._clock() + self._request_timeout_s,
        )
        if not self._request_timer.isActive() and QCoreApplication.instance() is not None:
            self._request_timer.start()

    def _expire_pending(self) -> None:
        """使超时请求以非零状态回调，保证复合事务能够失败收尾。"""
        now = self._clock()
        expired = [
            (seq, request) for seq, request in self._pending.items()
            if request.deadline <= now
        ]
        for seq, request in expired:
            if self._pending.pop(seq, None) is None:
                continue
            self._pending_sample_layouts.pop(seq, None)
            self._pending_wave_layouts.pop(seq, None)
            self._stats.request_timeouts += 1
            try:
                request.callback({
                    "cmd": 0, "seq": seq, "status": self.STATUS_TIMEOUT,
                    "payload": b"", "timeout": True,
                })
            except Exception:
                pass
        if not self._pending:
            self._request_timer.stop()

    def _send(self, data: bytes) -> None:
        if self._writer is None:
            raise RuntimeError("DebugService 无可用的发送通道 (未提供 session 或 writer)")
        self._writer(data)

    def _send_request(self, seq: int, frame: bytes) -> None:
        """发送失败时撤销挂起项，避免稍后超时造成重复回调。"""
        try:
            self._send(frame)
        except Exception:
            self._pending.pop(seq, None)
            if not self._pending:
                self._request_timer.stop()
            raise

    def read_memory(self, address: int, size: int, callback=None) -> int:
        """读取内存：发送 READ_MEM 命令，返回 seq；响应到达时调用 callback(resp)。"""
        seq = self._next_seq()
        if callback is not None:
            self._register_pending(seq, callback)
        frame = DebugProtocol.build_frame(
            DebugProtocol.CMD_READ_MEM, seq, address, bytes([size & 0xFF]))
        self._send_request(seq, frame)
        return seq

    def read_batch(self, items, callback=None) -> int:
        """Read multiple scalar memory regions in one READ_BATCH transaction.

        ``items`` is an iterable of ``(address, size)`` pairs. The response
        payload concatenates each item in request order; callers retain the
        layout for decoding.
        """
        try:
            normalized = [(int(address), int(size)) for address, size in items]
        except (TypeError, ValueError):
            raise ValueError("READ_BATCH items 必须是 (address, size) 序列") from None
        if not 1 <= len(normalized) <= self.MAX_BATCH_ITEMS:
            raise ValueError(f"READ_BATCH 项数必须为 1..{self.MAX_BATCH_ITEMS}")

        total_size = 0
        for address, size in normalized:
            if size not in (1, 2, 4, 8):
                raise ValueError(f"READ_BATCH 不支持的宽度: {size}")
            if address < 0 or address > 0xFFFFFFFF - (size - 1):
                raise ValueError(f"READ_BATCH 地址超出32位范围: {address}")
            total_size += size
        if total_size > self.MAX_BATCH_DATA_SIZE:
            raise ValueError(
                f"READ_BATCH 响应长度 {total_size} 超过 {self.MAX_BATCH_DATA_SIZE}")

        payload = bytearray([len(normalized)])
        for address, size in normalized:
            payload += struct.pack("<IB", address, size)
        seq = self._next_seq()
        if callback is not None:
            self._register_pending(seq, callback)
        frame = DebugProtocol.build_frame(
            DebugProtocol.CMD_READ_BATCH, seq, 0, bytes(payload))
        self._send_request(seq, frame)
        return seq

    def write_memory(self, address: int, data: bytes, callback=None) -> int:
        """写入内存：发送 WRITE_MEM 命令。"""
        seq = self._next_seq()
        if callback is not None:
            self._register_pending(seq, callback)
        frame = DebugProtocol.build_frame(
            DebugProtocol.CMD_WRITE_MEM, seq, address, bytes(data))
        self._send_request(seq, frame)
        return seq

    def write_and_verify(self, address: int, data: bytes, size: int, callback=None) -> int:
        """写入后立即读回校验（WRITE_MEM → READ_MEM → 逐字节比对）。

        callback(ok: bool, readback: bytes) 在完成时调用。返回写命令 seq。
        适合配合固件 g_uart_debug_scratch 做无副作用写路径验证。
        """
        data = bytes(data)

        def after_read(resp):
            ok = (resp.get("status", 0) == 0
                  and bytes(resp.get("payload", b""))[:size] == data[:size])
            if callback is not None:
                callback(ok, bytes(resp.get("payload", b"")))

        def after_write(resp):
            if resp.get("status", 0) != 0:
                if callback is not None:
                    callback(False, b"")
                return
            self.read_memory(int(address), int(size), callback=after_read)

        return self.write_memory(int(address), data, callback=after_write)

    def get_info(self, callback=None) -> int:
        seq = self._next_seq()
        if callback is not None:
            self._register_pending(seq, callback)
        frame = DebugProtocol.build_frame(DebugProtocol.CMD_GET_INFO, seq, 0, b"")
        self._send_request(seq, frame)
        return seq

    def reset(self, callback=None) -> int:
        seq = self._next_seq()
        if callback is not None:
            self._register_pending(seq, callback)
        frame = DebugProtocol.build_frame(self.CMD_RESET, seq, 0, b"")
        self._send_request(seq, frame)
        return seq

    def device_control(self, running: bool, callback=None) -> int:
        """启停设备 (DEVICE_CONTROL 0x0C)。running=True→START(01), False→STOP(00)。"""
        seq = self._next_seq()
        if callback is not None:
            self._register_pending(seq, callback)
        payload = bytes([self.CONTROL_START if running else self.CONTROL_STOP])
        frame = DebugProtocol.build_frame(self.CMD_DEVICE_CONTROL, seq, 0, payload)
        self._send_request(seq, frame)
        return seq

    @staticmethod
    def parse_device_info(payload: bytes) -> dict:
        """Parse the stable GET_INFO prefix and optional v2 diagnostics."""
        if len(payload) < 44:
            return {}
        model = payload[0:32].split(b"\x00")[0].decode("ascii", "replace")
        cpu_freq, elf_crc = struct.unpack_from("<II", payload, 32)
        protocol_ver = struct.unpack_from("<H", payload, 40)[0]
        fw = payload[42:58].split(b"\x00")[0].decode("ascii", "replace")
        info = {
            "model": model,
            "cpu_freq_hz": cpu_freq,
            "elf_crc": elf_crc,
            "protocol_ver": protocol_ver,
            "fw_version": fw,
        }
        optional_u32 = (
            (58, "stream_ring_drops"),
            (62, "tx_busy_retries"),
            (66, "tx_recovery_count"),
            (70, "last_init_error"),
            (74, "stim1_max_cycles"),
            (78, "stim3_max_cycles"),
            (82, "feature_flags"),
            (86, "wave_buffer_bytes"),
        )
        for offset, name in optional_u32:
            if len(payload) >= offset + 4:
                info[name] = struct.unpack_from("<I", payload, offset)[0]
        if len(payload) >= 92:
            info["max_wave_block_points"] = struct.unpack_from(
                "<H", payload, 90)[0]
        if len(payload) >= 93:
            info["max_wave_channels"] = payload[92]
        if len(payload) >= 94:
            info["max_wave_descriptor_bytes"] = payload[93]
        return info

    def setup_sample_list(self, list_id: int, period_us: int,
                          channels: list[SampleChannel], callback=None) -> int:
        """下发采样列表 (SET_SAMPLE) 并登记布局。

        payload: list_id(1) + period_us(2 LE) + count(1)
                 + [addr(4) size(1) type_code(1)] * count
        """
        payload = bytearray()
        payload.append(list_id & 0xFF)
        payload += struct.pack("<H", period_us & 0xFFFF)
        payload.append(len(channels) & 0xFF)
        for ch in channels:
            payload += struct.pack(
                _SAMPLE_ITEM_FMT, ch.address & 0xFFFFFFFF, ch.size & 0xFF,
                wave_type_code(ch.type_name, ch.size))
        seq = self._next_seq()
        # 暂存待确认布局；提交推迟到 SET_SAMPLE 的 OK ACK（见 _dispatch_response）。
        self._pending_sample_layouts[seq] = (list_id, list(channels), int(period_us))
        if callback is not None:
            self._register_pending(seq, callback)
        frame = DebugProtocol.build_frame(
            DebugProtocol.CMD_SET_SAMPLE, seq, 0, bytes(payload))
        self._send_request(seq, frame)
        return seq

    def start_stream(self, list_id: int, callback=None) -> int:
        seq = self._next_seq()
        if callback is not None:
            self._register_pending(seq, callback)
        frame = DebugProtocol.build_frame(
            DebugProtocol.CMD_START_STREAM, seq, 0, bytes([list_id & 0xFF]))
        self._send_request(seq, frame)
        return seq

    def stop_stream(self, list_id: int, callback=None) -> int:
        seq = self._next_seq()
        if callback is not None:
            self._register_pending(seq, callback)
        frame = DebugProtocol.build_frame(
            DebugProtocol.CMD_STOP_STREAM, seq, 0, bytes([list_id & 0xFF]))
        self._send_request(seq, frame)
        return seq

    def configure_wave(self, channels: list[SampleChannel], points: int,
                       tap_id: int = 1, period_us: int = 25,
                       callback=None, *, mode: int = WAVE_MODE_RECORDER,
                       pretrigger_points: int = 0,
                       posttrigger_points: int | None = None,
                       block_points: int = 0) -> int:
        """Configure an exact recorder, trigger recorder, or lossless Live stream.

        The legacy 11+6*N payload is retained for an immediate recorder without
        64-bit sequence guards. Advanced modes use the v2 extension header.
        """
        channels = list(channels)
        points = int(points)
        period_us = int(period_us)
        tap_id = int(tap_id)
        mode = int(mode)
        pretrigger_points = int(pretrigger_points)
        if not 1 <= len(channels) <= 16:
            raise ValueError("录波通道数必须为 1..16")
        if tap_id not in (0, 1):
            raise ValueError("tap_id 必须为 0(ADC_READY) 或 1(CONTROL_END)")
        if period_us != 25:
            raise ValueError("Wave 固定使用 25us 采样周期")
        if mode not in (WAVE_MODE_RECORDER, WAVE_MODE_TRIGGERED, WAVE_MODE_LIVE):
            raise ValueError("Wave mode 必须为 Recorder/Triggered/Live")
        if points <= 0:
            raise ValueError("录波点数必须大于 0")
        if mode == WAVE_MODE_LIVE and not 2 <= points < 0xFFFF:
            raise ValueError("Live 环形缓冲点数必须为 2..65534")

        row_bytes = 0
        max_size = 0
        descriptor_size = 6
        for channel in channels:
            if channel.size not in (1, 2, 4, 8):
                raise ValueError(f"录波不支持的宽度: {channel.size}")
            address = int(channel.address)
            sequence_address = int(channel.sequence_address)
            if not 0 <= address <= 0xFFFFFFFF:
                raise ValueError(f"通道地址超出 32 位: {channel.name}")
            if sequence_address:
                if channel.size != 8:
                    raise ValueError("sequence_address 只用于 8 字节通道")
                if not 0 <= sequence_address <= 0xFFFFFFFF or sequence_address & 3:
                    raise ValueError("sequence_address 必须是 4 字节对齐的 32 位地址")
                descriptor_size = 10
            row_bytes += int(channel.size)
            max_size = max(max_size, int(channel.size))
        if row_bytes > 64:
            raise ValueError("单个录波点总宽度不能超过 64 字节")
        required_bytes = ((points + 1) * (row_bytes + 4)
                          if mode == WAVE_MODE_LIVE else points * row_bytes)
        if required_bytes > WAVE_BUFFER_BYTES:
            raise ValueError(
                f"Wave 需要 {required_bytes} 字节，超过 MCU 128KB Wave 区")

        if mode == WAVE_MODE_TRIGGERED:
            posttrigger_points = (points - pretrigger_points if
                                  posttrigger_points is None else
                                  int(posttrigger_points))
            if (pretrigger_points < 0 or posttrigger_points <= 0 or
                    pretrigger_points + posttrigger_points != points):
                raise ValueError("触发录波要求 pre + post == points 且 post > 0")
        else:
            if pretrigger_points != 0 or posttrigger_points not in (None, 0):
                raise ValueError("只有 Triggered 模式可配置前/后触发点")
            pretrigger_points = 0
            posttrigger_points = 0

        if mode == WAVE_MODE_LIVE:
            if block_points <= 0:
                block_points = min(512, points)
            block_points = int(block_points)
            if not 1 <= block_points <= 512:
                raise ValueError("Live block_points 必须为 1..512")
            if block_points > points:
                raise ValueError("Live 环形缓冲点数不能小于 block_points")
        elif block_points:
            raise ValueError("block_points 只用于 Live 模式")

        extended = (mode != WAVE_MODE_RECORDER or descriptor_size == 10)
        payload = bytearray(struct.pack(
            "<BBIIB", mode, tap_id, period_us, points, len(channels)))
        if extended:
            payload += struct.pack(
                _WAVE_EXT_HEADER_FMT, pretrigger_points, posttrigger_points,
                block_points, 0x01, descriptor_size)
        for channel in channels:
            payload += struct.pack(
                _SAMPLE_ITEM_FMT,
                channel.address & 0xFFFFFFFF,
                channel.size & 0xFF,
                wave_type_code(channel.type_name, channel.size),
            )
            if extended and descriptor_size == 10:
                payload += struct.pack("<I", channel.sequence_address & 0xFFFFFFFF)

        seq = self._next_seq()
        self._pending_wave_layouts[seq] = (channels, period_us, mode)
        if callback is not None:
            self._register_pending(seq, callback)
        frame = DebugProtocol.build_frame(
            self.CMD_WAVE_CONFIG, seq, 0, bytes(payload))
        self._send_request(seq, frame)
        return seq

    def arm_wave(self, callback=None) -> int:
        seq = self._next_seq()
        if callback is not None:
            self._register_pending(seq, callback)
        frame = DebugProtocol.build_frame(self.CMD_WAVE_ARM, seq, 0, b"")
        self._send_request(seq, frame)
        return seq

    def get_wave_status(self, callback=None) -> int:
        seq = self._next_seq()
        if callback is not None:
            self._register_pending(seq, callback)
        frame = DebugProtocol.build_frame(self.CMD_WAVE_STATUS, seq, 0, b"")
        self._send_request(seq, frame)
        return seq

    def read_wave_chunk(self, offset: int, max_bytes: int = 112,
                        callback=None) -> int:
        offset = int(offset)
        max_bytes = int(max_bytes)
        if offset < 0 or offset > 0xFFFFFFFF:
            raise ValueError("录波上传 offset 超出 32 位范围")
        if not 1 <= max_bytes <= 112:
            raise ValueError("录波分片大小必须为 1..112 字节")
        seq = self._next_seq()
        if callback is not None:
            self._register_pending(seq, callback)
        payload = struct.pack("<IH", offset, max_bytes)
        frame = DebugProtocol.build_frame(
            self.CMD_WAVE_UPLOAD, seq, 0, payload)
        self._send_request(seq, frame)
        return seq

    def abort_wave(self, callback=None) -> int:
        seq = self._next_seq()
        if callback is not None:
            self._register_pending(seq, callback)
        frame = DebugProtocol.build_frame(self.CMD_WAVE_ABORT, seq, 0, b"")
        self._send_request(seq, frame)
        return seq

    def trigger_wave(self, callback=None) -> int:
        seq = self._next_seq()
        if callback is not None:
            self._register_pending(seq, callback)
        frame = DebugProtocol.build_frame(self.CMD_WAVE_TRIGGER, seq, 0, b"")
        self._send_request(seq, frame)
        return seq

    def start_wave_upload(self, offset: int = 0, callback=None) -> int:
        """Start resumable, low-priority automatic Recorder upload."""
        offset = int(offset)
        if not 0 <= offset <= 0xFFFFFFFF:
            raise ValueError("录波上传 offset 超出 32 位范围")
        seq = self._next_seq()
        if callback is not None:
            self._register_pending(seq, callback)
        frame = DebugProtocol.build_frame(
            self.CMD_WAVE_UPLOAD, seq, 0, struct.pack("<IH", offset, 0))
        self._send_request(seq, frame)
        return seq

    @staticmethod
    def parse_wave_config(payload: bytes) -> dict:
        if len(payload) < 16:
            return {}
        capture_id, period_us, points, row_bytes, tap_id, count = struct.unpack_from(
            "<IIIHBB", payload, 0)
        result = {
            "capture_id": capture_id, "period_us": period_us,
            "total_points": points, "row_bytes": row_bytes,
            "tap_id": tap_id, "channel_count": count,
            "mode": WAVE_MODE_RECORDER, "pretrigger_points": 0,
            "posttrigger_points": 0, "block_points": 0,
            "descriptor_size": 6, "flags": 0,
        }
        if len(payload) >= 28:
            result.update({
                "pretrigger_points": struct.unpack_from("<I", payload, 16)[0],
                "posttrigger_points": struct.unpack_from("<I", payload, 20)[0],
                "block_points": struct.unpack_from("<H", payload, 24)[0],
                "descriptor_size": payload[26], "flags": payload[27],
            })
        return result

    @staticmethod
    def parse_wave_status(payload: bytes) -> WaveStatus | None:
        if len(payload) < 29:
            return None
        return WaveStatus(
            state=payload[0], tap_id=payload[1], mode=payload[2],
            channel_count=payload[3], capture_id=struct.unpack_from("<I", payload, 4)[0],
            captured_points=struct.unpack_from("<I", payload, 8)[0],
            total_points=struct.unpack_from("<I", payload, 12)[0],
            row_bytes=struct.unpack_from("<H", payload, 16)[0],
            period_us=struct.unpack_from("<H", payload, 18)[0],
            buffer_high_water=struct.unpack_from("<I", payload, 20)[0],
            overflow_count=struct.unpack_from("<I", payload, 24)[0],
            compression_status=payload[28],
            pretrigger_points=(struct.unpack_from("<I", payload, 29)[0]
                               if len(payload) >= 33 else 0),
            posttrigger_points=(struct.unpack_from("<I", payload, 33)[0]
                                if len(payload) >= 37 else 0),
            tx_high_water=(struct.unpack_from("<H", payload, 37)[0]
                           if len(payload) >= 39 else 0),
            tx_low_water=(struct.unpack_from("<H", payload, 39)[0]
                          if len(payload) >= 41 else 0),
            tx_high_overflow=(struct.unpack_from("<I", payload, 41)[0]
                              if len(payload) >= 45 else 0),
            tx_low_overflow=(struct.unpack_from("<I", payload, 45)[0]
                             if len(payload) >= 49 else 0),
            atomic_retries=(struct.unpack_from("<I", payload, 49)[0]
                            if len(payload) >= 53 else 0),
            atomic_failures=(struct.unpack_from("<I", payload, 53)[0]
                             if len(payload) >= 57 else 0),
            non_atomic_mask=(struct.unpack_from("<H", payload, 57)[0]
                             if len(payload) >= 59 else 0),
            capture_isr_max_cycles=(struct.unpack_from("<I", payload, 59)[0]
                                    if len(payload) >= 63 else 0),
            live_raw_bytes=(struct.unpack_from("<I", payload, 63)[0]
                            if len(payload) >= 67 else 0),
            live_encoded_bytes=(struct.unpack_from("<I", payload, 67)[0]
                                if len(payload) >= 71 else 0),
        )

    @staticmethod
    def parse_wave_data(payload: bytes) -> WaveDataBlock | None:
        if len(payload) < 20:
            return None
        data_len = struct.unpack_from("<H", payload, 18)[0]
        if len(payload) != 20 + data_len:
            return None
        return WaveDataBlock(
            capture_id=struct.unpack_from("<I", payload, 0)[0],
            block_seq=struct.unpack_from("<H", payload, 4)[0],
            offset=struct.unpack_from("<I", payload, 6)[0],
            first_sample_id=struct.unpack_from("<I", payload, 10)[0],
            sample_count=struct.unpack_from("<H", payload, 14)[0],
            encoding=payload[16], tap_id=payload[17], data=bytes(payload[20:]),
        )

    @staticmethod
    def decode_live_wave_block(block: WaveDataBlock,
                               channels: list[SampleChannel],
                               period_us: int = 25) -> dict:
        if block.encoding != WAVE_ENCODING_LIVE_CHANNEL or len(block.data) < 6:
            raise ValueError("不是有效的 Live 通道块")
        channel_id, codec_id, parameter, value_size, encoded_len = \
            struct.unpack_from(_WAVE_LIVE_CHANNEL_FMT, block.data, 0)
        if channel_id >= len(channels):
            raise ValueError("Live channel_id 超出配置布局")
        if len(block.data) != 6 + encoded_len:
            raise ValueError("Live encoded_length 与负载不匹配")
        channel = channels[channel_id]
        if value_size != channel.size:
            raise ValueError("Live value_size 与通道布局不匹配")
        type_code = wave_type_code(channel.type_name, channel.size)
        raw = decode_channel(codec_id, parameter, block.data[6:], value_size,
                             block.sample_count, type_code)
        raw_values = []
        phys_values = []
        timestamps = []
        for index in range(block.sample_count):
            offset = index * value_size
            value = decode_value(raw[offset:offset + value_size], channel.type_name)
            raw_values.append(value)
            phys_values.append(None if isinstance(value, (bytes, bytearray)) else
                               value * channel.scale + channel.offset)
            timestamps.append((block.first_sample_id + index) * period_us / 1e6)
        return {
            "channel_id": channel_id, "name": channel.name,
            "codec_id": codec_id,
            "codec_name": CODEC_NAMES.get(codec_id, f"UNKNOWN_{codec_id}"),
            "codec_parameter": parameter, "first_sample_id": block.first_sample_id,
            "sample_count": block.sample_count, "raw_bytes": raw,
            "raw_values": raw_values, "phys_values": phys_values,
            "timestamps": timestamps, "unit": channel.unit,
            "encoded_bytes": encoded_len,
            "bits_per_sample": bits_per_sample(encoded_len, block.sample_count),
            "block_seq": block.block_seq, "capture_id": block.capture_id,
        }

    @staticmethod
    def decode_wave_capture(data: bytes, channels: list[SampleChannel],
                            period_us: int = 25, start_sample_id: int = 0) -> dict:
        row_bytes = sum(channel.size for channel in channels)
        if row_bytes <= 0 or len(data) % row_bytes:
            raise ValueError("录波原始数据长度与通道布局不匹配")
        result = {
            channel.name: {"timestamps": [], "raw_values": [],
                           "phys_values": [], "unit": channel.unit}
            for channel in channels
        }
        for sample_index in range(len(data) // row_bytes):
            offset = sample_index * row_bytes
            timestamp = (start_sample_id + sample_index) * period_us / 1e6
            for channel in channels:
                raw = data[offset:offset + channel.size]
                offset += channel.size
                value = decode_value(raw, channel.type_name)
                physical = None if isinstance(value, (bytes, bytearray)) else (
                    value * channel.scale + channel.offset)
                item = result[channel.name]
                item["timestamps"].append(timestamp)
                item["raw_values"].append(value)
                item["phys_values"].append(physical)
        return result

    # ------------------------------------------------------------------
    # 入站字节流 → 帧
    # ------------------------------------------------------------------

    def feed(self, data: bytes) -> None:
        """接收原始字节流，定界并分发其中的完整帧。"""
        if data:
            self._buf.extend(data)
            self._stats.bytes_received += len(data)
        if len(self._buf) > self._max_buffer:
            del self._buf[:-self._max_buffer]
        while self._try_one():
            pass

    def _try_one(self) -> bool:
        """尝试推进一步：消费一帧 / 丢弃垃圾返回 True；数据不足返回 False。"""
        idx = self._find_sof()
        if idx < 0:
            if len(self._buf) > 1:
                del self._buf[:-1]   # 仅保留可能是 SOF0 的最后一字节
            return False
        if idx > 0:
            del self._buf[:idx]
        if len(self._buf) < 4:
            return False             # 还读不到 cmd
        cmd = self._buf[3]
        if cmd == DebugProtocol.CMD_STREAM_DATA:
            return self._try_stream()
        return self._try_response()

    def _find_sof(self) -> int:
        buf = self._buf
        for i in range(len(buf) - 1):
            if buf[i] == SOF0 and buf[i + 1] == SOF1:
                return i
        return -1

    def _skip_past_current_sof(self) -> None:
        """Skip past the current SOF to the next SOF in the buffer.

        Used for recovery when a frame fails CRC, has unknown layout, or
        exceeds max size.  Instead of dropping 1 byte at a time (which can
        hit false SOF patterns inside payload data and cause cascading
        failures), we skip directly to the next valid SOF boundary.
        """
        buf = self._buf
        if len(buf) <= 1:
            buf.clear()
            return
        del buf[:1]
        for i in range(len(buf) - 1):
            if buf[i] == SOF0 and buf[i + 1] == SOF1:
                if i > 0:
                    del buf[:i]
                return
        if len(buf) > 1:
            del buf[:-1]

    def _try_response(self) -> bool:
        buf = self._buf
        if len(buf) < 9:
            return False
        plen = buf[7] | (buf[8] << 8)
        total = 9 + plen + 2
        if total > _MAX_FRAME_BYTES:
            self._skip_past_current_sof()
            return True
        if len(buf) < total:
            return False
        frame = bytes(buf[:total])
        if not self._crc_ok(frame):
            self._stats.crc_errors += 1
            self._skip_past_current_sof()   # CRC 错，跳到下一个 SOF
            return True
        del buf[:total]
        self._stats.responses += 1
        self._stats.frames_ok += 1
        self._dispatch_response(frame, plen)
        return True

    def _try_stream(self) -> bool:
        buf = self._buf
        if len(buf) < 12:
            return False
        list_id = buf[10]
        sample_count = buf[11] or 1
        layout = self._layouts.get(list_id)
        if layout is None:
            # 布局未知 → 无法确定帧长，跳到下一个 SOF
            self._skip_past_current_sof()
            return True
        sample_size = sum(ch.size for ch in layout)
        plen = sample_size * sample_count
        total = 12 + plen + 2
        if total > _MAX_FRAME_BYTES:
            self._skip_past_current_sof()
            return True
        if len(buf) < total:
            return False
        frame = bytes(buf[:total])
        if not self._crc_ok(frame):
            self._stats.crc_errors += 1
            self._skip_past_current_sof()
            return True
        del buf[:total]
        self._stats.stream_frames += 1
        self._stats.frames_ok += 1
        self._dispatch_stream(frame, list_id, sample_count, layout, sample_size)
        return True

    @staticmethod
    def _crc_ok(frame: bytes) -> bool:
        crc_calc = CRC16.calc(frame[:-2])
        crc_recv = frame[-2] | (frame[-1] << 8)
        return crc_calc == crc_recv

    # ------------------------------------------------------------------
    # 分发
    # ------------------------------------------------------------------

    def _dispatch_response(self, frame: bytes, plen: int) -> None:
        seq = frame[4] | (frame[5] << 8)
        resp = {
            "cmd": frame[3],
            "seq": seq,
            "status": frame[6],
            "payload": frame[9:9 + plen],
        }
        request = self._pending.pop(seq, None)
        if not self._pending:
            self._request_timer.stop()
        # 采样布局提交：仅当 MCU 以 status==0 确认 SET_SAMPLE 时切换解码布局；
        # NACK 时丢弃待确认布局，保留旧布局，让 MCU 实际仍在发的旧流帧持续可解码。
        proposed = self._pending_sample_layouts.pop(seq, None)
        if proposed is not None and resp["status"] == 0:
            effective_period = proposed[2]
            if len(resp["payload"]) >= 4:
                effective_period = struct.unpack_from("<I", resp["payload"], 0)[0]
            self.register_sample_layout(
                proposed[0], proposed[1], effective_period)
        wave_proposed = self._pending_wave_layouts.pop(seq, None)
        if (wave_proposed is not None and resp["status"] == 0 and
                resp["cmd"] == self.CMD_WAVE_CONFIG):
            self._wave_channels = list(wave_proposed[0])
            self._wave_period_us = int(wave_proposed[1])
            self._wave_mode = int(wave_proposed[2])
            self._wave_capture_id = (struct.unpack_from(
                "<I", resp["payload"], 0)[0]
                if len(resp["payload"]) >= 4 else 0)
            self._wave_expected_sample.clear()
            self._wave_expected_block.clear()
        if resp["cmd"] == self.CMD_WAVE_DATA and resp["status"] == 0:
            self._dispatch_wave_data(resp["payload"])
        if request is not None:
            try:
                request.callback(resp)
            except Exception:
                pass
        EventBus.instance().publish("debug/response", resp)

    def _dispatch_wave_data(self, payload: bytes) -> None:
        block = self.parse_wave_data(payload)
        if block is None:
            self._stats.wave_decode_errors += 1
            EventBus.instance().publish("wave/error", {
                "reason": "WAVE_DATA 长度或头部无效", "payload": bytes(payload)})
            return
        bus = EventBus.instance()
        if (block.encoding == WAVE_ENCODING_LIVE_CHANNEL and
                self._wave_capture_id and
                block.capture_id != self._wave_capture_id):
            self._stats.wave_decode_errors += 1
            bus.publish("wave/error", {
                "reason": "Live capture_id 与当前配置不匹配", "block": block})
            return
        self._stats.wave_blocks += 1
        bus.publish("wave/data", block)
        if block.encoding != WAVE_ENCODING_LIVE_CHANNEL:
            return
        try:
            decoded = self.decode_live_wave_block(
                block, self._wave_channels, self._wave_period_us)
        except (ValueError, struct.error) as exc:
            self._stats.wave_decode_errors += 1
            bus.publish("wave/error", {"reason": str(exc), "block": block})
            return

        channel_id = decoded["channel_id"]
        expected_block = self._wave_expected_block.get(channel_id)
        if expected_block is not None and block.block_seq != expected_block:
            block_delta = (block.block_seq - expected_block) & 0xFFFF
            if block_delta >= 0x8000:
                self._stats.wave_decode_errors += 1
                bus.publish("wave/error", {
                    "reason": "Live block_seq 重复或倒序", "block": block})
                return
            bus.publish("wave/error", {
                "reason": f"Live block_seq 缺失 {block_delta} 块", "block": block})
        self._wave_expected_block[channel_id] = (
            1 if block.block_seq == 0xFFFF else block.block_seq + 1)

        expected = self._wave_expected_sample.get(channel_id)
        first_sample = decoded["first_sample_id"]
        if expected is None:
            unwrapped_first = first_sample
            gap = 0
        else:
            gap = (first_sample - (expected & 0xFFFFFFFF)) & 0xFFFFFFFF
            if gap >= 0x80000000:
                self._stats.wave_decode_errors += 1
                bus.publish("wave/error", {
                    "reason": "Live sample_id 重复或倒序", "block": block})
                return
            unwrapped_first = expected + gap
        decoded["gap_samples"] = gap
        decoded["first_sample_id_unwrapped"] = unwrapped_first
        decoded["timestamps"] = [
            (unwrapped_first + index) * self._wave_period_us / 1e6
            for index in range(decoded["sample_count"])
        ]
        self._stats.wave_gap_samples += gap
        self._wave_expected_sample[channel_id] = (
            unwrapped_first + decoded["sample_count"])
        self._stats.wave_raw_bytes += len(decoded["raw_bytes"])
        self._stats.wave_encoded_bytes += decoded["encoded_bytes"]
        bus.publish("wave/live_block", decoded)

    def _dispatch_stream(self, frame: bytes, list_id: int, sample_count: int,
                         layout: list[SampleChannel], sample_size: int) -> None:
        ts_us = frame[6] | (frame[7] << 8) | (frame[8] << 16) | (frame[9] << 24)
        payload = frame[12:12 + sample_size * sample_count]
        period_us = self._periods_us.get(list_id, 25)
        bus = EventBus.instance()
        published = 0
        for s in range(sample_count):
            off = s * sample_size
            for ch in layout:
                raw = payload[off:off + ch.size]
                off += ch.size
                reg = decode_value(raw, ch.type_name)
                if isinstance(reg, (bytes, bytearray)):
                    continue          # 解码失败（类型未知/字节不足），跳过该通道
                phys = reg * ch.scale + ch.offset
                bus.publish("var/updated", VarUpdatedEvent(
                    name=ch.name,
                    raw_value=reg,
                    phys_value=phys,
                    unit=ch.unit,
                    timestamp=(ts_us + s * period_us) / 1e6,
                    source="stream",
                ))
                published += 1
        self._stats.var_updates += published







