"""主题系统 — 工业电力电子调试工具 dark-first 设计令牌

设计方向（适配 NS800RT 并网逆变器调试场景）：
  - 暗色优先（实验室/配电房标准，减少眼部疲劳）
  - 高信息密度 cockpit — 调试工程师需要一眼扫到关键数据
  - 等宽数字强制 — 工程数值不允许字体比例偏差
  - 1px 分割线优先于阴影卡片 — 密集数据用线条组织比卡片更轻
  - 工业冷静色板 — 不花哨、不加动画、不加渐变，数据说话
  - 状态色语义：绿=正常 · 红=故障 · 黄=告警 · 青=交互/信息

令牌层级：Base(原始色值) → Semantic(语义映射) → Component(组件消费)
"""

from PySide6.QtGui import QColor, QPalette, QFont
from PySide6.QtCore import Qt

# ═══════════════════════════════════════════════════════════════════
# Layer 1: Base 色板 — 不直接消费，仅通过 Semantic 引用
# ═══════════════════════════════════════════════════════════════════

BASE_COLORS = {
    # 暗色基底（工业 cockpit）
    "slate_950": "#0c0e14",   # 最深底（窗口背景）
    "slate_900": "#12141c",   # 次级底（面板/卡片）
    "slate_850": "#181a24",   # 抬高底（GroupBox/工具栏）
    "slate_800": "#1e2130",   # 悬浮底（hover）
    "slate_700": "#2a2d3a",   # 边框
    "slate_600": "#3b3f4d",   # 激活边框

    # 前景/文字
    "fg_primary": "#dce0e8",    # 主文字（off-white，不纯白）
    "fg_secondary": "#959aa8",  # 次级文字
    "fg_muted": "#5e6370",      # 禁用/占位符
    "fg_inverse": "#0c0e14",    # 反色文字（在强调色背景上）

    # 唯一强调色 — 青蓝（示波器/工控台传统色）
    "accent": "#00b4d8",        # 主强调（按钮/链接/选中）
    "accent_dim": "#007c99",    # 深强调（按下态）
    "accent_bg": "#0a1a22",     # 强调色底（标签背景）

    # 语义状态色 — 电力行业惯例
    "ok": "#2ecc71",            # 正常/运行（绿）
    "ok_dim": "#1a7a42",        # 深绿
    "ok_bg": "#0a1f12",        # 绿底
    "warn": "#f0c040",          # 告警（黄）
    "warn_dim": "#9a7a20",
    "warn_bg": "#1f1a08",
    "fault": "#e74c3c",         # 故障（红）
    "fault_dim": "#8b1f15",
    "fault_bg": "#1f0c0a",
    "info": "#5dade2",          # 信息（浅蓝）

    # 浅色主题回退（实验室日光环境备用）
    "light_bg": "#fafaf9",
    "light_bg_alt": "#f2f1ef",
    "light_surface": "#e8e7e4",
    "light_border": "#d4d2ce",
    "light_text": "#1c1b1a",
    "light_text_dim": "#6e6c69",
}

# ═══════════════════════════════════════════════════════════════════
# Layer 2: 图表色板 — 多通道波形/曲线颜色
# ═══════════════════════════════════════════════════════════════════

CHART_PALETTES = {
    "dark": [
        "#00b4d8",  # cyan（通道1）
        "#2ecc71",  # green
        "#f0c040",  # yellow
        "#e74c3c",  # red
        "#9b59b6",  # purple
        "#5dade2",  # light blue
        "#ff8c42",  # orange
        "#73d0c0",  # teal
    ],
    "light": [
        "#007c99",  # dark cyan
        "#1a7a42",  # dark green
        "#9a7a20",  # dark yellow
        "#8b1f15",  # dark red
        "#6c3483",  # dark purple
        "#2e86c1",  # dark blue
        "#c05a00",  # dark orange
        "#2e8b7e",  # dark teal
    ],
}

# ═══════════════════════════════════════════════════════════════════
# Layer 3: 间距/圆角/字体令牌
# ═══════════════════════════════════════════════════════════════════

SPACING = {
    "xs": 2,     # 紧密配对（label-input 之间）
    "sm": 4,     # 组件内部
    "md": 8,     # 网格/分组间
    "lg": 12,    # 区块间
    "xl": 16,    # 大区块
    "2xl": 24,   # 视图内边距
}

