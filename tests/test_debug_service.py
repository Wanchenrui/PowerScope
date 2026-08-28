"""test_debug_service.py — DebugService 单元测试 (P0 数据闭环)

验证 DebugService 把真实协议帧转成 UI 可用的数据：
  1. STREAM_DATA 帧 → 按采样列表布局解码 → 逐变量 publish var/updated（核心修复）
  2. 帧可跨多个字节块拆分到达（真实 UART 场景）
  3. 响应帧按 seq 匹配回挂起的请求回调
  4. 命令帧（SET_SAMPLE / READ_MEM）构造正确、可被协议层反解析

TDD: 本文件先于 power_scope/core/debug_service.py 编写，初次运行应全部失败 (RED)。
"""
from __future__ import annotations

import struct
import pytest

from power_scope.core.event_bus import EventBus, VarUpdatedEvent
from power_scope.core.cffi_loader import DebugProtocol

from tests.conftest import pump_events


@pytest.fixture
def captured():
    """收集 DebugService 发出的原始字节"""
    return []


@pytest.fixture
def service(qapp, captured):
    from power_scope.core.debug_service import DebugService
    return DebugService(writer=captured.append)


@pytest.fixture
def collect_var_updates(qapp):
    """订阅 var/updated，返回收集列表"""
    events: list[VarUpdatedEvent] = []
    EventBus.instance().subscribe("var/updated", events.append)
    return events


class TestStreamDecode:
    """STREAM_DATA 解码 — 问题 1 的真正修复"""

    def _make_layout(self):
        from power_scope.core.debug_service import SampleChannel
        return [
            SampleChannel(name="Vdc", address=0x20000000, size=2,
                          type_name="uint16_t", scale=0.1, offset=0.0, unit="V"),
            SampleChannel(name="Id", address=0x20000004, size=2,
                          type_name="int16_t", scale=0.01, offset=0.0, unit="A"),
        ]

    def test_stream_frame_decoded_to_var_updated(self, service, collect_var_updates):
        """单帧 STREAM_DATA → 两条 var/updated，物理值经 scale 换算，时间戳取自 MCU"""
        service.register_sample_layout(0, self._make_layout())
        # Vdc 原始 2300 → 230.0 V; Id 原始 1500 → 15.0 A
        data = struct.pack("<Hh", 2300, 1500)
        frame = DebugProtocol.build_stream_frame(
            seq=1, timestamp=123456, list_id=0, sample_count=1, data=data)

        service.feed(frame)
        pump_events()

        by_name = {e.name: e for e in collect_var_updates}
        assert set(by_name) == {"Vdc", "Id"}
        assert by_name["Vdc"].raw_value == 2300
        assert abs(by_name["Vdc"].phys_value - 230.0) < 1e-6
        assert by_name["Vdc"].unit == "V"
        assert by_name["Id"].raw_value == 1500
        assert abs(by_name["Id"].phys_value - 15.0) < 1e-6
        # 时间戳取自帧内 MCU 微秒时间戳，而非 PC 时钟
        assert abs(by_name["Vdc"].timestamp - 123456 / 1e6) < 1e-9
        assert by_name["Vdc"].source == "stream"

    def test_stream_frame_split_across_chunks(self, service, collect_var_updates):
        """帧被拆成两个字节块到达时仍能正确组帧解码"""
        service.register_sample_layout(0, self._make_layout())
        data = struct.pack("<Hh", 2300, 1500)
        frame = DebugProtocol.build_stream_frame(
            seq=2, timestamp=1000, list_id=0, sample_count=1, data=data)

        service.feed(frame[:7])
        pump_events()
        assert collect_var_updates == []          # 数据不足，未解码
        service.feed(frame[7:])
        pump_events()
        assert len(collect_var_updates) == 2

    def test_unknown_list_id_does_not_crash(self, service, collect_var_updates):
        """收到未注册布局的 list_id 时不崩溃、不产出脏数据"""
        data = struct.pack("<Hh", 1, 2)
        frame = DebugProtocol.build_stream_frame(
            seq=1, timestamp=1, list_id=7, sample_count=1, data=data)
        service.feed(frame)       # 布局未知
        pump_events()
        assert collect_var_updates == []

    def test_leading_garbage_is_skipped(self, service, collect_var_updates):
        """SOF 前的垃圾字节被跳过，仍能解析后续完整帧"""
        service.register_sample_layout(0, self._make_layout())
        data = struct.pack("<Hh", 2300, 1500)
        frame = DebugProtocol.build_stream_frame(
            seq=1, timestamp=5, list_id=0, sample_count=1, data=data)
        service.feed(b"\x00\xff\x12" + frame)
        pump_events()
        assert len(collect_var_updates) == 2


