"""Consumer boundary and fixed wire vectors, not an MCU behavior substitute."""
import pytest

from power_scope.core.contracts import (
    Capabilities, CommandPhase, CommandReceipt, DeviceIdentity, EffectState,
    Observation, ParameterDescriptor, Quality, require_read_memory_length,
)
from power_scope.core.cffi_loader import CRC16, DebugProtocol


def test_unknown_evidence_does_not_grant_permissions_or_success():
    assert not DeviceIdentity().artifacts_verified
    assert not Capabilities().supported_commands
    parameter = ParameterDescriptor("gain", "cfg.kp")
    assert not parameter.writable and not parameter.allowed_modes
    assert parameter.write_range is None and parameter.dtype is None
    receipt = CommandReceipt("intent", 1, phase=CommandPhase.ACKED)
    assert receipt.effect is EffectState.UNKNOWN
    assert Observation("gain", 1).quality is Quality.UNKNOWN


def test_read_memory_181_boundary_and_invalid_inputs():
    require_read_memory_length(1)
    require_read_memory_length(181)
    for invalid in (0, -1, 182, 192, 193, True, 1.5):
        with pytest.raises(ValueError):
            require_read_memory_length(invalid)


def test_raw_integer_precision_is_not_converted_to_float():
    value = 9007199254740993
    observation = Observation("counter", 2, raw_value=value)
    assert type(observation.raw_value) is int
    assert observation.raw_value == 9007199254740993


def test_crc_standard_check_and_fixed_request_vectors():
    assert CRC16.calc(b"123456789") == 0x4B37
    assert DebugProtocol.build_frame(7, 0x1234, 0, b"") == bytes.fromhex(
        "a55a010734120000000000008c05")
    assert DebugProtocol.build_frame(1, 0x1234, 0x20000000, b"\xb5") == bytes.fromhex(
        "a55a01013412000000200100b57f0d")


def test_fixed_nack_and_effective_period_vectors():
    nack = bytes.fromhex("a55a01ff3412040000b956")
    assert DebugProtocol.build_response(255, 0x1234, 4, b"") == nack
    assert DebugProtocol.parse_response(nack) == {
        "version": 1, "cmd": 255, "seq": 0x1234, "status": 4, "payload": b""}
    effective_period = bytes.fromhex("a55a010434120004001027000041e5")
    assert DebugProtocol.parse_response(effective_period)["payload"] == b"\x10\x27\x00\x00"
    with pytest.raises(ValueError, match="CRC"):
        DebugProtocol.parse_response(nack[:-1] + b"\x00")
    with pytest.raises(ValueError, match="truncated"):
        DebugProtocol.parse_response(effective_period[:-1])
