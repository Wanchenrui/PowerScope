"""Lossless, bounded codecs used by 25 us live waveform blocks.

The MCU selects a codec independently for every channel block.  All codecs
operate on the in-memory little-endian bit pattern; RAW is always available as
the fallback, so selecting a codec never changes a sampled value.
"""
from __future__ import annotations

from dataclasses import dataclass


CODEC_RAW = 0
CODEC_CONST = 1
CODEC_RLE = 2
CODEC_DELTA1 = 3
CODEC_DELTA2 = 4
CODEC_XOR = 5
CODEC_RICE_DELTA2 = 6
CODEC_ORDERED_FLOAT_RICE = 7

CODEC_NAMES = {
    CODEC_RAW: "RAW",
    CODEC_CONST: "CONST",
    CODEC_RLE: "RLE",
    CODEC_DELTA1: "DELTA1",
    CODEC_DELTA2: "DELTA2",
    CODEC_XOR: "XOR",
    CODEC_RICE_DELTA2: "RICE_DELTA2",
    CODEC_ORDERED_FLOAT_RICE: "ORDERED_FLOAT_RICE",
}

_FLOAT_TYPE_CODES = {7, 10}  # WAVE_TYPE_F32 / WAVE_TYPE_F64
_VALID_SIZES = {1, 2, 4, 8}


@dataclass(frozen=True)
class EncodedChannel:
    codec_id: int
    parameter: int
    payload: bytes

    @property
    def codec_name(self) -> str:
        return CODEC_NAMES.get(self.codec_id, f"UNKNOWN_{self.codec_id}")


def _check_raw(raw: bytes, value_size: int) -> int:
    if value_size not in _VALID_SIZES:
        raise ValueError("value_size 必须是 1/2/4/8")
    if not raw or len(raw) % value_size:
        raise ValueError("通道原始字节长度与 value_size 不匹配")
    return len(raw) // value_size


def _split_values(raw: bytes, value_size: int) -> list[int]:
    return [
        int.from_bytes(raw[offset:offset + value_size], "little")
        for offset in range(0, len(raw), value_size)
    ]


def _join_values(values, value_size: int) -> bytes:
    mask = (1 << (value_size * 8)) - 1
    return b"".join((int(value) & mask).to_bytes(value_size, "little")
                    for value in values)


def _signed_mod_delta(current: int, previous: int, bits: int) -> int:
    mask = (1 << bits) - 1
    delta = (current - previous) & mask
    sign = 1 << (bits - 1)
    return delta - (1 << bits) if delta & sign else delta


def _zigzag(value: int) -> int:
    return (value << 1) ^ (value >> 63)


def _unzigzag(value: int) -> int:
    return (value >> 1) ^ -(value & 1)


def _put_uleb(output: bytearray, value: int) -> None:
    value = int(value)
    if value < 0 or value > 0xFFFFFFFFFFFFFFFF:
        raise ValueError("ULEB128 数值超出 64 位")
    while value >= 0x80:
        output.append((value & 0x7F) | 0x80)
        value >>= 7
    output.append(value)


def _get_uleb(payload: bytes, offset: int) -> tuple[int, int]:
    value = 0
    shift = 0
    for _ in range(10):
        if offset >= len(payload):
            raise ValueError("ULEB128 数据被截断")
        byte = payload[offset]
        offset += 1
        if shift == 63 and (byte & 0x7E):
            raise ValueError("ULEB128 数值溢出")
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, offset
        shift += 7
    raise ValueError("ULEB128 长度超过 10 字节")


class _BitWriter:
    def __init__(self, limit: int):
        self.data = bytearray()
        self._current = 0
        self._used = 0
        self._limit = max(0, int(limit))

    def bit(self, value: int) -> None:
        if value & 1:
            self._current |= 1 << self._used
        self._used += 1
        if self._used == 8:
            self._flush_byte()

    def bits(self, value: int, count: int) -> None:
        for index in range(count):
            self.bit(value >> index)

    def _flush_byte(self) -> None:
        if len(self.data) >= self._limit:
            raise OverflowError
        self.data.append(self._current)
        self._current = 0
        self._used = 0

    def finish(self) -> bytes:
        if self._used:
            self._flush_byte()
        return bytes(self.data)


