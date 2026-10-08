"""test_workspace_and_snapshots.py — 工作区快照/还原点/审计/报告核心（P1-7/11/12）"""
from __future__ import annotations

from power_scope.core.debug_report import (
    report_from_snapshot, render_html, render_markdown,
)
from power_scope.core.param_snapshot import ParamSnapshotStore
from power_scope.core.write_audit import WriteAuditLog
from power_scope.core.workspace import WorkspaceStore, WorkspaceSnapshot


class TestWorkspaceStore:
    def test_save_get_delete(self, tmp_path):
        store = WorkspaceStore(tmp_path / "ws.json")
        snap = WorkspaceSnapshot(name="t", saved_at=0.0,
                                 scope_channels=["Vdc"], watch_items=[
                                     {"name": "g_kp", "type_name": "float",
                                      "address": "0x20000000", "size": "4B"}])
        store.save("NS800RT", snap)
        loaded = store.get("NS800RT")
        assert loaded is not None
        assert loaded.scope_channels == ["Vdc"]
        assert loaded.watch_items[0]["name"] == "g_kp"
        names = [w.name for w in store.load_all()]
        assert "NS800RT" in names
        store.delete("NS800RT")
        assert store.get("NS800RT") is None

    def test_save_same_name_replaces(self, tmp_path):
        store = WorkspaceStore(tmp_path / "ws.json")
        snap = WorkspaceSnapshot(name="x", saved_at=0.0)
        store.save("dup", snap)
        store.save("dup", snap)
        assert len(store.load_all()) == 1


class TestParamSnapshotStore:
    def test_add_and_latest(self, tmp_path):
        store = ParamSnapshotStore(tmp_path / "ps.json")
        assert store.latest() is None
        point = store.add("写入前", {"Kp": 0.85, "Ki": 120.0})
        latest = store.latest()
        assert latest is not None
        assert latest.values["Kp"] == 0.85
        assert "Kp=0.85" in point.summary()


class TestWriteAuditLog:
    def test_append_and_read(self, tmp_path):
        log = WriteAuditLog(tmp_path / "audit.jsonl")
        log.append("Kp", 0.9, 0.85, source="manual")
        log.append("Ki", 121.0, 120.0, source="tuning", note="写后读回")
        records = log.records()
        assert len(records) == 2
        assert records[-1].var == "Ki"
        assert records[-1].old_value == 120.0
        assert records[-1].note == "写后读回"

    def test_corrupt_line_tolerated(self, tmp_path):
        path = tmp_path / "audit.jsonl"
        log = WriteAuditLog(path)
        log.append("Kp", 1.0, 0.9)
        with path.open("a", encoding="utf-8") as fh:
            fh.write("{not json}\n")
        assert len(log.records()) == 1


class TestDebugReport:
    def _payload(self):
        return {
            "device_profile": "C01",
            "connection": {"state": "connected", "info": "COM3"},
            "values": {"pv_voltage": 380.5, "grid_current": 12.3},
            "active_alarms": ["PV A 过压"],
            "msg_latency": {"p99_ms": 3.2},
            "last_wave_recorder": {"overflow_count": 0},
        }

    def test_markdown_contains_sections(self):
        report = report_from_snapshot(
            self._payload(),
            tuning_metrics={"overshoot_pct": 5.0},
            tuning_params={"Kp": 0.85},
            audit_records=[{"timestamp": 1, "var": "Kp", "old_value": 0.8,
                            "new_value": 0.85, "source": "manual", "note": ""}])
        md = render_markdown(report)
        assert "# PowerScope 调试报告" in md
        assert "pv_voltage" in md
        assert "PV A 过压" in md
        assert "Kp" in md

    def test_html_self_contained(self):
        report = report_from_snapshot(self._payload())
        html = render_html(report)
        assert "<!DOCTYPE html>" in html
        assert "PowerScope 调试报告" in html
        assert "pv_voltage" in html
        # 自包含：无外部资源引用
        assert "http://" not in html and "src=" not in html

    def test_empty_payload_renders(self):
        report = report_from_snapshot({})
        md = render_markdown(report)
        html = render_html(report)
        assert "无活动告警" in md
        assert "（无数据）" in html
