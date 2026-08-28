"""test_session_recorder.py — 会话录制测试"""
import pytest
import os
import tempfile
from power_scope.core.session_recorder import SessionRecorder, RecordedVar


class TestSessionRecorder:
    @pytest.fixture
    def recorder(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        r = SessionRecorder(path)
        yield r
        r.close()
        os.unlink(path)

    def test_create_and_init(self, recorder):
        assert recorder is not None
        assert not recorder.is_recording

    def test_start_session(self, recorder):
        sid = recorder.start_session("test_session")
        assert sid > 0
        assert recorder.is_recording

    def test_end_session(self, recorder):
        recorder.start_session("test")
        recorder.end_session()
        assert not recorder.is_recording

    def test_record_and_playback(self, recorder):
        recorder.start_session("test")
        recorder.record_var("Vdc", 0.0, 0, 380.5, "V", "mock")
        recorder.record_var("Vdc", 1.0, 0, 381.0, "V", "mock")
        recorder.record_var("Vdc", 2.0, 0, 382.0, "V", "mock")
        recorder.flush()

        events = list(recorder.playback("Vdc"))
        assert len(events) == 3
        assert events[0].timestamp == 0.0
        assert events[0].phys_value == 380.5
        assert events[1].phys_value == 381.0
        assert events[2].phys_value == 382.0

    def test_record_without_session_ignored(self, recorder):
        recorder.record_var("Vdc", 0.0, 0, 380.5, "V", "mock")
        recorder.flush()
        events = list(recorder.playback("Vdc"))
        assert len(events) == 0

    def test_playback_time_range(self, recorder):
        recorder.start_session("test")
        for i in range(10):
            recorder.record_var("Vdc", float(i), 0, 380.0 + i, "V", "mock")
        recorder.flush()

        events = list(recorder.playback("Vdc", start=3.0, end=6.0))
        assert len(events) == 4  # 3,4,5,6
        assert events[0].timestamp == 3.0
        assert events[-1].timestamp == 6.0

    def test_playback_all_vars(self, recorder):
        recorder.start_session("test")
        recorder.record_var("Vdc", 0.0, 0, 380.5, "V", "mock")
        recorder.record_var("Idc", 0.0, 0, 10.0, "A", "mock")
        recorder.flush()

        events = list(recorder.playback_all())
        assert len(events) == 2
        names = {e.name for e in events}
        assert names == {"Vdc", "Idc"}

    def test_export_csv(self, recorder):
        recorder.start_session("test")
        recorder.record_var("Vdc", 0.0, 0, 380.5, "V", "mock")
        recorder.record_var("Vdc", 1.0, 0, 381.0, "V", "mock")
        recorder.flush()

        fd, csv_path = tempfile.mkstemp(suffix=".csv")
        os.close(fd)
        count = recorder.export_csv("Vdc", csv_path)
        assert count == 2

        with open(csv_path, "r") as f:
            lines = f.readlines()
        assert len(lines) == 3  # header + 2 data
        os.unlink(csv_path)

    def test_list_sessions(self, recorder):
        sid1 = recorder.start_session("session_a")
        recorder.end_session()
        sid2 = recorder.start_session("session_b")
        recorder.end_session()

        sessions = recorder.list_sessions()
        assert len(sessions) == 2
        assert sessions[0]["id"] == sid2  # 最新在前
        assert sessions[1]["id"] == sid1

    def test_get_var_names(self, recorder):
        recorder.start_session("test")
        recorder.record_var("Vdc", 0.0, 0, 380.5, "V", "mock")
        recorder.record_var("Idc", 0.0, 0, 10.0, "A", "mock")
        recorder.flush()

        names = recorder.get_var_names()
        assert sorted(names) == ["Idc", "Vdc"]

    def test_get_stats(self, recorder):
        recorder.start_session("test")
        recorder.record_var("Vdc", 0.0, 0, 380.5, "V", "mock")
        recorder.record_var("Vdc", 5.0, 0, 385.0, "V", "mock")
        recorder.flush()

        stats = recorder.get_stats()
        assert stats["total_records"] == 2
        assert stats["start_time"] == 0.0
        assert stats["end_time"] == 5.0

    def test_close_clears_state(self, recorder):
        recorder.start_session("test")
        assert recorder.is_recording
        recorder.close()
        assert not recorder.is_recording
