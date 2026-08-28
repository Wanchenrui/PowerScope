"""应用默认 profile 选择必须优先服务 NS800RT 真机。"""
from power_scope.main import _select_profile_path


def test_ns800rt_profile_has_highest_default_priority():
    profiles = [
        ("builtin", "profiles/microinverter.yaml"),
        ("builtin", "profiles/ns800rt_smoke.yaml"),
        ("builtin", "profiles/ess_storage.yaml"),
    ]
    assert _select_profile_path(profiles, ["app.py"]).endswith("ns800rt_smoke.yaml")


def test_explicit_existing_profile_overrides_default(tmp_path):
    explicit = tmp_path / "custom.yaml"
    explicit.write_text("name: custom", encoding="utf-8")
    profiles = [("builtin", "profiles/ns800rt_smoke.yaml")]
    assert _select_profile_path(
        profiles, ["app.py", str(explicit)]) == str(explicit)
