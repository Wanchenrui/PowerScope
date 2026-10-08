"""test_command_index.py — 命令面板索引与模糊搜索（P0-4）"""
from __future__ import annotations

from power_scope.core.command_index import (
    CommandItem, fuzzy_score, kind_label, search,
)

_ITEMS = [
    CommandItem("page", "前往: 波形", subtitle="页签", payload=1,
                keywords=("tab", "goto")),
    CommandItem("action", "连接设备", payload=("action", None),
                keywords=("connect", "串口")),
    CommandItem("variable", "Vdc_bus", subtitle="直流母线电压",
                payload=("variable", "Vdc_bus"),
                keywords=("var", "bus")),
    CommandItem("symbol", "g_adObjF", subtitle="ELF 符号",
                payload=("symbol", "g_adObjF")),
    CommandItem("msg", "0x2108", subtitle="电网电压读取",
                payload=("msg", 0x2108)),
]


class TestFuzzyScore:
    def test_exact_prefix_scores_high(self):
        assert fuzzy_score("vd", "vdc_bus") > 0
        assert fuzzy_score("vdc_bus", "vdc_bus") > fuzzy_score("vd", "vdc_bus")

    def test_subsequence_match(self):
        assert fuzzy_score("vcb", "vdc_bus") > 0

    def test_no_match_zero(self):
        assert fuzzy_score("xyz", "vdc_bus") == 0

    def test_empty_query_matches(self):
        assert fuzzy_score("", "anything") == 1


class TestSearch:
    def test_finds_variable_by_name(self):
        hits = search(_ITEMS, "vdc")
        assert hits and hits[0][0].title == "Vdc_bus"

    def test_finds_action_by_keyword(self):
        hits = search(_ITEMS, "connect")
        assert any(item.kind == "action" for item, _s in hits)

    def test_finds_page(self):
        hits = search(_ITEMS, "波形")
        assert any(item.kind == "page" for item, _s in hits)

    def test_empty_query_returns_prefix(self):
        hits = search(_ITEMS, "")
        assert len(hits) == len(_ITEMS)

    def test_limit(self):
        hits = search(_ITEMS, "a", limit=2)
        assert len(hits) <= 2

    def test_kind_label(self):
        assert kind_label("variable") == "变量"
        assert kind_label("unknown") == "unknown"