RADII = {
    "input": "3px",      # 输入框/下拉框
    "button": "4px",     # 按钮
    "card": "6px",       # 卡片/GroupBox
    "panel": "8px",      # 大面板/QFrame#card
}

TYPOGRAPHY = {
    "font_family": '"Microsoft YaHei", "Segoe UI", "Helvetica Neue", Arial, sans-serif',
    "font_mono": '"Cascadia Code", "Consolas", "JetBrains Mono", "Courier New", monospace',
    "size_xs": "11px",
    "size_sm": "12px",
    "size_body": "13px",
    "size_md": "14px",
    "size_lg": "16px",
    "size_xl": "18px",
    "size_2xl": "22px",
    "size_value": "18px",    # 数值大字（Gauge/KPI）
    "weight_normal": "400",
    "weight_medium": "500",
    "weight_bold": "600",
}

# ═══════════════════════════════════════════════════════════════════
# Layer 4: 旧兼容 THEMES 字典（保留对外 API）
# ═══════════════════════════════════════════════════════════════════

THEMES = {
    "dark": {
        "bg": BASE_COLORS["slate_950"],
        "bg_alt": BASE_COLORS["slate_900"],
        "surface": BASE_COLORS["slate_850"],
        "border": BASE_COLORS["slate_700"],
        "text": BASE_COLORS["fg_primary"],
        "text_dim": BASE_COLORS["fg_secondary"],
        "primary": BASE_COLORS["accent"],
        "success": BASE_COLORS["ok"],
        "warning": BASE_COLORS["warn"],
        "danger": BASE_COLORS["fault"],
        "accent": "#7dcfff",
        "cyan": BASE_COLORS["accent"],
        "chart": CHART_PALETTES["dark"],
        # 语义角色色（串口收发/日志/AI 对话等内联样式消费）
        "rx": BASE_COLORS["ok"],
        "tx": BASE_COLORS["warn"],
        "ai": "#9b59b6",
        "user": BASE_COLORS["info"],
        "log_dim": BASE_COLORS["fg_secondary"],
    },
    "light": {
        "bg": BASE_COLORS["light_bg"],
        "bg_alt": BASE_COLORS["light_bg_alt"],
        "surface": BASE_COLORS["light_surface"],
        "border": BASE_COLORS["light_border"],
        "text": BASE_COLORS["light_text"],
        "text_dim": BASE_COLORS["light_text_dim"],
        "primary": BASE_COLORS["accent_dim"],
        "success": BASE_COLORS["ok_dim"],
        "warning": BASE_COLORS["warn_dim"],
        "danger": BASE_COLORS["fault_dim"],
        "accent": "#7b1fa2",
        "cyan": BASE_COLORS["accent_dim"],
        "chart": CHART_PALETTES["light"],
        "rx": BASE_COLORS["ok_dim"],
        "tx": BASE_COLORS["warn_dim"],
        "ai": "#6c3483",
        "user": "#2e86c1",
        "log_dim": BASE_COLORS["light_text_dim"],
    },
    "solar": {
        "bg": "#1a1a2e",
        "bg_alt": "#16213e",
        "surface": "#0f3460",
        "border": "#533483",
        "text": "#e6e6e6",
        "text_dim": "#a6adc8",
        "primary": "#f9b208",
        "success": "#7fb800",
        "warning": "#f5b700",
        "danger": "#e63946",
        "accent": "#533483",
        "cyan": "#06ffa5",
        "chart": ["#f9b208", "#7fb800", "#06ffa5", "#e63946", "#bb9af7",
                  "#2ac3de", "#ff9e64", "#f5b700"],
        "rx": "#7fb800",
        "tx": "#f5b700",
        "ai": "#bb9af7",
        "user": "#2ac3de",
        "log_dim": "#a6adc8",
    },
}


def get_theme(name: str) -> dict:
    """返回指定主题的设计令牌字典（兼容旧 API）。"""
    return THEMES.get(name, THEMES["dark"])


def get_base_color(key: str) -> str:
    """直接读取 BASE_COLORS 令牌。"""
    return BASE_COLORS.get(key, "#000000")


def chart_color(index: int, theme_name: str | None = None) -> str:
    """返回波形/图表第 index 条曲线的颜色（按主题调色板取模循环）。

    theme_name 省略时跟随当前生效主题（见 set_current_theme）。
    """
    t = get_theme(theme_name or _CURRENT_THEME)
    palette = t.get("chart") or CHART_PALETTES["dark"]
    return palette[index % len(palette)]