class TestRequestResponse:
    """请求/响应事务 — 解决“假读/假写”"""

    def test_read_memory_response_invokes_callback(self, service, captured):
        """read_memory 发命令帧，匹配 seq 的响应到达时回调拿到 payload"""
        got = {}
        seq = service.read_memory(0x20000000, 4, callback=lambda r: got.update(r))

        # 校验发出的是合法 READ_MEM 命令帧
        assert len(captured) == 1
        parsed = DebugProtocol.parse_frame(captured[0])
        assert parsed["cmd"] == DebugProtocol.CMD_READ_MEM
        assert parsed["seq"] == seq
        assert parsed["address"] == 0x20000000

        # MCU 回一个同 seq 的响应，payload = 42 (uint32)
        resp = DebugProtocol.build_response(
            DebugProtocol.CMD_READ_MEM, seq, status=0, payload=struct.pack("<I", 42))
        service.feed(resp)
        pump_events()

        assert got["seq"] == seq
        assert got["status"] == 0
        assert struct.unpack("<I", got["payload"])[0] == 42

    def test_mismatched_seq_does_not_invoke_callback(self, service):
        """响应 seq 不匹配时不触发回调"""
        called = []
        service.read_memory(0x20000000, 4, callback=lambda r: called.append(r))
        resp = DebugProtocol.build_response(
            DebugProtocol.CMD_READ_MEM, 9999, status=0, payload=b"\x00")
        service.feed(resp)
        pump_events()
        assert called == []


class TestDeviceControlAndInfo:
    """DEVICE_CONTROL(0x0C) 与 GET_INFO 解析 (NS800RT 联调)"""

    def test_device_control_start_frame(self, service, captured):
        seq = service.device_control(True)
        parsed = DebugProtocol.parse_frame(captured[0])      # parse 校验 CRC
        assert parsed["cmd"] == 0x0C
        assert parsed["seq"] == seq
        assert parsed["payload"] == b"\x01"

    def test_device_control_stop_frame(self, service, captured):
        service.device_control(False)
        parsed = DebugProtocol.parse_frame(captured[0])
        assert parsed["cmd"] == 0x0C
        assert parsed["payload"] == b"\x00"

    def test_parse_device_info(self):
        from power_scope.core.debug_service import DebugService
        info = (b"NS800RT5039".ljust(32, b"\x00")
                + struct.pack("<IIH", 240000000, 0, 1)
                + b"1.0.0".ljust(16, b"\x00")).ljust(60, b"\x00")
        d = DebugService.parse_device_info(info)
        assert d["model"] == "NS800RT5039"
        assert d["cpu_freq_hz"] == 240000000
        assert d["protocol_ver"] == 1
        assert d["fw_version"] == "1.0.0"

    def test_parse_device_info_too_short(self):
        from power_scope.core.debug_service import DebugService
        assert DebugService.parse_device_info(b"\x00\x01") == {}


