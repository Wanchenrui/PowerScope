"""Compare native C layout with the actual ctypes declarations."""
import ctypes
from pathlib import Path
import subprocess

import pytest


def test_compiled_native_abi():
    root = Path(__file__).resolve().parents[1]
    probe = root / 'build/native/native_abi_probe.exe'
    if not probe.exists():
        pytest.skip('Run scripts/build-native.ps1 -Install to build native ABI probe')
    from power_scope.core import cffi_loader as native

    values = dict(line.split('=') for line in subprocess.check_output(
        [str(probe)], text=True).splitlines())
    types = {
        'modbus_request_t': native._ModbusRequest,
        'modbus_response_t': native._ModbusResponse,
        'dbg_frame_t': native._DbgFrame,
        'pointer': ctypes.c_void_p,
    }
    for key, value in values.items():
        type_name, field = key.split('.')
        actual = (ctypes.sizeof(types[type_name]) if field == 'size'
                  else getattr(types[type_name], field).offset)
        assert actual == int(value), key
    assert native.lib.pc_get_version() == b'PowerScope Core v0.1.0'
    assert native.CRC16.calc(b'123456789') == 0x4B37