def spacing(key: str) -> int:
    """读取间距令牌。"""
    return SPACING.get(key, 8)


def radius(key: str) -> str:
    """读取圆角令牌。"""
    return RADII.get(key, "4px")


def font_size(key: str) -> str:
    """读取字号令牌。"""
    return TYPOGRAPHY.get(f"size_{key}", TYPOGRAPHY["size_body"])


# ═══════════════════════════════════════════════════════════════════
# 当前主题状态 — 供 pyqtgraph / 内联样式 / 图表调色板等运行时消费
# ═══════════════════════════════════════════════════════════════════

_CURRENT_THEME = "dark"


def set_current_theme(name: str) -> None:
    """记录当前生效主题（build_stylesheet 会自动调用，一般无需手动调）。"""
    global _CURRENT_THEME
    if name in THEMES:
        _CURRENT_THEME = name


def current_theme() -> str:
    """返回当前生效主题名。"""
    return _CURRENT_THEME


def ui_color(role: str, theme_name: str | None = None) -> str:
    """读取语义角色色（rx/tx/ai/user/log_dim 及 THEMES 既有键）。

    供无法用 QSS 级联覆盖的内联样式（代码着色、聊天气泡等）使用，
    避免在视图里硬编码 hex。
    """
    t = get_theme(theme_name or _CURRENT_THEME)
    return t.get(role, t["text"])


def apply_pyqtgraph_theme(theme_name: str | None = None) -> None:
    """把 pyqtgraph 全局背景/前景对齐到当前主题。

    只影响之后新建的 PlotWidget；已存在的图表需各自重新着色
    （RealtimePlotWidget.apply_theme / WaveformWidget.apply_theme）。
    """
    t = get_theme(theme_name or _CURRENT_THEME)
    try:
        import pyqtgraph as pg
        pg.setConfigOption("background", t["bg_alt"])
        pg.setConfigOption("foreground", t["text_dim"])
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════
# QSS 样式表生成
# ═══════════════════════════════════════════════════════════════════

