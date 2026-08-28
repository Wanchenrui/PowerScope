"""test_inspector_batch.py — 变量查看器批量读取/添加/绘图 (Problem 2)"""
from __future__ import annotations

import pytest


@pytest.fixture
def inspector(qapp):
    from power_scope.ui.variable_inspector_view import VariableInspectorView
    return VariableInspectorView(profile=None)


class FakeDebug:
    def __init__(self):
        self.reads = []
        self.writes = []

    def read_memory(self, addr, size, callback=None):
        self.reads.append((addr, size))

    def write_memory(self, addr, data, callback=None):
        self.writes.append((addr, bytes(data)))


class TestBatch:
    def test_tree_multi_select_enabled(self, inspector):
        from PySide6.QtWidgets import QAbstractItemView
        assert inspector._tree.selectionMode() == QAbstractItemView.ExtendedSelection

    def test_read_all_reads_every_row(self, inspector):
        dbg = FakeDebug()
        inspector.set_debug_service(dbg)
        inspector.set_connected(True)
        inspector.add_watch_address("a", "uint32_t", "0x20000000")
        inspector.add_watch_address("b", "uint16_t", "0x20000010")
        inspector._on_read_all()
        assert len(dbg.reads) == 2
        assert (0x20000000, 4) in dbg.reads
        assert (0x20000010, 2) in dbg.reads

    def test_plot_selected_emits_specs(self, inspector):
        inspector.add_watch_address("a", "float", "0x20000000")
        got = []
        inspector.plot_requested.connect(lambda specs: got.append(specs))
        inspector._on_plot_selected()       # 无选中 → 全部
        assert got
        spec = got[0][0]
        assert spec["name"] == "a"
        assert spec["address"] == 0x20000000
        assert spec["size"] == 4
        assert spec["type_name"] == "float"

    def test_remove_row_uses_sender_not_stale_index(self, inspector):
        for nm, addr in [("a", "0x20000000"), ("b", "0x20000001"), ("c", "0x20000002")]:
            inspector.add_watch_address(nm, "uint8_t", addr)
        # 删除第一行 → 后续行索引下移
        inspector._watch_table.cellWidget(0, 4).click()
        names = [inspector._watch_table.item(r, 0).text()
                 for r in range(inspector._watch_table.rowCount())]
        assert names == ["b", "c"]
        # 删除 'c'（原 row2，现 row1）：旧代码会用过期索引删错行
        target = None
        for r in range(inspector._watch_table.rowCount()):
            if inspector._watch_table.item(r, 0).text() == "c":
                target = inspector._watch_table.cellWidget(r, 4)
        target.click()
        names = [inspector._watch_table.item(r, 0).text()
                 for r in range(inspector._watch_table.rowCount())]
        assert names == ["b"]

    def test_read_all_empty_table_noop(self, inspector):
        dbg = FakeDebug()
        inspector.set_debug_service(dbg)
        inspector.set_connected(True)
        inspector._on_read_all()
        assert dbg.reads == []

class FakeBatchDebug(FakeDebug):
    def __init__(self, payload=b"", status=0):
        super().__init__()
        self.batches = []
        self.payload = payload
        self.status = status

    def read_batch(self, items, callback=None):
        self.batches.append(list(items))
        if callback is not None:
            callback({"status": self.status, "payload": self.payload})


class TestSingleFrameBatchRead:
    def test_read_all_uses_one_batch_and_decodes_rows(self, inspector):
        import struct

        dbg = FakeBatchDebug(struct.pack("<IH", 0x12345678, 0xABCD))
        inspector.set_debug_service(dbg)
        inspector.set_connected(True)
        inspector.add_watch_address("a", "uint32_t", "0x20000000")
        inspector.add_watch_address("b", "uint16_t", "0x20000010")

        inspector._on_read_all()

        assert dbg.reads == []
        assert dbg.batches == [[(0x20000000, 4), (0x20000010, 2)]]
        assert inspector._watch_table.item(0, 3).text() == str(0x12345678)
        assert inspector._watch_table.item(1, 3).text() == str(0xABCD)

    def test_more_than_32_rows_are_chunked(self, inspector):
        dbg = FakeBatchDebug(payload=b"\x00" * 32)
        inspector.set_debug_service(dbg)
        inspector.set_connected(True)
        for index in range(33):
            inspector.add_watch_address(
                f"v{index}", "uint8_t", hex(0x20000000 + index))

        inspector._on_read_all()

        assert [len(batch) for batch in dbg.batches] == [32, 1]

    def test_batch_payload_length_mismatch_does_not_update(self, inspector):
        dbg = FakeBatchDebug(payload=b"\x01")
        inspector.set_debug_service(dbg)
        inspector.set_connected(True)
        inspector.add_watch_address("a", "uint32_t", "0x20000000")
        inspector._on_read_all()
        assert inspector._watch_table.item(0, 3).text() == "---"
        assert "长度" in inspector._log_label.text()

