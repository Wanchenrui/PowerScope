"""Golden round trips for every lossless MCU/host waveform codec."""
import struct

import pytest

from power_scope.core.wave_codec import (
    CODEC_CONST,
    CODEC_DELTA1,
    CODEC_DELTA2,
    CODEC_ORDERED_FLOAT_RICE,
    CODEC_RAW,
    CODEC_RICE_DELTA2,
    CODEC_RLE,
    CODEC_XOR,
    decode_channel,
    encode_channel,
)


@pytest.mark.parametrize("size,values", [
    (1, [250, 251, 252, 1, 2, 3, 3, 3]),
    (2, [65530, 65531, 0, 1, 2, 10, 20, 30]),
    (4, [0xFFFFFFF0, 0xFFFFFFF1, 0, 1, 3, 6, 10, 15]),
    (8, [0xFFFFFFFFFFFFFFF0, 0, 1, 3, 6, 10, 15, 21]),
])
@pytest.mark.parametrize("codec", [
    CODEC_RAW, CODEC_RLE, CODEC_DELTA1, CODEC_DELTA2,
    CODEC_XOR, CODEC_RICE_DELTA2,
])
def test_integer_codec_round_trip(size, values, codec):
    raw = b"".join(value.to_bytes(size, "little") for value in values)
    encoded = encode_channel(raw, size, force_codec=codec)
    assert decode_channel(encoded.codec_id, encoded.parameter, encoded.payload,
                          size, len(values)) == raw


def test_const_and_rle_are_selected_when_shorter_than_raw():
    constant = struct.pack("<32H", *([77] * 32))
    assert encode_channel(constant, 2).codec_id == CODEC_CONST

    runs = struct.pack("<24H", *([1] * 8 + [2] * 8 + [3] * 8))
    encoded = encode_channel(runs, 2, force_codec=CODEC_RLE)
    assert len(encoded.payload) < len(runs)
    assert decode_channel(encoded.codec_id, 0, encoded.payload, 2, 24) == runs


def test_float_ordered_rice_preserves_exact_ieee_bits():
    bits = [
        0x4395FFF8, 0x4395FFFA, 0x4395FFFC, 0x4395FFFE,
        0x43960000, 0x43960002, 0x43960004, 0x43960006,
    ]
    raw = struct.pack("<8I", *bits)
    encoded = encode_channel(
        raw, 4, type_code=7, force_codec=CODEC_ORDERED_FLOAT_RICE)
    restored = decode_channel(
        encoded.codec_id, encoded.parameter, encoded.payload, 4, len(bits), 7)
    assert restored == raw


def test_best_encoder_never_exceeds_raw_and_ramp_compresses():
    raw = struct.pack("<32I", *range(1000, 1032))
    encoded = encode_channel(raw, 4)
    assert len(encoded.payload) <= len(raw)
    assert encoded.codec_id != CODEC_RAW


def test_large_live_block_uses_compression_and_raw_fallback_can_shrink():
    smooth = struct.pack("<512H", *range(512))
    encoded = encode_channel(smooth, 2, max_bytes=106)
    assert len(encoded.payload) <= 106
    assert decode_channel(encoded.codec_id, encoded.parameter, encoded.payload,
                          2, 512) == smooth

    noisy = bytes(range(256)) * 2
    with pytest.raises(ValueError, match="没有可用"):
        encode_channel(noisy, 1, max_bytes=16)
    fallback = encode_channel(
        noisy[:16], 1, force_codec=CODEC_RAW, max_bytes=16)
    assert fallback.codec_id == CODEC_RAW
    assert decode_channel(fallback.codec_id, fallback.parameter,
                          fallback.payload, 1, 16) == noisy[:16]


def test_decoder_rejects_malformed_payloads():
    with pytest.raises(ValueError, match="RAW"):
        decode_channel(CODEC_RAW, 0, b"\x00", 2, 2)
    with pytest.raises(ValueError, match="RLE"):
        decode_channel(CODEC_RLE, 0, b"\x00\x01\x00", 2, 1)
    with pytest.raises(ValueError, match="截断"):
        decode_channel(CODEC_DELTA1, 0, b"\x00\x00\x80", 2, 2)
    with pytest.raises(ValueError, match="多余"):
        decode_channel(CODEC_RICE_DELTA2, 0, b"\x01\x02\x00", 1, 2)
    with pytest.raises(ValueError, match="填充"):
        decode_channel(CODEC_RICE_DELTA2, 0, b"\x01\x02\x81", 1, 3)
