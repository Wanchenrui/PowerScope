"""protocol_engine.py — 调试协议帧解析状态机

从字节流中提取完整帧，通过 EventBus 发布 FrameReceivedEvent。
支持调试协议响应帧（9 字节头）和命令帧（12 字节头）。
"""
from __future__ import annotations

import time
from typing import Callable

from .event_bus import EventBus, FrameReceivedEvent
from .cffi_loader import CRC16, DebugProtocol


class ProtocolEngine:
    """调试协议帧解析状态机

    使用方式:
        engine = ProtocolEngine()
        events = engine.feed(b"...raw bytes...")

    解析成功后会自动通过 EventBus 发布 ``frame/received`` 事件。
    """

    SOF = bytes([0xA5, 0x5A])
    HDR_SIZE_RESP = 9   # 响应帧头: SOF(2)+VER(1)+CMD(1)+SEQ(2)+STATUS(1)+LEN(2)
    HDR_SIZE_CMD = 12   # 命令帧头: SOF(2)+VER(1)+CMD(1)+SEQ(2)+ADDR(4)+LEN(2)
    CRC_SIZE = 2

    def __init__(self, max_buffer: int = 4096) -> None:
        self._buf = bytearray()
        self._max_buffer = max_buffer

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    def feed(self, data: bytes) -> list[FrameReceivedEvent]:
        """接收字节流，返回本次解析出的帧事件列表。

        每解析出一帧，会自动通过 EventBus 发布 ``frame/received`` 事件。
        """
        if data:
            self._buf.extend(data)

        # 防溢出：保留最近 max_buffer 字节
        if len(self._buf) > self._max_buffer:
            self._buf = self._buf[-self._max_buffer:]

        frames: list[FrameReceivedEvent] = []
        while True:
            prev_len = len(self._buf)
            event = self._try_parse_one()
            if event is not None:
                frames.append(event)
                EventBus.instance().publish("frame/received", event)
                continue
            # 没有解析出事件
            if len(self._buf) == prev_len:
                # 缓冲区没有变化，说明数据不足，停止循环
                break
            # 缓冲区变化了（丢弃了垃圾数据），继续尝试
        return frames

    def reset(self) -> None:
        """重置状态机，清空缓冲区"""
        self._buf.clear()

    # ------------------------------------------------------------------
    # 内部解析
    # ------------------------------------------------------------------

    def _try_parse_one(self) -> FrameReceivedEvent | None:
        """尝试从缓冲区解析一帧，成功则截断缓冲区并返回事件"""
        # 1) 搜索 SOF
        sof_idx = self._find_sof()
        if sof_idx < 0:
            # 无 SOF，但保留最后一个字节（可能是 0xA5）
            if len(self._buf) > 1:
                self._buf = self._buf[-1:]
            return None

        if sof_idx > 0:
            # 丢弃 SOF 前的垃圾数据
            self._buf = self._buf[sof_idx:]

        # 2) 尝试解析为响应帧（9 字节头）—— PC 端最常见
        event = self._try_parse_response()
        if event is not None:
            return event

        # 3) 尝试解析为命令帧（12 字节头）
        event = self._try_parse_command()
        if event is not None:
            return event

        # 4) 两种解析都失败。
        #    如果数据足够长（至少能完整解析响应帧或命令帧），说明是 CRC 错误/垃圾数据，
        #    丢弃 SOF 后 1 字节让外层重新搜索；否则保留 SOF 等待更多数据。
        if self._has_enough_data_for_any_frame():
            self._buf = self._buf[1:]
        return None

    def _has_enough_data_for_any_frame(self) -> bool:
        """检查缓冲区是否足够长以解析至少一种完整帧（响应帧或命令帧）。"""
        # 响应帧：需要至少 9 字节头 + payload_len + 2 CRC
        if len(self._buf) >= self.HDR_SIZE_RESP:
            resp_payload_len = self._buf[7] | (self._buf[8] << 8)
            if len(self._buf) >= self.HDR_SIZE_RESP + resp_payload_len + self.CRC_SIZE:
                return True
        # 命令帧：需要至少 12 字节头 + payload_len + 2 CRC
        if len(self._buf) >= self.HDR_SIZE_CMD:
            cmd_payload_len = self._buf[10] | (self._buf[11] << 8)
            if len(self._buf) >= self.HDR_SIZE_CMD + cmd_payload_len + self.CRC_SIZE:
                return True
        return False

    def _find_sof(self) -> int:
        """返回 SOF 在缓冲区中的索引，未找到返回 -1"""
        for i in range(len(self._buf) - 1):
            if self._buf[i] == 0xA5 and self._buf[i + 1] == 0x5A:
                return i
        return -1

    # ----- 响应帧 (9 字节头) -----

    def _try_parse_response(self) -> FrameReceivedEvent | None:
        """尝试解析为响应帧（9 字节头），成功时截断缓冲区。"""
        if len(self._buf) < self.HDR_SIZE_RESP:
            return None

        payload_len = self._buf[7] | (self._buf[8] << 8)
        expected_len = self.HDR_SIZE_RESP + payload_len + self.CRC_SIZE

        if len(self._buf) < expected_len:
            return None

        frame_data = bytes(self._buf[:expected_len])

        # CRC 校验
        crc_calc = CRC16.calc(frame_data[:-2])
        crc_recv = frame_data[-2] | (frame_data[-1] << 8)
        if crc_calc != crc_recv:
            # CRC 失败：不修改 self._buf，让 _try_parse_one 统一决定是丢弃 SOF 还是等待更多数据
            return None

        # 成功，截断缓冲区
        self._buf = self._buf[expected_len:]
        return self._make_event(frame_data, "response")

    # ----- 命令帧 (12 字节头) -----

    def _try_parse_command(self) -> FrameReceivedEvent | None:
        """尝试解析为命令帧（12 字节头），成功时截断缓冲区。"""
        if len(self._buf) < self.HDR_SIZE_CMD:
            return None

        payload_len = self._buf[10] | (self._buf[11] << 8)
        expected_len = self.HDR_SIZE_CMD + payload_len + self.CRC_SIZE

        if len(self._buf) < expected_len:
            return None

        frame_data = bytes(self._buf[:expected_len])

        crc_calc = CRC16.calc(frame_data[:-2])
        crc_recv = frame_data[-2] | (frame_data[-1] << 8)
        if crc_calc != crc_recv:
            # CRC 失败：不修改 self._buf，让 _try_parse_one 统一决定
            return None

        self._buf = self._buf[expected_len:]
        return self._make_event(frame_data, "command")

    # ----- 事件构造 -----

    def _make_event(self, frame_data: bytes, frame_type: str) -> FrameReceivedEvent:
        """从已校验的完整帧构造 FrameReceivedEvent"""
        if frame_type == "response":
            payload_len = frame_data[7] | (frame_data[8] << 8)
            payload = frame_data[9:9 + payload_len] if payload_len > 0 else b""
            return FrameReceivedEvent(
                protocol="debug",
                cmd=frame_data[3],
                seq=frame_data[4] | (frame_data[5] << 8),
                payload=payload,
                raw_frame=frame_data,
                status=frame_data[6],
                timestamp=time.time(),
            )
        else:  # command
            payload_len = frame_data[10] | (frame_data[11] << 8)
            payload = frame_data[12:12 + payload_len] if payload_len > 0 else b""
            return FrameReceivedEvent(
                protocol="debug",
                cmd=frame_data[3],
                seq=frame_data[4] | (frame_data[5] << 8),
                payload=payload,
                raw_frame=frame_data,
                status=0,
                timestamp=time.time(),
            )
