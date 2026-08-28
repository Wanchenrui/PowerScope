import struct

from power_scope.core.msg_service import (
    FRAME_START,
    MsgService,
    MsgStreamParser,
    build_msg_frame,
)


def test_msg_frame_is_big_endian_and_fragment_safe(qapp):
    frame = build_msg_frame(0x2108, [0x0000])
    assert frame == bytes.fromhex("EF EF 21 08 00 01 00 00")

    parser = MsgStreamParser()
    assert parser.feed(frame[:3]) == []
    frames = parser.feed(frame[3:])
    assert len(frames) == 1
    assert frames[0].start == FRAME_START
    assert frames[0].command == 0x2108
    assert frames[0].words == (0,)


def test_service_rejects_false_msg_marker_from_debug_stream(qapp):
    sent = []
    replies = []
    service = MsgService(writer=sent.append)
    service.request_read(0x2108, 1, replies.append)

    false_debug_payload = bytes.fromhex("A5 5A EF EF 12 34 00 01 AA BB")
    response = struct.pack(">HHHH", FRAME_START, 0x2108, 1, 2301)
    service.feed(false_debug_payload + response)

    assert len(sent) == 1
    assert replies == [{
        "cmd": 0x2108,
        "ok": True,
        "kind": "data",
        "words": (2301,),
        "raw": response,
    }]
