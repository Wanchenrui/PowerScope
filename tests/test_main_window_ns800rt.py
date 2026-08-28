"""test_main_window_ns800rt.py — NS800RT 联调相关 MainWindow 修复

  F2: 工具栏连接拆分 "COMx - 描述" 串
  F3: 断开前先发 STOP_STREAM（transport 仍打开）
  F6: 流启动按 SET_SAMPLE / START_STREAM ACK 串行化
"""
from __future__ import annotations

import pytest

from power_scope.config.device_profile import DeviceProfile, VarBinding


def _mw(qapp, profile=None):
    from power_scope.ui.main_window import MainWindow
    return MainWindow(profile or DeviceProfile(name="t", device_type="x", version="1"))


def _fake_serial_connected(mw):
    """让 SessionController 处于“串口已连接”状态（不真正开端口），以便测试采样下发。"""
    from power_scope.transport import SerialTransport
    mw._session._transport = SerialTransport("COM_TEST")
    mw._session._connect_signals()
    mw._session._state = "connected"


class TestToolbarConnect:
    def test_strips_com_description(self, qapp, monkeypatch):
        mw = _mw(qapp)
        mw._serial_view._sim_check.setChecked(False)
        mw._serial_view._port_combo.setEditText("COM3 - USB Serial Port")
        mw._serial_view._baud_combo.setCurrentText("115200")
        captured = {}
        monkeypatch.setattr(mw._session, "connect_serial",
                            lambda **kw: captured.update(kw))
        mw._on_connect()
        assert captured.get("port") == "COM3"
        assert captured.get("baudrate") == 115200


class TestDisconnectStopsStreamFirst:
    def test_stop_before_close(self, qapp):
        mw = _mw(qapp)
        calls = []
        mw._streaming = True
        mw._debug.stop_stream = lambda lid, callback=None: calls.append("stop")
        mw._session.disconnect = lambda: calls.append("disconnect")
        mw._on_disconnect()
        assert calls == ["stop", "disconnect"]


class TestCloseEventReleasesPort:
    def test_close_disconnects_session(self, qapp):
        mw = _mw(qapp)
        mw._session.connect_mock()
        assert mw._session.is_connected is True
        mw.close()
        assert mw._session.is_connected is False

    def test_close_stops_streaming(self, qapp):
        mw = _mw(qapp)
        stopped = []
        mw._streaming = True
        mw._debug.stop_stream = lambda lid, callback=None: stopped.append(lid)
        mw.close()
        assert stopped == [mw._stream_list_id]


    def test_close_stops_owned_sim_timer_immediately(self, qapp):
        from tests.conftest import pump_events

        mw = _mw(qapp)
        mw._session.connect_mock()
        pump_events()
        assert mw._sim_timer.isActive()
        assert mw._sim_timer.parent() is mw
        mw.close()
        assert not mw._sim_timer.isActive()

class TestScopeStreamManager:
    def _mw_syms(self, qapp):
        from power_scope.debug.elf_parser import ElfVariable
        prof = DeviceProfile(
            name="t", device_type="x", version="1",
            variables=[VarBinding(name="v", elf_symbol="X", update_rate=20)])
        mw = _mw(qapp, prof)
        mw._symbols = {
            "X": ElfVariable("X", 0x20000000, 4, "uint32_t"),
            "g_raw": ElfVariable("g_raw", 0x20000010, 2, "uint16_t"),
        }
        return mw

    def test_scope_tab_present(self, qapp):
        mw = _mw(qapp)
        assert hasattr(mw, "_scope")
        tabs = [mw._tabs.tabText(i) for i in range(mw._tabs.count())]
        assert "波形" in tabs

    def test_add_profile_var_channel_resolves(self, qapp):
        mw = self._mw_syms(qapp)
        mw._on_scope_channels_added(["v"])
        assert "v" in mw._extra_channels
        assert mw._extra_channels["v"].address == 0x20000000

    def test_add_raw_symbol_channel(self, qapp):
        mw = self._mw_syms(qapp)
        mw._on_scope_channels_added(["g_raw"])
        ch = mw._extra_channels.get("g_raw")
        assert ch is not None and ch.address == 0x20000010 and ch.size == 2

    def test_remove_extra_channel(self, qapp):
        mw = self._mw_syms(qapp)
        mw._on_scope_channels_added(["g_raw"])
        mw._on_scope_channels_removed(["g_raw"])
        assert "g_raw" not in mw._extra_channels

    def test_unresolvable_channel_ignored(self, qapp):
        mw = self._mw_syms(qapp)
        mw._on_scope_channels_added(["does_not_exist"])
        assert "does_not_exist" not in mw._extra_channels

    def test_inspector_plot_adds_extra_and_scope(self, qapp):
        mw = _mw(qapp)
        specs = [{"name": "g_x", "address": 0x20000000, "size": 4, "type_name": "uint32_t"}]
        mw._on_inspector_plot(specs)
        assert "g_x" in mw._extra_channels
        assert "g_x" in mw._scope.plotted_channels()

    def test_scope_channels_do_not_join_slow_stream_set(self, qapp):
        from power_scope.core.debug_service import SampleChannel
        mw = self._mw_syms(qapp)
        mw._profile_channels = {"v": SampleChannel("v", 0x20000000, 4, "uint32_t")}
        mw._on_scope_channels_added(["g_raw"])
        assert set(mw._stream_set()) == {"v"}
        assert set(mw._stream.scope_set()) == {"g_raw"}