class TestSerialQuickCommands:
    """串口页 NS800RT 快捷帧 — 必须带正确 CRC 与命令码 (F1)"""

    def test_quick_commands_valid(self):
        from power_scope.ui.serial_monitor_view import SerialMonitorView
        cmds = SerialMonitorView.ns800rt_quick_commands()
        labels = [c[0] for c in cmds]
        assert "读设备信息" in labels and "开机" in labels and "关机" in labels
        for label, hexstr in cmds:
            parsed = DebugProtocol.parse_frame(bytes.fromhex(hexstr))   # 校验 CRC，错则抛
            assert parsed["cmd"] in (0x07, 0x06, 0x0C)
        by = {l: h for l, h in cmds}
        assert DebugProtocol.parse_frame(bytes.fromhex(by["开机"]))["payload"] == b"\x01"
        assert DebugProtocol.parse_frame(bytes.fromhex(by["关机"]))["payload"] == b"\x00"


class TestStats:
    """链路统计 — 供状态条展示"""

    def _layout(self):
        from power_scope.core.debug_service import SampleChannel
        return [
            SampleChannel("Vdc", 0x20000000, 2, "uint16_t", 0.1, 0.0, "V"),
            SampleChannel("Id", 0x20000004, 2, "int16_t", 0.01, 0.0, "A"),
        ]

    def test_stream_updates_stats(self, service):
        service.register_sample_layout(0, self._layout())
        data = struct.pack("<Hh", 2300, 1500)
        frame = DebugProtocol.build_stream_frame(
            seq=1, timestamp=10, list_id=0, sample_count=1, data=data)
        service.feed(frame)
        pump_events()
        st = service.stats
        assert st.bytes_received == len(frame)
        assert st.stream_frames == 1
        assert st.frames_ok == 1
        assert st.var_updates == 2
        assert st.crc_errors == 0

    def test_crc_error_counted(self, service):
        service.register_sample_layout(0, self._layout())
        data = struct.pack("<Hh", 2300, 1500)
        frame = bytearray(DebugProtocol.build_stream_frame(
            seq=1, timestamp=10, list_id=0, sample_count=1, data=data))
        frame[12] ^= 0xFF       # 破坏一个 payload 字节 → CRC 失配
        service.feed(bytes(frame))
        pump_events()
        assert service.stats.crc_errors >= 1
        assert service.stats.var_updates == 0

    def test_response_counted(self, service):
        resp = DebugProtocol.build_response(
            DebugProtocol.CMD_READ_MEM, 1, status=0, payload=b"\x01\x02\x03\x04")
        service.feed(resp)
        pump_events()
        assert service.stats.responses == 1
        snap = service.stats_snapshot()
        assert snap["responses"] == 1 and snap["frames_ok"] == 1


class TestBuildChannels:
    """从 profile + ELF 符号表构造采样通道（MainWindow 接线用）"""

    def _profile(self):
        from power_scope.config.device_profile import DeviceProfile, VarBinding
        return DeviceProfile(
            name="t", device_type="x", version="1",
            variables=[
                VarBinding(name="Vdc", elf_symbol="gVdc", unit="V", scale=0.1, update_rate=10),
                VarBinding(name="Id", elf_symbol="gId", unit="A", scale=0.01, update_rate=10),
                VarBinding(name="Static", elf_symbol="gStatic", update_rate=0),
            ])

    def _syms(self):
        from power_scope.debug.elf_parser import ElfVariable
        return {
            "gVdc": ElfVariable(name="gVdc", address=0x20000000, size=2, type_name="uint16_t"),
            "gId": ElfVariable(name="gId", address=0x20000004, size=2, type_name="int16_t"),
        }

    def test_builds_channels_from_symbols(self):
        from power_scope.core.debug_service import build_sample_channels
        chans = build_sample_channels(self._profile(), self._syms())
        # update_rate=0 的 Static 被排除；其余按符号解析
        assert [c.name for c in chans] == ["Vdc", "Id"]
        assert chans[0].address == 0x20000000
        assert chans[0].size == 2
        assert chans[0].type_name == "uint16_t"
        assert chans[0].scale == 0.1 and chans[0].unit == "V"

    def test_skips_unresolved_symbols(self):
        from power_scope.core.debug_service import build_sample_channels
        assert build_sample_channels(self._profile(), {}) == []

    def test_names_filter_overrides_update_rate(self):
        from power_scope.core.debug_service import build_sample_channels
        chans = build_sample_channels(self._profile(), self._syms(), names={"Id"})
        assert [c.name for c in chans] == ["Id"]


