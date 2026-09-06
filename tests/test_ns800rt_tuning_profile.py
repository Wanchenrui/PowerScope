"""NS800RT 调参 profile 必须映射到真实 ELF 的 PI 配置叶子。"""
import hashlib
import json
from pathlib import Path

import pytest

from power_scope.config.device_profile import load_profile
from power_scope.debug.elf_parser import ELFParser, resolve_symbol_path


def test_all_tuning_loop_parameters_resolve_against_real_elf(firmware_elf):
    profile = load_profile("power_scope/profiles/ns800rt_smoke.yaml")
    assert profile.tuning["loops"]
    parser = ELFParser(firmware_elf)
    lookup = {var.name: var for var in parser.parse_variables()}
    try:
        for loop in profile.tuning["loops"]:
            assert loop["params"].get("Kd") is None
            for key in ("Kp", "Ki"):
                binding_name = loop["params"][key]
                binding = profile.find_var(binding_name)
                assert binding is not None, (loop["id"], key)
                leaf = resolve_symbol_path(lookup, binding.elf_symbol)
                assert leaf is not None, binding.elf_symbol
                assert leaf.type_name == "float" and leaf.size == 4
        fault = profile.find_var("fault_code")
        leaf = resolve_symbol_path(lookup, fault.elf_symbol)
        assert leaf is not None and leaf.size == 2
    finally:
        parser.close()


def test_ns800rt_pi_bindings_keep_the_verified_leaf_addresses(firmware_elf):
    profile = load_profile("power_scope/profiles/ns800rt_smoke.yaml")
    oracle = json.loads((Path(__file__).parent / 'fixtures/c01_20260821_addresses.json').read_text())
    digest = hashlib.sha256(Path(firmware_elf).read_bytes()).hexdigest()
    if digest != oracle['elf_sha256']:
        pytest.skip(f'No independently verified fixed-address oracle for ELF SHA256 {digest}')
    expected = oracle['addresses']
    parser = ELFParser(firmware_elf)
    lookup = {var.name: var for var in parser.parse_variables()}
    try:
        for binding_name, address in expected.items():
            binding = profile.find_var(binding_name)
            leaf = resolve_symbol_path(lookup, binding.elf_symbol)
            assert leaf.address == int(address, 16), binding.elf_symbol
    finally:
        parser.close()


def test_ns800rt_safety_profile_has_no_placeholder_analog_limits():
    profile = load_profile("power_scope/profiles/ns800rt_smoke.yaml")
    safety = profile.tuning["safety"]
    assert safety.get("limits", {}) == {}
    fault = profile.find_var("fault_code")
    assert fault is not None and fault.update_rate > 0