class _BitReader:
    def __init__(self, payload: bytes, offset: int):
        self._payload = payload
        self._bit = offset * 8

    def bit(self) -> int:
        if self._bit >= len(self._payload) * 8:
            raise ValueError("Rice 位流被截断")
        value = (self._payload[self._bit // 8] >> (self._bit & 7)) & 1
        self._bit += 1
        return value

    def bits(self, count: int) -> int:
        value = 0
        for index in range(count):
            value |= self.bit() << index
        return value

    def ensure_finished(self) -> None:
        """Only the encoder's zero padding may remain in the final byte."""
        byte_index, bit_index = divmod(self._bit, 8)
        if bit_index:
            if self._payload[byte_index] >> bit_index:
                raise ValueError("Rice 末字节填充位非零")
            byte_index += 1
        if byte_index != len(self._payload):
            raise ValueError("Rice 存在多余数据")


def _ordered_float(value: int, bits: int) -> int:
    mask = (1 << bits) - 1
    sign = 1 << (bits - 1)
    return (~value & mask) if value & sign else (value ^ sign)


def _unordered_float(value: int, bits: int) -> int:
    mask = (1 << bits) - 1
    sign = 1 << (bits - 1)
    return (value ^ sign) if value & sign else (~value & mask)


def _encode_const(values: list[int], value_size: int) -> bytes | None:
    if all(value == values[0] for value in values[1:]):
        return values[0].to_bytes(value_size, "little")
    return None


def _encode_rle(values: list[int], value_size: int) -> bytes:
    output = bytearray()
    index = 0
    while index < len(values):
        run = 1
        while (index + run < len(values) and run < 255 and
               values[index + run] == values[index]):
            run += 1
        output.append(run)
        output += values[index].to_bytes(value_size, "little")
        index += run
    return bytes(output)


def _encode_delta(values: list[int], value_size: int, order: int) -> bytes:
    bits = value_size * 8
    mask = (1 << bits) - 1
    output = bytearray(values[0].to_bytes(value_size, "little"))
    if len(values) == 1:
        return bytes(output)
    previous_delta = _signed_mod_delta(values[1], values[0], bits)
    _put_uleb(output, _zigzag(previous_delta))
    if order == 1:
        for index in range(2, len(values)):
            delta = _signed_mod_delta(values[index], values[index - 1], bits)
            _put_uleb(output, _zigzag(delta))
        return bytes(output)
    for index in range(2, len(values)):
        delta = _signed_mod_delta(values[index], values[index - 1], bits)
        delta2 = _signed_mod_delta(delta & mask, previous_delta & mask, bits)
        _put_uleb(output, _zigzag(delta2))
        previous_delta = delta
    return bytes(output)


def _encode_xor(values: list[int], value_size: int) -> bytes:
    output = bytearray(values[0].to_bytes(value_size, "little"))
    for previous, current in zip(values, values[1:]):
        _put_uleb(output, previous ^ current)
    return bytes(output)


def _rice_payload(values: list[int], value_size: int, k: int,
                  max_bytes: int) -> bytes | None:
    bits = value_size * 8
    mask = (1 << bits) - 1
    prefix = bytearray(values[0].to_bytes(value_size, "little"))
    if len(values) == 1:
        return bytes(prefix)
    previous_delta = _signed_mod_delta(values[1], values[0], bits)
    _put_uleb(prefix, _zigzag(previous_delta))
    if len(prefix) > max_bytes:
        return None
    writer = _BitWriter(max_bytes - len(prefix))
    try:
        for index in range(2, len(values)):
            delta = _signed_mod_delta(values[index], values[index - 1], bits)
            delta2 = _signed_mod_delta(delta & mask, previous_delta & mask, bits)
            code = _zigzag(delta2)
            quotient = code >> k
            if quotient > 2048:
                return None
            for _ in range(quotient):
                writer.bit(0)
            writer.bit(1)
            if k:
                writer.bits(code & ((1 << k) - 1), k)
            previous_delta = delta
        return bytes(prefix) + writer.finish()
    except OverflowError:
        return None


def _best_rice(values: list[int], value_size: int,
               max_bytes: int) -> tuple[int, bytes] | None:
    best = None
    for k in range(8):
        payload = _rice_payload(values, value_size, k, max_bytes)
        if payload is not None and (best is None or len(payload) < len(best[1])):
            best = (k, payload)
    return best


def encode_channel(raw: bytes, value_size: int, type_code: int = 0,
                   force_codec: int | None = None,
                   max_bytes: int | None = None) -> EncodedChannel:
    """Choose the shortest exact codec that fits ``max_bytes``.

    With no explicit limit, RAW is the hard upper bound.  The MCU uses a
    smaller limit for a large Live block: compressible 512-point blocks fit in
    one frame, while an incompressible block is retried with fewer points so a
    RAW payload remains available.
    """
    raw = bytes(raw)
    _check_raw(raw, value_size)
    limit = len(raw) if max_bytes is None else int(max_bytes)
    if limit <= 0:
        raise ValueError("max_bytes 必须大于 0")
    values = _split_values(raw, value_size)
    candidates: list[EncodedChannel] = [EncodedChannel(CODEC_RAW, 0, raw)]

    const = _encode_const(values, value_size)
    if const is not None:
        candidates.append(EncodedChannel(CODEC_CONST, 0, const))
    candidates.append(EncodedChannel(CODEC_RLE, 0,
                                     _encode_rle(values, value_size)))
    candidates.append(EncodedChannel(CODEC_DELTA1, 0,
                                     _encode_delta(values, value_size, 1)))
    candidates.append(EncodedChannel(CODEC_DELTA2, 0,
                                     _encode_delta(values, value_size, 2)))
    candidates.append(EncodedChannel(CODEC_XOR, 0,
                                     _encode_xor(values, value_size)))

    rice = _best_rice(values, value_size, limit)
    if rice is not None:
        candidates.append(EncodedChannel(CODEC_RICE_DELTA2, rice[0], rice[1]))

    if int(type_code) in _FLOAT_TYPE_CODES:
        ordered = [_ordered_float(value, value_size * 8) for value in values]
        rice = _best_rice(ordered, value_size, limit)
        if rice is not None:
            candidates.append(EncodedChannel(
                CODEC_ORDERED_FLOAT_RICE, rice[0], rice[1]))

    if max_bytes is not None:
        candidates = [item for item in candidates if len(item.payload) <= limit]
    if force_codec is not None:
        for candidate in candidates:
            if candidate.codec_id == force_codec:
                return candidate
        raise ValueError(f"编码器 {force_codec} 不适用于当前数据")
    if not candidates:
        raise ValueError("该块在 max_bytes 内没有可用的无损编码")

    priority = {
        CODEC_RAW: 0, CODEC_CONST: 1, CODEC_RLE: 2,
        CODEC_ORDERED_FLOAT_RICE: 3, CODEC_RICE_DELTA2: 4,
        CODEC_DELTA2: 5, CODEC_DELTA1: 6, CODEC_XOR: 7,
    }
    return min(candidates, key=lambda item: (len(item.payload),
                                             priority[item.codec_id]))


def _decode_delta(payload: bytes, value_size: int, sample_count: int,
                  order: int) -> list[int]:
    if len(payload) < value_size:
        raise ValueError("DELTA 首值被截断")
    bits = value_size * 8
    mask = (1 << bits) - 1
    values = [int.from_bytes(payload[:value_size], "little")]
    offset = value_size
    if sample_count == 1:
        if offset != len(payload):
            raise ValueError("DELTA 存在多余数据")
        return values
    code, offset = _get_uleb(payload, offset)
    previous_delta = _unzigzag(code)
    values.append((values[-1] + previous_delta) & mask)
    for _ in range(2, sample_count):
        code, offset = _get_uleb(payload, offset)
        encoded = _unzigzag(code)
        delta = encoded if order == 1 else previous_delta + encoded
        delta = _signed_mod_delta(delta & mask, 0, bits)
        values.append((values[-1] + delta) & mask)
        previous_delta = delta
    if offset != len(payload):
        raise ValueError("DELTA 存在多余数据")
    return values


def _decode_rice(payload: bytes, value_size: int, sample_count: int,
                 k: int) -> list[int]:
    if not 0 <= k <= 7 or len(payload) < value_size:
        raise ValueError("Rice 参数或首值无效")
    bits = value_size * 8
    mask = (1 << bits) - 1
    values = [int.from_bytes(payload[:value_size], "little")]
    offset = value_size
    if sample_count == 1:
        if offset != len(payload):
            raise ValueError("Rice 存在多余数据")
        return values
    code, offset = _get_uleb(payload, offset)
    previous_delta = _unzigzag(code)
    values.append((values[-1] + previous_delta) & mask)
    reader = _BitReader(payload, offset)
    for _ in range(2, sample_count):
        quotient = 0
        while not reader.bit():
            quotient += 1
            if quotient > 2048:
                raise ValueError("Rice 商异常")
        remainder = reader.bits(k) if k else 0
        delta2 = _unzigzag((quotient << k) | remainder)
        delta = _signed_mod_delta((previous_delta + delta2) & mask, 0, bits)
        values.append((values[-1] + delta) & mask)
        previous_delta = delta
    reader.ensure_finished()
    return values


def decode_channel(codec_id: int, parameter: int, payload: bytes,
                   value_size: int, sample_count: int,
                   type_code: int = 0) -> bytes:
    """Decode one channel block and reject truncated or contradictory input."""
    if value_size not in _VALID_SIZES or sample_count <= 0:
        raise ValueError("Live 通道宽度或点数无效")
    payload = bytes(payload)
    expected = value_size * sample_count
    if codec_id == CODEC_RAW:
        if len(payload) != expected:
            raise ValueError("RAW 长度不匹配")
        return payload
    if codec_id == CODEC_CONST:
        if len(payload) != value_size:
            raise ValueError("CONST 长度不匹配")
        return payload * sample_count
    if codec_id == CODEC_RLE:
        output = bytearray()
        offset = 0
        while offset < len(payload):
            if offset + 1 + value_size > len(payload):
                raise ValueError("RLE 数据被截断")
            run = payload[offset]
            value = payload[offset + 1:offset + 1 + value_size]
            if run == 0 or len(output) + run * value_size > expected:
                raise ValueError("RLE 游程无效")
            output += value * run
            offset += 1 + value_size
        if len(output) != expected:
            raise ValueError("RLE 点数不匹配")
        return bytes(output)
    if codec_id in (CODEC_DELTA1, CODEC_DELTA2):
        values = _decode_delta(payload, value_size, sample_count,
                               1 if codec_id == CODEC_DELTA1 else 2)
        return _join_values(values, value_size)
    if codec_id == CODEC_XOR:
        if len(payload) < value_size:
            raise ValueError("XOR 首值被截断")
        values = [int.from_bytes(payload[:value_size], "little")]
        offset = value_size
        for _ in range(1, sample_count):
            value, offset = _get_uleb(payload, offset)
            values.append(values[-1] ^ value)
        if offset != len(payload):
            raise ValueError("XOR 存在多余数据")
        return _join_values(values, value_size)
    if codec_id in (CODEC_RICE_DELTA2, CODEC_ORDERED_FLOAT_RICE):
        if codec_id == CODEC_ORDERED_FLOAT_RICE and int(type_code) not in _FLOAT_TYPE_CODES:
            raise ValueError("有序浮点编码器只能用于 float/double")
        values = _decode_rice(payload, value_size, sample_count, parameter)
        if codec_id == CODEC_ORDERED_FLOAT_RICE:
            values = [_unordered_float(value, value_size * 8) for value in values]
        return _join_values(values, value_size)
    raise ValueError(f"未知 Live 编码器: {codec_id}")


def bits_per_sample(encoded_bytes: int, sample_count: int) -> float:
    return (int(encoded_bytes) * 8.0 / int(sample_count)) if sample_count else 0.0
