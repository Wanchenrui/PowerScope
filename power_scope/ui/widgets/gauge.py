"""仪表盘基础组件 — LED 指示灯 + 仪表盘数值显示"""
from PySide6.QtWidgets import QLabel, QFrame, QVBoxLayout, QProgressBar
from PySide6.QtCore import Qt

from ..theme import font_size, resolve_color, ui_color


class LedIndicator(QLabel):
    """LED 状态指示灯

    显式传入 color_on/color_off 时固定使用该色；省略时跟随主题语义令牌，
    并通过 apply_theme() 在主题切换时重新解析（否则浅色主题下仍是暗色专用值）。
    """

    def __init__(self, color_on=None, color_off=None):
        super().__init__()
        self._explicit_on = color_on
        self._explicit_off = color_off
        self._on = False
        self.setFixedSize(16, 16)
        self._resolve_colors()
        self._update_style()

    def _resolve_colors(self):
        """按当前主题解析亮/暗色。

        传入值一律过 resolve_color()：语义名直接取令牌，旧 hex 经迁移表
        转到语义名 —— 否则 profile 里的 Tokyo Night 色在浅色主题下不可见。
        """
        self.color_on = resolve_color(self._explicit_on, "success")
        self.color_off = resolve_color(self._explicit_off, "log_dim")

    def apply_theme(self, theme_name=None):
        """主题切换后重新解析默认色并重绘。"""
        self._resolve_colors()
        self._update_style()

    def set_on(self, on):
        self._on = on
        self._update_style()

    def _update_style(self):
        c = self.color_on if self._on else self.color_off
        self.setStyleSheet(
            f"background-color:{c};border-radius:8px;border:1px solid rgba(255,255,255,0.2);"
        )


class GaugeWidget(QFrame):
    """仪表盘数值显示组件 — 标题 + 大号数值 + 单位 + 进度条"""

    #: 数值字号走令牌，不再写死 28px
    VALUE_STYLE = "font-size:{size};font-weight:bold;"

    def __init__(self, title, unit="", min_val=0, max_val=100, color=None):
        super().__init__()
        self.setObjectName("card")
        self._min, self._max = min_val, max_val
        self._color_raw = color          # 保留原始规格，供 apply_theme 重解析
        self._color = resolve_color(color, "primary")
        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignCenter)
        tl = QLabel(title)
        tl.setAlignment(Qt.AlignCenter)
        tl.setObjectName("dim")
        self._val = QLabel("---")
        self._val.setObjectName("value")
        self._val.setAlignment(Qt.AlignCenter)
        ul = QLabel(unit)
        ul.setObjectName("unit")
        ul.setAlignment(Qt.AlignCenter)
        self._bar = QProgressBar()
        self._bar.setRange(0, 1000)
        self._bar.setFixedHeight(6)
        self._bar.setTextVisible(False)
        lay.addWidget(tl)
        lay.addWidget(self._val)
        lay.addWidget(ul)
        lay.addWidget(self._bar)
        self._apply_color()

    def _apply_color(self):
        """把当前解析出的颜色应用到数值文字与进度条 chunk。"""
        self._val.setStyleSheet(
            self.VALUE_STYLE.format(size=font_size("value")) + f"color:{self._color};")
        self._bar.setStyleSheet(
            f"QProgressBar::chunk{{background-color:{self._color};}}")

    def apply_theme(self, theme_name=None):
        """主题切换后重新解析颜色（语义名/旧 hex 都会跟随主题）。"""
        self._color = resolve_color(self._color_raw, "primary")
        self._apply_color()

    def set_value(self, v):
        if self._max > self._min:
            pct = int(1000 * (v - self._min) / (self._max - self._min))
            self._bar.setValue(max(0, min(1000, pct)))
        self._val.setText(f"{v:.2f}")
