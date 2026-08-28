"""设备配置系统测试"""
import os, sys, pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from power_scope.config.device_profile import DeviceProfile, load_profile, list_profiles

_PROFILES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "power_scope", "profiles")


class TestMicroinverterProfile:
    def test_load_microinverter(self):
        path = os.path.join(_PROFILES_DIR, "microinverter.yaml")
        p = load_profile(path)
        assert p.name == "光伏微逆变器 GTI-1000"
        assert p.device_type == "microinverter"
        assert p.theme == "solar"

    def test_variables(self):
        p = load_profile(os.path.join(_PROFILES_DIR, "microinverter.yaml"))
        assert len(p.variables) >= 10
        pv = p.find_var("pv_voltage")
        assert pv is not None
        assert pv.display_name == "PV电压"
        assert pv.unit == "V"
        assert pv.scale == 0.1
        assert pv.widget == "gauge"

    def test_control_buttons(self):
        p = load_profile(os.path.join(_PROFILES_DIR, "microinverter.yaml"))
        btn_ids = [b.id for b in p.control_buttons]
        assert "power_on" in btn_ids
        assert "power_off" in btn_ids
        assert "emergency_stop" in btn_ids
        power_off = next(b for b in p.control_buttons if b.id == "power_off")
        assert power_off.confirm == True
        assert power_off.color == "danger"

    def test_dashboard_layout(self):
        p = load_profile(os.path.join(_PROFILES_DIR, "microinverter.yaml"))
        assert len(p.dashboard) >= 5
        waveform = next(w for w in p.dashboard if w.type == "waveform")
        assert waveform.w == 12
        assert "id_current" in waveform.config.get("variables", [])


class TestESSProfile:
    def test_load_ess(self):
        p = load_profile(os.path.join(_PROFILES_DIR, "ess_storage.yaml"))
        assert p.name == "储能系统 ESS-5kWh"
        assert p.device_type == "storage"

    def test_mode_buttons(self):
        p = load_profile(os.path.join(_PROFILES_DIR, "ess_storage.yaml"))
        btn_ids = [b.id for b in p.control_buttons]
        assert "mode_grid" in btn_ids      # 并网
        assert "mode_offgrid" in btn_ids   # 离网
        assert "mode_charging" in btn_ids  # 充电
        assert "mode_discharging" in btn_ids  # 放电
        assert "mode_vsg" in btn_ids       # VSG

    def test_vsg_variables(self):
        p = load_profile(os.path.join(_PROFILES_DIR, "ess_storage.yaml"))
        vsg_j = p.find_var("vsg_virtual_inertia")
        assert vsg_j is not None
        assert vsg_j.display_name == "虚拟惯量J"
        vsg_d = p.find_var("vsg_damping")
        assert vsg_d.display_name == "阻尼系数D"


class TestProfileListing:
    def test_list_profiles(self):
        profiles = list_profiles()
        assert len(profiles) >= 2
        names = [os.path.basename(p[1]) for p in profiles]
        assert any("microinverter" in n for n in names)
        assert any("ess" in n for n in names)


class TestProfileRoundtrip:
    def test_save_and_reload(self, tmp_path):
        p = load_profile(os.path.join(_PROFILES_DIR, "microinverter.yaml"))
        out = tmp_path / "test_profile.yaml"
        p.to_yaml(str(out))
        p2 = load_profile(str(out))
        assert p2.name == p.name
        assert p2.device_type == p.device_type
        assert len(p2.variables) == len(p.variables)
        assert len(p2.control_buttons) == len(p.control_buttons)
