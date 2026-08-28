"""test_write_verify.py — 写后读回校验 (利用固件 g_uart_debug_scratch)

DebugService.write_and_verify: WRITE_MEM → READ_MEM → 逐字节比对，callback(ok, readback)。
"""
from __future__ import annotations

import struct
import pytest

from power_scope.core.debug_service import DebugService
from power_scope.core.cffi_loader import DebugProtocol


@pytest.fixture
def svc(qapp):
    sent = []
    s = DebugService(writer=sent.append)
    s._sent = sent
    return s


class TestWriteAndVerify:
    def test_write_then_readback_match_ok(self, svc):
        results = []
        svc.write_and_verify(0x20001F30, struct.pack("<I", 0x12345678), 4,
                             callback=lambda ok, rb: results.append((ok, rb)))
        # 1) 首帧为 WRITE_MEM
        w = DebugProtocol.parse_frame(svc._sent[0])
        assert w["cmd"] == DebugProtocol.CMD_WRITE_MEM
        assert w["address"] == 0x20001F30
        assert w["payload"] == struct.pack("<I", 0x12345678)
        # 2) 喂入写响应 OK → 触发读回
        svc.feed(DebugProtocol.build_response(DebugProtocol.CMD_WRITE_MEM, w["seq"], 0, b""))
        r = DebugProtocol.parse_frame(svc._sent[1])
        assert r["cmd"] == DebugProtocol.CMD_READ_MEM
        # 3) 喂入读响应（与写入一致）→ ok=True
        svc.feed(DebugProtocol.build_response(
            DebugProtocol.CMD_READ_MEM, r["seq"], 0, struct.pack("<I", 0x12345678)))
        assert results == [(True, struct.pack("<I", 0x12345678))]

    def test_readback_mismatch_fails(self, svc):
        results = []
        svc.write_and_verify(0x20001F30, struct.pack("<I", 0x12345678), 4,
                             callback=lambda ok, rb: results.append(ok))
        w = DebugProtocol.parse_frame(svc._sent[0])
        svc.feed(DebugProtocol.build_response(DebugProtocol.CMD_WRITE_MEM, w["seq"], 0, b""))
        r = DebugProtocol.parse_frame(svc._sent[1])
        svc.feed(DebugProtocol.build_response(
            DebugProtocol.CMD_READ_MEM, r["seq"], 0, struct.pack("<I", 0xDEADBEEF)))
        assert results == [False]

    def test_write_nack_fails_without_read(self, svc):
        results = []
        svc.write_and_verify(0x08000000, struct.pack("<I", 1), 4,
                             callback=lambda ok, rb: results.append(ok))
        w = DebugProtocol.parse_frame(svc._sent[0])
        # 写被拒（如只读区 status=6）
        svc.feed(DebugProtocol.build_response(DebugProtocol.CMD_WRITE_MEM, w["seq"], 6, b""))
        assert results == [False]
        assert len(svc._sent) == 1     # 未发起读回
