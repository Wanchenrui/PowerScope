"""Strict scalar encoding for controlled parameter writes (little endian)."""
from dataclasses import dataclass
from fractions import Fraction
import math
import struct

from .contracts import ParameterDescriptor, TypeSource

_FORMATS = {"int8_t": "b", "uint8_t": "B", "int16_t": "h", "uint16_t": "H",
            "int32_t": "i", "uint32_t": "I", "int64_t": "q", "uint64_t": "Q",
            "float": "f", "double": "d", "bool": "?"}


@dataclass(frozen=True)
class EncodedParameter:
    data: bytes
    raw_value: int | float | bool


def scalar_format(parameter: ParameterDescriptor) -> str:
    if parameter.type_source not in (TypeSource.DWARF, TypeSource.DEVICE_PACK):
        raise ValueError("Unknown type provenance")
    fmt = _FORMATS.get(parameter.dtype)
    if fmt is None or parameter.byte_size != struct.calcsize(fmt):
        raise ValueError("Unsupported type or mismatched width")
    address = parameter.address
    if type(address) is not int or not 0 <= address <= 2**32 - parameter.byte_size:
        raise ValueError("Invalid address")
    if address % parameter.byte_size:
        raise ValueError("Unaligned scalar address")
    return "<" + fmt


def decode_parameter(parameter, data):
    fmt = scalar_format(parameter)
    if len(data) != parameter.byte_size:
        raise ValueError("Readback width mismatch")
    value = struct.unpack(fmt, data)[0]
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Non-finite readback")
    return value


def encode_parameter(parameter, value):
    fmt = scalar_format(parameter)
    if type(value) not in (int, float, bool) or not math.isfinite(value):
        raise ValueError("Requested value must be finite numeric")
    bounds = parameter.write_range
    if bounds is None or len(bounds) != 2 or not all(math.isfinite(v) for v in bounds):
        raise ValueError("Missing or invalid write range")
    if not bounds[0] <= value <= bounds[1]:
        raise ValueError("Requested value outside write range")
    if not math.isfinite(parameter.scale) or parameter.scale == 0 or not math.isfinite(parameter.offset):
        raise ValueError("Invalid scale/offset")
    if fmt[-1] in "fd":
        raw = (value - parameter.offset) / parameter.scale
    else:
        # Rational arithmetic preserves all integer bits through scale/offset.
        # Float metadata is interpreted as its exact represented value; no
        # tolerance can silently turn a fractional integer target into a write.
        raw = (Fraction(value) - Fraction(parameter.offset)) / Fraction(parameter.scale)
        if raw.denominator != 1:
            raise ValueError("Non-integral encoded value")
        raw = raw.numerator
        if fmt[-1] == "?" and raw not in (0, 1):
            raise ValueError("Boolean value must be 0 or 1")
    try:
        data = struct.pack(fmt, raw)
    except (struct.error, OverflowError) as exc:
        raise ValueError("Encoded value exceeds scalar width") from exc
    actual = decode_parameter(parameter, data)
    physical = actual * parameter.scale + parameter.offset
    if fmt[-1] not in "fd":
        physical = Fraction(actual) * Fraction(parameter.scale) + Fraction(parameter.offset)
    if not bounds[0] <= physical <= bounds[1]:
        raise ValueError("Rounded encoded value outside write range")
    return EncodedParameter(data, actual)
