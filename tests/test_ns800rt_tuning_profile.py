"""NS800RT 调参 profile 必须映射到真实 ELF 的 PI 配置叶子。"""
from power_scope.config.device_profile import load_profile
from power_scope.debug.elf_parser import ELFParser, resolve_symbol_path


def test_all_tuning_loop_parameters_resolve_against_real_elf():
    profile = load_profile("power_scope/profiles/ns800rt_smoke.yaml")
    assert profile.tuning["loops"]
    parser = ELFParser(profile.elf_file)
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


def test_ns800rt_pi_bindings_keep_the_verified_leaf_addresses():
    profile = load_profile("power_scope/profiles/ns800rt_smoke.yaml")
    expected = {
        "inv_curr_freq_kp": 0x2000208C, "inv_curr_freq_ki": 0x20002090,
        "inv_curr_pri_kp": 0x2000209C, "inv_curr_pri_ki": 0x200020A0,
        "inv_curr_phase_kp": 0x200020AC, "inv_curr_phase_ki": 0x200020B0,
        "inv_volt_kp": 0x20002144, "inv_volt_ki": 0x20002148,
        "current_limit_kp": 0x20002060, "current_limit_ki": 0x20002064,
        "urms_kp": 0x200024B8, "urms_ki": 0x200024BC,
        "active_power_kp": 0x200013C8, "active_power_ki": 0x200013CC,
        "reactive_power_kp": 0x200021E0, "reactive_power_ki": 0x200021E4,
        "spll_kp": 0x200029D8, "spll_ki": 0x200029DC,
    }
    parser = ELFParser(profile.elf_file)
    lookup = {var.name: var for var in parser.parse_variables()}
    try:
        for binding_name, address in expected.items():
            binding = profile.find_var(binding_name)
            leaf = resolve_symbol_path(lookup, binding.elf_symbol)
            assert leaf.address == address, binding.elf_symbol
    finally:
        parser.close()


def test_ns800rt_safety_profile_has_no_placeholder_analog_limits():
    profile = load_profile("power_scope/profiles/ns800rt_smoke.yaml")
    safety = profile.tuning["safety"]
    assert safety.get("limits", {}) == {}
    fault = profile.find_var("fault_code")
    assert fault is not None and fault.update_rate > 0
