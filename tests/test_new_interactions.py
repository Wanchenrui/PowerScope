"""test_new_interactions.py — P0/P1 新交互的 UI 级测试"""
from __future__ import annotations

import time

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication


# ═══════════════════════════════════════════════════════════════════
# P0-3：inline 确认条
# ═══════════════════════════════════════════════════════════════════

class TestConfirmBar:
    def test_ask_confirm_cancel(self, qapp):
        from power_scope.ui.widgets.confirm_bar import ConfirmBar
        bar = ConfirmBar()
        assert not bar.is_pending()
        confirmed = []
        cancelled = []
        bar.confirmed.connect(lambda: confirmed.append(1))
        bar.cancelled.connect(lambda: cancelled.append(1))
        bar.ask("确认写入", "Kp = 0.85？")
        assert bar.is_pending()
        assert "Kp = 0.85" in bar._text.text()
        bar._no.click()
        assert not bar.is_pending()
        assert cancelled and not confirmed
        bar.ask("确认写入", "Kp = 0.85？")
        bar._yes.click()
        assert confirmed and not bar.is_pending()


# ═══════════════════════════════════════════════════════════════════
# P0-2：数值 delta / sparkline
# ════════════════════════════════════════════════��══════════════════

class TestValueTrend:
    def test_push_returns_delta(self, qapp):
        from power_scope.ui.widgets.sparkline import ValueTrend
        trend = ValueTrend()
        assert trend.push(10.0, 1.0) is None      # 首次无 delta
        delta = trend.push(12.0, 2.0)
        assert delta is not None
        assert delta.direction == "up"
        assert abs(delta.absolute - 2.0) < 1e-9
        assert abs(delta.percent - 20.0) < 1e-6
        delta2 = trend.push(11.0, 3.0)
        assert delta2.direction == "down"

    def test_clear_resets(self, qapp):
        from power_scope.ui.widgets.sparkline import ValueTrend
        trend = ValueTrend()
        trend.push(1.0)
        trend.clear()
        assert trend.push(5.0) is None


# ═══════════════════════════════════════════════════════════════════
# P1-9：发送历史 + 序列解析
# ═══════════════════════════════════════════════════════════════════

class TestHistoryLineEdit:
    def test_up_down_history(self, qapp):
        from power_scope.ui.widgets.history_line_edit import HistoryLineEdit
        edit = HistoryLineEdit()
        edit.push_history("A5 5A 01")
        edit.push_history("A5 5A 02")
        edit.push_history("A5 5A 03")
        edit.keyPressEvent(_key(Qt.Key_Up))
        assert edit.text() == "A5 5A 03"
        edit.keyPressEvent(_key(Qt.Key_Up))
        assert edit.text() == "A5 5A 02"
        edit.keyPressEvent(_key(Qt.Key_Down))
        assert edit.text() == "A5 5A 03"
        edit.keyPressEvent(_key(Qt.Key_Down))
        assert edit.text() == "A5 5A 03" or edit.text() == ""

    def test_empty_text_not_added(self, qapp):
        from power_scope.ui.widgets.history_line_edit import HistoryLineEdit
        edit = HistoryLineEdit()
        edit.push_history("  ")
        assert edit.history() == []


class TestHexLines:
    def test_parse_frames_and_errors(self):
        from power_scope.ui.widgets.hex_highlighter import parse_hex_lines
        # 注释/空行忽略；ZZ 非 Hex 报错；A5 是合法的单字节帧
        frames, errors = parse_hex_lines(
            "A5 5A 01 02\n# 注释\n\nZZ\nA5")
        assert frames == ["A55A0102", "A5"]
        assert errors == ["ZZ"]

    def test_parse_odd_nibbles_error(self):
        from power_scope.ui.widgets.hex_highlighter import parse_hex_lines
        frames, errors = parse_hex_lines("A5 5A 0")   # 3 个半字节
        assert frames == []
        assert errors == ["A5 5A 0"]

    def test_parse_comma_and_semicolon(self):
        from power_scope.ui.widgets.hex_highlighter import parse_hex_lines
        # 一行即一帧：逗号/分号是字节分隔符，不换帧
        frames, errors = parse_hex_lines("A5,5A,01,02; A5 5A 03")
        assert errors == []
        assert frames == ["A55A0102A55A03"]


# ═══════════════════════════════════════════════════════════════════
# P0-5：光标测量 UI 闭环
# ════════════════════════════════════════════════��══════════════════

class TestScopeMeasureUI:
    def _scope(self, qapp):
        from power_scope.ui.scope_view import ScopeView
        view = ScopeView(profile=None)
        view._add_names(["Vdc"])
        for i in range(40):
            view._plot.add_sample("Vdc", i * 0.01, 1.0 - __import__("math").exp(-i * 0.01 / 0.05))
        return view

    def test_measure_toggle_shows_metrics(self, qapp):
        view = self._scope(qapp)
        view._measure_btn.setChecked(True)
        view._on_dual_cursor_moved(0.05, 0.35)
        assert "指标:" in view._measure_result.text()
        assert view._send_to_tuning_btn.isEnabled()

    def test_send_metrics_emits(self, qapp):
        view = self._scope(qapp)
        view._measure_btn.setChecked(True)
        view._on_dual_cursor_moved(0.05, 0.35)
        got = []
        view.metrics_to_tuning.connect(got.append)
        view._send_metrics_to_tuning()
        assert got and got[0]["channel"] == "Vdc"
        assert got[0]["rise_ms"] > 0

    def test_measure_off_hides_bar(self, qapp):
        view = self._scope(qapp)
        view._measure_btn.setChecked(True)
        view._measure_btn.setChecked(False)
        assert not view._measure_widget.isVisible()