def build_stylesheet(theme_name: str) -> str:
    """生成 QSS 样式表。

    设计原则：
      - 1px 边框优先于阴影卡片（cockpit 风）
      - 等宽字体用于所有数值和输入
      - 按钮层级：primary(solid 强调色) / default(outline) / danger(solid 红)
      - 状态指示用左侧色条（不用 badge）
    """
    t = get_theme(theme_name)
    set_current_theme(theme_name)
    B = BASE_COLORS  # 直接引用 Base 令牌
    S = SPACING
    R = RADII
    T = TYPOGRAPHY
    return f"""
    /* ═══ 全局 ═══ */
    QWidget {{
        background-color: {t['bg']};
        color: {t['text']};
        font-family: {T['font_family']};
        font-size: {T['size_body']};
    }}
    QMainWindow {{
        background-color: {t['bg']};
    }}

    /* ═══ 菜单栏 ═══ */
    QMenuBar {{
        background-color: {t['bg_alt']};
        color: {t['text']};
        border-bottom: 1px solid {t['border']};
        padding: {S['xs']}px {S['sm']}px;
    }}
    QMenuBar::item:selected {{
        background-color: {t['primary']};
        color: {t['bg']};
    }}
    QMenu {{
        background-color: {t['bg_alt']};
        border: 1px solid {t['border']};
        padding: {S['xs']}px 0;
    }}
    QMenu::item {{
        padding: {S['sm']}px {S['xl']}px;
    }}
    QMenu::item:selected {{
        background-color: {t['primary']};
        color: {t['bg']};
    }}
    QMenu::separator {{
        height: 1px;
        background: {t['border']};
        margin: {S['xs']}px {S['md']}px;
    }}

    /* ═══ 工具栏 ═══ */
    QToolBar {{
        background-color: {t['bg_alt']};
        border-bottom: 1px solid {t['border']};
        padding: {S['sm']}px;
        spacing: {S['sm']}px;
    }}

    /* ═══ 按钮 ═══ */
    QPushButton {{
        background-color: {t['surface']};
        color: {t['text']};
        border: 1px solid {t['border']};
        border-radius: {R['button']};
        padding: {S['sm']}px {S['lg']}px;
        min-height: 24px;
    }}
    QPushButton:hover {{
        background-color: {t['border']};
        border-color: {B['fg_secondary']};
    }}
    QPushButton:pressed {{
        background-color: {t['primary']};
        color: {t['bg']};
    }}
    QPushButton:disabled {{
        color: {B['fg_muted']};
        background-color: {t['bg_alt']};
    }}
    /* 语义按钮 */
    QPushButton#btn_primary {{
        background-color: {t['primary']};
        color: {t['bg']};
        border-color: {t['primary']};
        font-weight: {T['weight_bold']};
    }}
    QPushButton#btn_primary:hover {{
        background-color: {B['accent_dim']};
    }}
    QPushButton#btn_success {{
        background-color: {B['ok']};
        color: {t['bg']};
        border-color: {B['ok']};
    }}
    QPushButton#btn_success:hover {{
        background-color: {B['ok_dim']};
    }}
    QPushButton#btn_danger {{
        background-color: {B['fault']};
        color: white;
        border-color: {B['fault']};
    }}
    QPushButton#btn_danger:hover {{
        background-color: {B['fault_dim']};
    }}
    QPushButton#btn_warning {{
        background-color: {B['warn']};
        color: {t['bg']};
        border-color: {B['warn']};
    }}

    /* ═══ GroupBox — 1px 顶边 + 底分隔替代厚重卡片框 ═══ */
    QGroupBox {{
        background-color: {t['bg_alt']};
        border: 1px solid {t['border']};
        border-radius: {R['card']};
        margin-top: 14px;
        padding: {S['lg']}px {S['xl']}px {S['md']}px {S['xl']}px;
        font-weight: {T['weight_bold']};
        color: {t['text']};
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: {S['lg']}px;
        padding: 0 {S['sm']}px;
        color: {t['primary']};
    }}

    /* ═══ 标签 ═══ */
    QLabel {{
        background: transparent;
    }}
    QLabel#title {{
        font-size: {T['size_lg']};
        font-weight: {T['weight_bold']};
        color: {t['primary']};
    }}
    QLabel#value {{
        font-size: {T['size_value']};
        font-weight: {T['weight_bold']};
        font-family: {T['font_mono']};
    }}
    QLabel#unit {{
        font-size: {T['size_sm']};
        color: {t['text_dim']};
    }}
    QLabel#dim {{ color: {t['text_dim']}; }}
    QLabel#hint {{ color: {t['cyan']}; padding: {S['sm']}px; }}
    QLabel[role="ok"] {{ color: {B['ok']}; }}
    QLabel[role="warn"] {{ color: {B['warn']}; }}
    QLabel[role="err"] {{ color: {B['fault']}; }}
    QLabel#strong {{ font-weight: {T['weight_bold']}; color: {t['text']}; }}
    QLabel#body {{
        color: {t['text_dim']};
        font-size: {T['size_body']};
        padding: {S['xl']}px;
    }}

    /* ═══ 输入框 — 统一等宽字体 ═══ */
    QLineEdit, QSpinBox, QDoubleSpinBox {{
        background-color: {t['bg']};
        color: {t['text']};
        border: 1px solid {t['border']};
        border-radius: {R['input']};
        padding: {S['sm']}px {S['md']}px;
        font-family: {T['font_mono']};
        font-size: {T['size_sm']};
    }}
    QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
        border-color: {t['primary']};
        background-color: {B['accent_bg']};
    }}

    /* ═══ 下拉框 ═══ */
    QComboBox {{
        background-color: {t['surface']};
        color: {t['text']};
        border: 1px solid {t['border']};
        border-radius: {R['input']};
        padding: {S['sm']}px {S['md']}px;
        font-size: {T['size_sm']};
    }}
    QComboBox:hover {{ border-color: {B['fg_secondary']}; }}
    QComboBox:focus {{ border-color: {t['primary']}; }}
    QComboBox QAbstractItemView {{
        background-color: {t['bg_alt']};
        border: 1px solid {t['border']};
        selection-background-color: {t['primary']};
        selection-color: {t['bg']};
        outline: none;
    }}
    QComboBox::drop-down {{
        subcontrol-origin: padding;
        subcontrol-position: top right;
        width: 20px;
        border-left: 1px solid {t['border']};
    }}

    /* ═══ Tab 页签 ═══ */
    QTabWidget::pane {{
        border: 1px solid {t['border']};
        background-color: {t['bg']};
    }}
    QTabBar::tab {{
        background-color: {t['bg_alt']};
        color: {t['text_dim']};
        padding: {S['sm']}px {S['xl']}px;
        border: 1px solid {t['border']};
        border-bottom: none;
        border-top-left-radius: {R['input']};
        border-top-right-radius: {R['input']};
        margin-right: {S['xs']}px;
    }}
    QTabBar::tab:selected {{
        background-color: {t['bg']};
        color: {t['primary']};
        border-bottom: 2px solid {t['primary']};
    }}
    QTabBar::tab:hover {{
        color: {t['text']};
    }}

    /* ═══ 表格 ═══ */
    QTableWidget {{
        background-color: {t['bg']};
        alternate-background-color: {t['bg_alt']};
        gridline-color: {t['border']};
        border: 1px solid {t['border']};
        font-family: {T['font_mono']};
        font-size: {T['size_sm']};
    }}
    QTableWidget::item:selected {{
        background-color: {t['primary']};
        color: {t['bg']};
    }}
    QHeaderView::section {{
        background-color: {t['bg_alt']};
        color: {t['text']};
        border: none;
        border-bottom: 2px solid {t['border']};
        border-right: 1px solid {t['border']};
        padding: {S['sm']}px {S['md']}px;
        font-weight: {T['weight_bold']};
        font-size: {T['size_xs']};
    }}

    /* ═══ 滚动条 ═══ */
    QScrollBar:vertical {{
        background: {t['bg_alt']};
        width: 8px;
        margin: 0;
    }}
    QScrollBar::handle:vertical {{
        background: {t['border']};
        min-height: 24px;
        border-radius: 4px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {B['fg_secondary']};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0px;
    }}
    QScrollBar:horizontal {{
        background: {t['bg_alt']};
        height: 8px;
        margin: 0;
    }}
    QScrollBar::handle:horizontal {{
        background: {t['border']};
        min-width: 24px;
        border-radius: 4px;
    }}

    /* ═══ 状态栏 ═══ */
    QStatusBar {{
        background-color: {t['bg_alt']};
        color: {t['text_dim']};
        border-top: 1px solid {t['border']};
        font-size: {T['size_sm']};
        padding: {S['xs']}px;
    }}

    /* ═══ 文本编辑区 ═══ */
    QTextEdit, QPlainTextEdit {{
        background-color: {t['bg_alt']};
        color: {t['text']};
        border: 1px solid {t['border']};
        border-radius: {R['input']};
        font-family: {T['font_mono']};
        font-size: {T['size_sm']};
        selection-background-color: {t['primary']};
        selection-color: {t['bg']};
    }}

    /* ═══ 复选框 ═══ */
    QCheckBox {{
        spacing: {S['md']}px;
    }}
    QCheckBox::indicator {{
        width: 16px;
        height: 16px;
        border: 1px solid {t['border']};
        border-radius: 2px;
        background-color: {t['bg']};
    }}
    QCheckBox::indicator:checked {{
        background-color: {t['primary']};
        border-color: {t['primary']};
    }}

    /* ═══ 进度条 ═══ */
    QProgressBar {{
        background-color: {t['bg_alt']};
        border: 1px solid {t['border']};
        border-radius: {R['input']};
        text-align: center;
        font-size: {T['size_xs']};
        height: 16px;
    }}
    QProgressBar::chunk {{
        background-color: {t['primary']};
        border-radius: 2px;
    }}

    /* ═══ 卡片面板 ═══ */
    QFrame#card {{
        background-color: {t['bg_alt']};
        border: 1px solid {t['border']};
        border-radius: {R['panel']};
    }}

    /* ═══ 列表控件 ═══ */
    QListWidget {{
        background-color: {t['bg']};
        border: 1px solid {t['border']};
        border-radius: {R['input']};
        font-size: {T['size_sm']};
        outline: none;
    }}
    QListWidget::item {{
        padding: {S['sm']}px {S['md']}px;
    }}
    QListWidget::item:selected {{
        background-color: {t['primary']};
        color: {t['bg']};
    }}
    QListWidget::item:hover {{
        background-color: {t['surface']};
    }}

    /* ═══ 分割器 ═══ */
    QSplitter::handle {{
        background-color: {t['border']};
    }}
    QSplitter::handle:horizontal {{ width: 1px; }}
    QSplitter::handle:vertical {{ height: 1px; }}

    /* ═══ 工具提示 ═══ */
    QToolTip {{
        background-color: {t['bg_alt']};
        color: {t['text']};
        border: 1px solid {t['border']};
        padding: {S['sm']}px;
        font-size: {T['size_xs']};
    }}
    """

