import struct

from power_scope.core.debug_service import DebugService


def _device_payload(length=94):
    payload = bytearray(length)
    payload[:11] = b"NS800RT5039"
    struct.pack_into("<IIH", payload, 32, 240_000_000, 0x12345678, 2)
    payload[42:58] = b"20260827-wave-v2"
    if length >= 94:
        struct.pack_into(
            "<IIIIIIII", payload, 58,
            3, 4, 5, 6, 7, 8, 0xFF, 128 * 1024)
        struct.pack_into("<HBB", payload, 90, 512, 16, 10)
    return bytes(payload)


def test_parse_device_info_v2_diagnostics_and_capabilities():
    info = DebugService.parse_device_info(_device_payload())

    assert info == {
        "model": "NS800RT5039",
        "cpu_freq_hz": 240_000_000,
        "elf_crc": 0x12345678,
        "protocol_ver": 2,
        "fw_version": "20260827-wave-v2",
        "stream_ring_drops": 3,
        "tx_busy_retries": 4,
        "tx_recovery_count": 5,
        "last_init_error": 6,
        "stim1_max_cycles": 7,
        "stim3_max_cycles": 8,
        "feature_flags": 0xFF,
        "wave_buffer_bytes": 128 * 1024,
        "max_wave_block_points": 512,
        "max_wave_channels": 16,
        "max_wave_descriptor_bytes": 10,
    }


def test_parse_device_info_keeps_short_legacy_prefix_compatible():
    info = DebugService.parse_device_info(_device_payload(58))

    assert info["model"] == "NS800RT5039"
    assert info["fw_version"] == "20260827-wave-v2"
    assert "feature_flags" not in info


def test_parse_device_info_rejects_truncated_prefix():
    assert DebugService.parse_device_info(b"\x00" * 43) == {}
