"""test_theme.py — 主题令牌层测试 (问题 4：消除写死字面色)

  1. 三套主题都含完整令牌（含新增 chart 调色板）
  2. chart_color(i) 按主题调色板取模循环
  3. build_stylesheet 为三套主题生成含语义标签类的 QSS

TDD: 先于实现编写，初次运行应失败 (RED)。
"""
from __future__ import annotations

import pytest

from power_scope.ui.theme import get_theme, build_stylesheet, chart_color


REQUIRED = {
    "bg", "bg_alt", "surface", "border", "text", "text_dim",
    "primary", "success", "warning", "danger", "accent", "cyan", "chart",
}


class TestThemeTokens:
    @pytest.mark.parametrize("name", ["dark", "light", "solar"])
    def test_theme_has_required_tokens(self, name):
        t = get_theme(name)
        assert REQUIRED <= set(t), f"{name} 缺少令牌: {REQUIRED - set(t)}"
        assert isinstance(t["chart"], list) and len(t["chart"]) >= 4

    def test_unknown_theme_falls_back_to_dark(self):
        assert get_theme("不存在") == get_theme("dark")


class TestChartColor:
    def test_returns_hex(self):
        assert chart_color(0).startswith("#")

    def test_distinct_adjacent(self):
        assert chart_color(0) != chart_color(1)

    def test_cycles_modulo_palette(self):
        n = len(get_theme("dark")["chart"])
        assert chart_color(0) == chart_color(n)

    def test_theme_specific_does_not_raise(self):
        assert chart_color(2, "light").startswith("#")
        assert chart_color(2, "solar").startswith("#")


class TestStylesheet:
    @pytest.mark.parametrize("name", ["dark", "light", "solar"])
    def test_builds_nonempty(self, name):
        qss = build_stylesheet(name)
        assert isinstance(qss, str) and len(qss) > 200

    def test_contains_semantic_label_classes(self):
        qss = build_stylesheet("dark")
        assert "QLabel#dim" in qss
        assert "QLabel#hint" in qss
        assert 'role="ok"' in qss

    def test_uses_theme_palette(self):
        t = get_theme("dark")
        qss = build_stylesheet("dark")
        assert t["bg"] in qss and t["primary"] in qss
