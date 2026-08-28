"""Deterministic latency and timeout statistics for sustained MSG polling."""
import struct

import pytest

from power_scope.core.msg_service import FRAME_START, MsgService


def _response(command: int, value: int) -> bytes:
    return struct.pack(">HHHH", FRAME_START, command, 1, value)


def test_latency_percentiles_and_timeout_are_measured_not_inferred(qapp):
    now = [0.0]
    service = MsgService(writer=lambda _frame: None, timeout_s=0.1,
                         clock=lambda: now[0])

    for index, latency_ms in enumerate((5, 10, 15, 20)):
        replies = []
        service.request_read(0x2108, 1, replies.append)
        now[0] += latency_ms / 1000.0
        service.feed(_response(0x2108, index))
        assert replies[-1]["ok"] is True

    stats = service.latency_stats()
    assert stats["sample_count"] == 4
    assert stats["response_count"] == 4
    assert stats["mean_ms"] == pytest.approx(12.5)
    assert stats["p50_ms"] == pytest.approx(10.0)
    assert stats["p95_ms"] == pytest.approx(20.0)
    assert stats["p99_ms"] == pytest.approx(20.0)

    timeout = []
    service.request_read(0x2109, 1, timeout.append)
    now[0] += 0.101
    service.expire_pending()
    assert timeout[-1]["kind"] == "timeout"
    assert service.latency_stats()["timeout_count"] == 1

    service.reset_latency_stats()
    assert service.latency_stats()["sample_count"] == 0
    assert service.latency_stats()["timeout_count"] == 0
