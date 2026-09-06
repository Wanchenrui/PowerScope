"""T09 real NS5039 parser plus actual platform runtime gate (no control library)."""
from pathlib import Path
import os
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]

def test_t09_production_runtime_gate():
    fw_arg = os.environ.get("POWERSCOPE_TEST_FW")
    cc_arg = os.environ.get("POWERSCOPE_TEST_HOST_CC")
    if not fw_arg or not cc_arg:
        pytest.skip("set POWERSCOPE_TEST_FW and POWERSCOPE_TEST_HOST_CC explicitly")
    fw, cc = Path(fw_arg), Path(cc_arg)
    output = ROOT / "build/t09-runtime.exe"
    command = [str(cc), "-std=c11", "-Wall", "-Wextra", "-Werror",
               "-Wno-error=unused-but-set-variable", "-Itests/firmware_ns5039",
               f"-I{fw}/user/include", f"-I{fw}/user/source", f"-I{fw}/ns800rt/common",
               "-include", "tests/firmware_ns5039/address_seam.h",
               "tests/firmware_ns5039/t09_driver.c", str(fw / "user/source/wave_codec.c"),
               "-o", str(output)]
    build = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    assert build.returncode == 0, build.stdout + build.stderr
    result = subprocess.run([str(output)], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "T09 production runtime policy passed" in result.stdout
    print(result.stdout)
