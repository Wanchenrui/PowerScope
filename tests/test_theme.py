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


class TestArrowAssets:
    """下拉框/SpinBox 箭头子控件必须显式指定图标（深底下不留黑色原生回退）"""

    def test_combo_and_spin_arrows_styled(self):
        qss = build_stylesheet("dark")
        assert "QComboBox::down-arrow" in qss
        assert "QAbstractSpinBox::up-arrow" in qss
        assert "QAbstractSpinBox::down-arrow" in qss
        assert "image: url(" in qss

    def test_glyph_matches_theme_brightness(self):
        assert "arrow_down_dark.png" in build_stylesheet("light")
        assert "arrow_down.png" in build_stylesheet("dark")
        assert "arrow_down.png" in build_stylesheet("solar")

    def test_icon_files_exist(self):
        from pathlib import Path
        from power_scope.ui.theme import icons_dir
        base = Path(icons_dir())
        for name in (
                "arrow_up.png", "arrow_down.png",
                "arrow_up_dim.png", "arrow_down_dim.png",
                "arrow_up_dark.png", "arrow_down_dark.png",
                "arrow_up_dark_dim.png", "arrow_down_dark_dim.png"):
            assert (base / name).is_file(), name

    def test_build_palette_matches_theme(self):
        from PySide6.QtGui import QColor, QPalette
        from power_scope.ui.theme import build_palette
        pal = build_palette("dark")
        assert pal.color(QPalette.Window) == QColor(get_theme("dark")["bg"])
        assert pal.color(QPalette.ButtonText) == QColor(get_theme("dark")["text"])
        pal_light = build_palette("light")
        assert pal_light.color(QPalette.Window) == QColor(get_theme("light")["bg"])