class TestCommandBuilding:
    """命令帧构造 — 采样列表下发"""

    def test_setup_sample_list_builds_parseable_frame(self, service, captured):
        from power_scope.core.debug_service import SampleChannel
        chans = [
            SampleChannel("Vdc", 0x20000000, 2, "uint16_t"),
            SampleChannel("Id", 0x20000004, 2, "int16_t"),
        ]
        service.setup_sample_list(list_id=0, period_us=1000, channels=chans)

        assert len(captured) == 1
        parsed = DebugProtocol.parse_frame(captured[0])
        assert parsed["cmd"] == DebugProtocol.CMD_SET_SAMPLE
        payload = parsed["payload"]
        assert payload[0] == 0                       # list_id
        assert struct.unpack("<H", payload[1:3])[0] == 1000   # period_us
        assert payload[3] == 2                        # channel count
        # 布局在 MCU 确认(OK ACK)后才提交，避免乐观切换导致错位解码
        assert not service.has_layout(0)
        service.feed(DebugProtocol.build_response(
            DebugProtocol.CMD_SET_SAMPLE, parsed["seq"], status=0, payload=b""))
        pump_events()
        assert service.has_layout(0)

class TestReadBatch:
    def test_builds_wire_format_and_dispatches_response(self, service, captured):
        got = {}
        items = [(0x20000000, 4), (0x20000010, 2)]
        seq = service.read_batch(items, callback=lambda response: got.update(response))

        parsed = DebugProtocol.parse_frame(captured[0])
        assert parsed["cmd"] == 0x03
        assert parsed["seq"] == seq
        assert parsed["address"] == 0
        assert parsed["payload"] == (
            b"\x02" + struct.pack("<IB", 0x20000000, 4)
            + struct.pack("<IB", 0x20000010, 2))

        payload = struct.pack("<IH", 0x12345678, 0xABCD)
        service.feed(DebugProtocol.build_response(0x03, seq, 0, payload))
        pump_events()
        assert got["status"] == 0
        assert got["payload"] == payload

    @pytest.mark.parametrize("items", [
        [],
        [(0x20000000, 4)] * 33,
        [(0x20000000, 3)],
        [(-1, 4)],
        [(0x100000000, 4)],
    ])
    def test_rejects_invalid_items_before_sending(self, service, captured, items):
        with pytest.raises(ValueError):
            service.read_batch(items)
        assert captured == []
        assert service._seq == 0

    def test_accepts_maximum_256_byte_response_layout(self, service, captured):
        service.read_batch([(0x20000000 + index * 8, 8) for index in range(32)])
        parsed = DebugProtocol.parse_frame(captured[0])
        assert parsed["payload"][0] == 32
        assert len(parsed["payload"]) == 161



class TestMalformedLengthRecovery:
    def test_oversized_response_length_does_not_block_next_frame(self, service, captured):
        from power_scope.core.cffi_loader import DebugProtocol
        seen = []
        seq = service.read_memory(0x20000000, 4, callback=seen.append)
        fake = bytes([0xA5, 0x5A, 1, 1, 0, 0, 0, 0xFF, 0xFF])
        good = DebugProtocol.build_response(
            DebugProtocol.CMD_READ_MEM, seq, 0, b"\x01\x02\x03\x04")
        service.feed(fake + good)
        assert seen and seen[0]["payload"] == b"\x01\x02\x03\x04"

    def test_oversized_stream_count_does_not_block_next_response(self, service):
        from power_scope.core.cffi_loader import DebugProtocol
        from power_scope.core.debug_service import SampleChannel
        service.register_sample_layout(
            0, [SampleChannel(f"v{i}", 0x20000000 + i * 8, 8, "uint64_t")
                for i in range(32)])
        seen = []
        seq = service.get_info(callback=seen.append)
        fake_stream_header = bytes([
            0xA5, 0x5A, 1, DebugProtocol.CMD_STREAM_DATA,
            0, 0, 0, 0, 0, 0, 0, 0xFF])
        good = DebugProtocol.build_response(
            DebugProtocol.CMD_GET_INFO, seq, 0, b"")
        service.feed(fake_stream_header + good)
        assert seen and seen[0]["status"] == 0


