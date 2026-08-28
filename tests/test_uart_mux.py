from power_scope.core.cffi_loader import DebugProtocol
from power_scope.core.debug_service import DebugService
from power_scope.core.msg_service import MsgService, build_msg_frame


def test_debug_and_msg_services_parse_the_same_interleaved_uart_bytes(qapp):
    sent = []
    debug = DebugService(writer=sent.append)
    msg = MsgService(writer=sent.append)
    debug_result = []
    msg_result = []

    debug_seq = debug.get_info(callback=debug_result.append)
    msg.request_read(0x2108, 1, callback=msg_result.append)

    # Include a coincidental MSG marker for the pending command in Debug data.
    # Its impossible word count must be rejected without consuming the real MSG.
    info = bytearray(94)
    info[:11] = b"NS800RT5039"
    info[20:26] = b"\xEF\xEF\x21\x08\xFF\xFF"
    incoming = (
        DebugProtocol.build_response(
            DebugProtocol.CMD_GET_INFO, debug_seq, 0, bytes(info))
        + build_msg_frame(0x2108, [2300])
    )

    for offset in range(0, len(incoming), 7):
        chunk = incoming[offset:offset + 7]
        debug.feed(chunk)
        msg.feed(chunk)

    assert debug_result and debug_result[0]["status"] == 0
    assert msg_result == [{
        "cmd": 0x2108,
        "ok": True,
        "kind": "data",
        "words": (2300,),
        "raw": build_msg_frame(0x2108, [2300]),
    }]
    assert msg.latency_stats()["response_count"] == 1