# ═══════════════════════════════════════════════════════════════════
# P1-7：工作区收集/恢复（视图级）
# ═══════════════════════════════════════════════════════════════════

class TestWorkspaceViewHooks:
    def test_scope_collect_restore(self, qapp):
        from power_scope.ui.scope_view import ScopeView
        view = ScopeView(profile=None)
        view._add_names(["Vdc", "Idc"])
        data = view.collect_workspace()
        assert "Vdc" in data["scope_channels"]
        view2 = ScopeView(profile=None)
        view2.restore_workspace(data)
        assert view2.plotted_channels() == ["Vdc", "Idc"]

    def test_serial_collect_restore(self, qapp):
        from power_scope.ui.serial_monitor_view import SerialMonitorView
        view = SerialMonitorView()
        view._send_input.setText("A5 5A 01")
        data = view.collect_workspace()
        assert data["send_input"] == "A5 5A 01"
        view2 = SerialMonitorView()
        view2.restore_workspace({"send_input": "A5 5A 09"})
        assert view2._send_input.text() == "A5 5A 09"

    def test_inspector_collect_restore(self, qapp):
        from power_scope.ui.variable_inspector_view import VariableInspectorView
        view = VariableInspectorView(profile=None)
        view.add_watch_address("g_kp", "uint32_t", "0x20000000")
        data = view.collect_workspace()
        assert data["watch_items"][0]["name"] == "g_kp"
        view2 = VariableInspectorView(profile=None)
        view2.restore_workspace(data)
        assert view2._watch_table.rowCount() == 1


# ═══════════════════════════════════════════════════════════════════
# P1-8：快捷命令编辑器 store 驱动
# ═══════════════════════════════════════════════════════════════════

class TestQuickCommandEditor:
    def test_editor_lists_defaults(self, qapp, tmp_path):
        from power_scope.core.quick_commands import QuickCommandStore
        from power_scope.ui.quick_command_editor import QuickCommandEditor
        store = QuickCommandStore(tmp_path / "qc.json")
        editor = QuickCommandEditor(store)
        assert editor._table.rowCount() >= 4
        # 新增一条（内置帧 CRC 合法）
        editor._name_edit.setText("测试命令")
        editor._frame_edit.setText("A5 5A 01 07 01 00 00 00 00 00 00 00 7D 2F")
        editor._save_btn.click()
        assert any(c.name == "测试命令" for c in store.load())

    def test_editor_rejects_bad_crc(self, qapp, tmp_path):
        from power_scope.core.quick_commands import QuickCommandStore
        from power_scope.ui.quick_command_editor import QuickCommandEditor
        store = QuickCommandStore(tmp_path / "qc.json")
        editor = QuickCommandEditor(store)
        editor._name_edit.setText("坏命令")
        editor._frame_edit.setText("A5 5A 01 07 01 00 00 00 00 00 00 00 00 00")
        editor._save_btn.click()
        assert not any(c.name == "坏命令" for c in store.load())
        assert "CRC" in editor._form_status.text()

    def test_serial_view_rebuilds_from_store(self, qapp, tmp_path):
        from power_scope.core.quick_commands import QuickCommandStore
        from power_scope.ui.serial_monitor_view import SerialMonitorView
        store = QuickCommandStore(tmp_path / "qc.json")
        view = SerialMonitorView()
        view._quick_store = store
        view._reload_quick_commands()
        assert len(view._quick_buttons) >= 4
        assert view._quick_buttons[0].text() == "读设备信息"


# ═══════════════════════════════════════════════════════════════════
# P1-10：会话回放视图
# ═══════════════════════════════════════════════════════════════════

class TestSessionReplay:
    def test_replay_loads_session_and_plays(self, qapp, tmp_path):
        from power_scope.core.session_recorder import SessionRecorder
        from power_scope.ui.replay_view import SessionReplayView

        db = str(tmp_path / "sessions.db")
        recorder = SessionRecorder(db)
        session_id = recorder.start_session("现场排障", device_name="C01")
        base = time.time()
        for i in range(50):
            recorder.record_var("Vdc", base + i * 0.1, float(i),
                                float(i) * 0.1, "V", source="mock")
        recorder.flush()
        recorder.end_session()

        view = SessionReplayView(recorder=recorder)
        view._session_list.setCurrentRow(0)
        assert view._session_id == session_id
        # 勾选 Vdc → 预载 → 播放
        for index in range(view._var_list.count()):
            item = view._var_list.item(index)
            if item.text() == "Vdc":
                item.setCheckState(Qt.Checked)
        assert "Vdc" in view._series
        view._play_btn.setChecked(True)
        assert view._playing
        # 拖动时间轴到 1s 处，曲线应已渲染部分样本
        view._on_timeline_moved(1000)
        assert view._plot.sample_count("Vdc") > 0
        view._play_btn.setChecked(False)
        view.cleanup()


def _key(key_code):
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtCore import QEvent
    return QKeyEvent(QEvent.KeyPress, key_code, Qt.NoModifier)