class TestScopePlotsLiveData:
    def test_sim_data_reaches_scope_plot(self, qapp):
        from tests.conftest import pump_events
        prof = DeviceProfile(
            name="t", device_type="x", version="1",
            variables=[VarBinding(name="voltage", elf_symbol="v", unit="V",
                                  scale=1.0, update_rate=20)])
        mw = _mw(qapp, prof)
        mw._scope.add_channels_external(["voltage"])   # 用户在波形页添加该通道
        mw._session.connect_mock()
        for _ in range(5):
            mw._on_sim_tick()
            pump_events()
        assert mw._scope._plot.sample_count("voltage") > 0


class TestStreamingAckGating:
    def test_streaming_set_only_after_both_acks(self, qapp):
        from power_scope.debug.elf_parser import ElfVariable
        prof = DeviceProfile(
            name="t", device_type="x", version="1",
            variables=[VarBinding(name="v", elf_symbol="X", update_rate=20)])
        mw = _mw(qapp, prof)
        mw._symbols = {"X": ElfVariable("X", 0x20000000, 4, "uint32_t")}
        cbs = {}
        mw._debug.setup_sample_list = lambda lid, per, ch, callback=None: cbs.__setitem__("setup", callback)
        mw._debug.start_stream = lambda lid, callback=None: cbs.__setitem__("start", callback)

        _fake_serial_connected(mw)
        mw._start_streaming()
        assert "setup" in cbs and mw._streaming is False     # 未确认前不置位
        cbs["setup"]({"status": 0})                           # SET_SAMPLE ACK
        assert "start" in cbs and mw._streaming is False
        cbs["start"]({"status": 0})                           # START_STREAM ACK
        assert mw._streaming is True

    def test_nack_does_not_start_streaming(self, qapp):
        from power_scope.debug.elf_parser import ElfVariable
        prof = DeviceProfile(
            name="t", device_type="x", version="1",
            variables=[VarBinding(name="v", elf_symbol="X", update_rate=20)])
        mw = _mw(qapp, prof)
        mw._symbols = {"X": ElfVariable("X", 0x20000000, 4, "uint32_t")}
        cbs = {}
        mw._debug.setup_sample_list = lambda lid, per, ch, callback=None: cbs.__setitem__("setup", callback)
        mw._debug.start_stream = lambda lid, callback=None: cbs.__setitem__("start", callback)
        _fake_serial_connected(mw)
        mw._start_streaming()
        cbs["setup"]({"status": 4})        # SET_SAMPLE NACK
        assert "start" not in cbs and mw._streaming is False



def test_start_stream_warns_when_safety_monitor_is_not_streamed(qapp):
    from power_scope.debug.elf_parser import ElfVariable
    prof = DeviceProfile(
        name="t", device_type="x", version="1",
        variables=[
            VarBinding(name="fault", elf_symbol="FAULT", update_rate=20),
            VarBinding(name="not_streamed", elf_symbol="MON", update_rate=0),
        ],
        tuning={"safety": {
            "fault_vars": ["fault"],
            "limits": {"not_streamed": [0, 1]},
        }},
    )
    mw = _mw(qapp, prof)
    mw._symbols = {
        "FAULT": ElfVariable("FAULT", 0x20000000, 2, "uint16_t"),
        "MON": ElfVariable("MON", 0x20000004, 4, "float"),
    }
    messages = []
    mw._log_status = messages.append
    mw._debug.setup_sample_list = lambda *args, **kwargs: 1
    _fake_serial_connected(mw)
    mw._start_streaming()

    assert any("安全监测变量未进入流" in message and "not_streamed" in message
               for message in messages)


def test_serial_connect_auto_loads_profile_elf_without_duplicate_start(qapp, monkeypatch):
    from power_scope.core.event_bus import ConnectionStateEvent
    prof = DeviceProfile(
        name="t", device_type="x", version="1", elf_file="D:/firmware/test.elf")
    mw = _mw(qapp, prof)
    loaded = []
    starts = []
    monkeypatch.setattr("power_scope.ui.main_window.os.path.exists", lambda path: True)
    mw._var_view.load_elf = lambda path, show_error=True: loaded.append(path) or True
    mw._start_streaming = lambda: starts.append(True)

    mw._on_connection_state(ConnectionStateEvent(
        state="connected", transport_type="serial", info="COM3"))

    assert loaded == ["D:/firmware/test.elf"]
    assert starts == []
