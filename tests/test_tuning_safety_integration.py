"""调参页 profile 映射与安全事务接入。"""
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QMessageBox

from power_scope.config.device_profile import DeviceProfile, VarBinding
from power_scope.core.debug_service import SampleChannel
from power_scope.ui.tuning_view import TuningView


class FakeSafety(QObject):
    state_changed = Signal(str)
    event = Signal(str, str)

    def __init__(self):
        super().__init__()
        self.begins = []
        self.confirms = 0
        self.reverts = 0
        self.clears = 0

    def begin(self, params):
        self.begins.append(params)
        return True

    def confirm(self):
        self.confirms += 1

    def revert(self):
        self.reverts += 1

    def clear_safe_stop(self):
        self.clears += 1


def profile():
    return DeviceProfile(
        name="test", device_type="custom", version="1",
        variables=[
            VarBinding("loop_kp", "cfg.kp", min_val=-10, max_val=0, precision=5),
            VarBinding("loop_ki", "cfg.kiTc", min_val=-1, max_val=1, precision=6),
        ],
        tuning={"loops": [{
            "id": "loop", "label": "真实 PI 环",
            "params": {"Kp": "loop_kp", "Ki": "loop_ki", "Kd": None},
        }]},
    )


def resolver(name):
    address = {"loop_kp": 0x20000100, "loop_ki": 0x20000104}.get(name)
    return SampleChannel(name, address, 4, "float") if address else None


def test_profile_drives_loop_and_disables_unmapped_kd(qapp):
    view = TuningView(profile())
    assert view._loop_combo.currentText() == "真实 PI 环"
    assert not view._kd_input.isEnabled()
    assert view._kp_input.minimum() == -10
    assert view._kp_input.maximum() == 0
    view.close()


def test_apply_starts_one_atomic_safety_transaction(qapp, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    view = TuningView(profile())
    safety = FakeSafety()
    view.set_safety_controller(safety)
    view.set_channel_resolver(resolver)
    view.set_connected(True)
    view._kp_input.setValue(-2.0)
    view._ki_input.setValue(0.25)
    view._on_apply()

    assert len(safety.begins) == 1
    params = safety.begins[0]
    assert [item[0] for item in params] == ["loop_kp", "loop_ki"]
    assert [item[1].address for item in params] == [0x20000100, 0x20000104]
    view.close()


def test_state_buttons_delegate_to_safety_controller(qapp):
    view = TuningView(profile())
    safety = FakeSafety()
    view.set_safety_controller(safety)

    safety.state_changed.emit("MONITORING")
    assert view._confirm_btn.isEnabled()
    assert view._revert_btn.isEnabled()
    view._confirm_btn.click()
    view._revert_btn.click()

    safety.state_changed.emit("SAFE_STOP")
    assert not view._clear_safe_btn.isHidden()
    view._clear_safe_btn.click()
    assert (safety.confirms, safety.reverts, safety.clears) == (1, 1, 1)
    view.close()



def test_kitc_mapping_is_named_explicitly_in_ui(qapp):
    view = TuningView(profile())
    assert "kiTc" in view._ki_label.text()
    assert "原值" in view._ki_label.text()
    view.close()
