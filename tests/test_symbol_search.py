"""test_symbol_search.py — ELF 符号搜索与解析缓存 (问题 2)

  1. filter_variables: 按变量名 / 结构体.成员 子串过滤（不区分大小写）
  2. ELFParser.parse_variables: 按文件 mtime 缓存，避免每次全量重解析
  3. VariableInspectorView: 搜索框实时过滤变量树

TDD: 本文件先于实现编写，初次运行应失败 (RED)。
"""
from __future__ import annotations

import pytest

from power_scope.debug.elf_parser import (
    ElfVariable, StructMember, filter_variables, ELFParser,
)


def make_vars():
    return [
        ElfVariable("g_id", 0x20001000, 4, "float"),
        ElfVariable("g_vd", 0x20001008, 4, "float"),
        ElfVariable("g_vq", 0x2000100C, 4, "float"),
        ElfVariable("g_current_pi", 0x20002000, 16, "PIController", is_struct=True, members=[
            StructMember("kp", 0, 4, "float"),
            StructMember("ki", 4, 4, "float"),
            StructMember("kd", 8, 4, "float"),
            StructMember("integral", 12, 4, "float"),
        ]),
        ElfVariable("g_duty", 0x20003000, 2, "uint16_t"),
    ]


class TestFilterVariables:
    def test_empty_returns_all_unfiltered(self):
        hits = filter_variables(make_vars(), "")
        assert len(hits) == 5
        assert all(members is None for _, members in hits)

    def test_substring_name_match(self):
        hits = filter_variables(make_vars(), "vd")
        assert [v.name for v, _ in hits] == ["g_vd"]

    def test_case_insensitive(self):
        assert [v.name for v, _ in filter_variables(make_vars(), "DUTY")] == ["g_duty"]

    def test_member_match_filters_to_matching_members(self):
        hits = filter_variables(make_vars(), "kp")
        assert len(hits) == 1
        var, members = hits[0]
        assert var.name == "g_current_pi"
        assert [m.name for m in members] == ["kp"]

    def test_name_match_shows_all_members(self):
        hits = filter_variables(make_vars(), "current")
        assert len(hits) == 1
        assert hits[0][1] is None          # 变量名命中 → 展示全部成员

    def test_dotted_struct_member_search(self):
        hits = filter_variables(make_vars(), "pi.ki")
        assert len(hits) == 1
        var, members = hits[0]
        assert var.name == "g_current_pi"
        assert [m.name for m in members] == ["ki"]

    def test_no_match_returns_empty(self):
        assert filter_variables(make_vars(), "zzz") == []


class TestParseCache:
    def _parser(self):
        p = object.__new__(ELFParser)
        p.path = "phantom.elf"
        p._cache = None
        p._cache_mtime = None
        return p

    def test_parse_caches_until_mtime_changes(self):
        p = self._parser()
        calls = []
        p._do_parse = lambda: (calls.append(1) or [ElfVariable("g", 0x1000, 4, "uint32_t")])
        p._current_mtime = lambda: 100

        r1 = p.parse_variables()
        r2 = p.parse_variables()
        assert r1 is r2            # 第二次命中缓存，返回同一对象
        assert len(calls) == 1     # 只解析一次

        p._current_mtime = lambda: 200   # 文件改变
        p.parse_variables()
        assert len(calls) == 2     # 触发重新解析


class TestEncodeValue:
    """encode_value — decode_value 的逆，供真实写入路径用"""

    def test_uint8(self):
        from power_scope.debug.elf_parser import encode_value
        assert encode_value(255, "uint8_t") == b"\xff"

    def test_int8_negative(self):
        from power_scope.debug.elf_parser import encode_value
        assert encode_value(-1, "int8_t") == b"\xff"

    def test_uint32_little_endian(self):
        from power_scope.debug.elf_parser import encode_value
        assert encode_value(0x12345678, "uint32_t") == b"\x78\x56\x34\x12"

    def test_hex_string_input(self):
        from power_scope.debug.elf_parser import encode_value
        assert encode_value("0x10", "uint8_t") == b"\x10"

    def test_float_roundtrip(self):
        from power_scope.debug.elf_parser import encode_value, decode_value
        raw = encode_value("1.5", "float")
        assert abs(decode_value(raw, "float") - 1.5) < 1e-6

    def test_unknown_type_raises(self):
        from power_scope.debug.elf_parser import encode_value
        with pytest.raises(ValueError):
            encode_value(1, "PIController")

    def test_type_size(self):
        from power_scope.debug.elf_parser import type_size
        assert type_size("uint16_t") == 2
        assert type_size("float") == 4
        assert type_size("unknown") == 0


class TestGccDwarfTypeNames:
    """decode/encode 兼容 GCC DWARF 基础类型名 (F7)"""

    def test_short_unsigned_int(self):
        from power_scope.debug.elf_parser import decode_value
        assert decode_value(b"\x64\x00", "short unsigned int") == 100

    def test_long_unsigned_int(self):
        from power_scope.debug.elf_parser import decode_value
        assert decode_value(b"\x78\x56\x34\x12", "long unsigned int") == 0x12345678

    def test_long_int_size(self):
        from power_scope.debug.elf_parser import type_size
        assert type_size("long unsigned int") == 4
        assert type_size("short unsigned int") == 2


class TestInspectorRealWrite:
    """变量查看器真实写入路径（连接 + DebugService）"""

    def test_write_var_sends_encoded_bytes(self, qapp, monkeypatch):
        from power_scope.ui.variable_inspector_view import VariableInspectorView
        from PySide6.QtWidgets import QMessageBox, QTableWidgetItem
        view = VariableInspectorView(profile=None)

        sent = []

        class FakeDebug:
            def write_memory(self, addr, data, callback=None):
                sent.append((addr, bytes(data)))

            def read_memory(self, addr, size, callback=None):
                pass

        view.set_debug_service(FakeDebug())
        view.set_connected(True)
        t = view._watch_table
        t.insertRow(0)
        t.setItem(0, 0, QTableWidgetItem("g_kp"))
        t.setItem(0, 1, QTableWidgetItem("uint16_t"))
        t.setItem(0, 2, QTableWidgetItem("0x20000000"))
        t.setItem(0, 3, QTableWidgetItem("---"))
        t.setCurrentCell(0, 0)
        view._write_input.setText("100")
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)

        view._on_write_var()
        assert sent == [(0x20000000, b"\x64\x00")]


def _count_var_nodes(tree):
    n = 0
    for i in range(tree.topLevelItemCount()):
        n += tree.topLevelItem(i).childCount()
    return n


class TestInspectorSearch:
    def test_search_box_filters_tree(self, qapp):
        from power_scope.ui.variable_inspector_view import VariableInspectorView
        view = VariableInspectorView(profile=None)
        view._all_variables = make_vars()

        view._apply_filter("")
        assert _count_var_nodes(view._tree) == 5

        view._apply_filter("vd")
        assert _count_var_nodes(view._tree) == 1

        view._apply_filter("kp")          # 结构体成员命中
        assert _count_var_nodes(view._tree) == 1

        view._apply_filter("zzz")
        assert _count_var_nodes(view._tree) == 0
