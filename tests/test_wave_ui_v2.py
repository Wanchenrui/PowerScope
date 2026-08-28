import json

from power_scope.config.device_profile import DeviceProfile
from power_scope.core.debug_service import SampleChannel, WAVE_MODE_TRIGGERED
from power_scope.debug.elf_parser import ElfVariable


def _window(qapp):
    from power_scope.ui.main_window import MainWindow

    return MainWindow(DeviceProfile(name="wave-test", device_type="x", version="1"))


def _mark_serial_connected(window):
    from power_scope.transport import SerialTransport

    window._session._transport = SerialTransport("COM_TEST")
    window._session._connect_signals()
    window._session._state = "connected"


def test_trigger_ratio_is_preserved_when_128k_buffer_clamps_points(qapp):
    window = _window(qapp)
    names = [f"v{index}" for index in range(16)]
    window._symbols = {
        name: ElfVariable(name, 0x20001000 + index * 4, 4, "uint32_t")
        for index, name in enumerate(names)
    }
    window._scope.plotted_channels = lambda: names
    _mark_serial_connected(window)
    call = {}

    def configure(channels, points, **options):
        call.update(channels=channels, points=points, options=options)
        return 1

    window._debug.configure_wave = configure
    window._on_wave_record_requested(
        32768, 1, WAVE_MODE_TRIGGERED, pretrigger_points=16384)

    assert call["points"] == 2048
    assert call["options"]["pretrigger_points"] == 1024
    assert call["options"]["posttrigger_points"] == 1024
    window.close()


def test_csv_export_writes_exact_raw_and_self_describing_sidecars(qapp, tmp_path):
    window = _window(qapp)
    channel = SampleChannel(
        "counter64", 0x20101000, 8, "uint64_t",
        scale=0.5, offset=2.0, unit="count",
        sequence_address=0x20100020)
    window._last_wave_capture = {
        "raw": bytes.fromhex("01000000000000000200000000000000"),
        "channels": [channel],
        "tap_id": 1,
        "period_us": 25,
        "points": 2,
        "capture_id": 9,
        "mode": WAVE_MODE_TRIGGERED,
        "trigger_index": 1,
        "diagnostics": {"capture_isr_max_cycles": 120},
    }
    messages = []
    window._log_status = messages.append
    csv_path = tmp_path / "capture.csv"
    csv_path.write_text("time,counter64\n", encoding="utf-8")

    window._on_scope_export_completed(str(csv_path))

    assert (tmp_path / "capture.wave.bin").read_bytes() == window._last_wave_capture["raw"]
    metadata = json.loads(
        (tmp_path / "capture.wave.json").read_text(encoding="utf-8"))
    assert metadata["tap_id"] == 1
    assert metadata["period_us"] == 25
    assert metadata["trigger_index"] == 1
    assert metadata["channels"][0] == {
        "name": "counter64",
        "address": 0x20101000,
        "size": 8,
        "type_name": "uint64_t",
        "scale": 0.5,
        "offset": 2.0,
        "unit": "count",
        "sequence_address": 0x20100020,
    }
    assert messages and "原始录波" in messages[-1]
    window.close()


def test_live_blocks_are_ignored_after_live_session_stops(qapp):
    from power_scope.ui.scope_view import ScopeView

    class PlotSpy:
        def __init__(self):
            self.calls = []

        @staticmethod
        def has_channel(_name):
            return True

        def add_samples(self, *args):
            self.calls.append(args)

    view = ScopeView()
    spy = PlotSpy()
    view._plot = spy
    block = {"name": "v", "timestamps": [0.0], "phys_values": [1.0]}

    view._on_live_block(block)
    assert spy.calls == []
    view.set_live_status("running", True)
    view._on_live_block(block)
    assert len(spy.calls) == 1
    view.set_live_status("stopped", False)
    view._on_live_block(block)
    assert len(spy.calls) == 1


def test_inspector_member_reaches_recorder_config_from_record_button(qapp):
    window = _window(qapp)
    _mark_serial_connected(window)
    call = {}

    def configure(channels, points, **options):
        call.update(channels=channels, points=points, options=options)
        return 1

    window._debug.configure_wave = configure
    window._on_inspector_plot([{
        "name": "g_adObjF.uout",
        "address": 0x200024BC,
        "size": 4,
        "type_name": "float",
    }])

    window._scope._record_btn.click()

    assert call["channels"][0].name == "g_adObjF.uout"
    assert call["channels"][0].address == 0x200024BC
    assert call["channels"][0].type_name == "float"
    window.close()