class TestSampleLayoutCommitOnAck:
    """采样布局只能在 MCU 确认(ACK)后提交 — 修复"读 ELF 变量后流永久停更需重连"。

    根因：setup_sample_list 旧实现乐观地立即 register_sample_layout。一旦 MCU 拒绝
    (地址越界/超长/宽度非法)或 ACK 丢失，MCU 仍在发旧布局流帧，而 PC 已切到新布局解码
    → 每帧 CRC 失配 → var/updated 永久停更，必须重连才恢复。修复后布局只反映 MCU 已确认状态。
    """

    def _ch(self, name, addr, size, type_name):
        from power_scope.core.debug_service import SampleChannel
        return SampleChannel(name=name, address=addr, size=size, type_name=type_name)

    def test_rejected_setup_keeps_old_layout_streaming(self, service, captured,
                                                       collect_var_updates):
        """SET_SAMPLE 被 NACK 时，旧布局流帧应继续解码(不冻结)。"""
        from power_scope.core.cffi_loader import DebugProtocol
        service.register_sample_layout(0, [self._ch("Vdc", 0x20000000, 2, "uint16_t")])
        base = DebugProtocol.build_stream_frame(
            seq=1, timestamp=10, list_id=0, sample_count=1, data=struct.pack("<H", 100))
        service.feed(base)
        pump_events()
        assert len(collect_var_updates) == 1            # 基线：旧布局可解码

        new = [self._ch("Vdc", 0x20000000, 2, "uint16_t"),
               self._ch("Iext", 0x20100000, 2, "int16_t")]
        captured.clear()
        service.setup_sample_list(0, 1000, new)
        sent = DebugProtocol.parse_frame(captured[0])
        service.feed(DebugProtocol.build_response(
            DebugProtocol.CMD_SET_SAMPLE, sent["seq"], status=0x02, payload=b""))  # NACK
        pump_events()

        collect_var_updates.clear()
        again = DebugProtocol.build_stream_frame(
            seq=2, timestamp=20, list_id=0, sample_count=1, data=struct.pack("<H", 200))
        service.feed(again)
        pump_events()
        assert len(collect_var_updates) == 1            # 旧布局仍解码(修复前为 0=冻结)
        assert collect_var_updates[0].raw_value == 200

    def test_layout_committed_only_after_ok_ack(self, service, captured,
                                                collect_var_updates):
        """SET_SAMPLE 的布局在收到 status==0 的 ACK 后才生效。"""
        from power_scope.core.cffi_loader import DebugProtocol
        new = [self._ch("Vdc", 0x20000000, 2, "uint16_t"),
               self._ch("Iext", 0x20000004, 2, "int16_t")]
        service.setup_sample_list(0, 1000, new)
        assert not service.has_layout(0)                # ACK 前不提交
        sent = DebugProtocol.parse_frame(captured[0])
        service.feed(DebugProtocol.build_response(
            DebugProtocol.CMD_SET_SAMPLE, sent["seq"], status=0, payload=b""))
        pump_events()
        assert service.has_layout(0)                    # OK ACK 后提交
        service.feed(DebugProtocol.build_stream_frame(
            seq=1, timestamp=5, list_id=0, sample_count=1,
            data=struct.pack("<Hh", 2300, 1500)))
        pump_events()
        assert {e.name for e in collect_var_updates} == {"Vdc", "Iext"}