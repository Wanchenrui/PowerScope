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
    # 暗色基底（工业 cockpit）— 相邻两级对比度 ≥1.18:1。
    # 旧值 card/bg 仅 1.05:1、边框/背景 1.41:1，「抬升」在密集数据界面上感知不到。
    "slate_950": "#0b0d12",   # 最深底（窗口背景）
    "slate_900": "#171c28",   # 次级底（面板/卡片）
    "slate_850": "#20253a",   # 抬高底（GroupBox/工具栏/按钮面）
    "slate_800": "#2a3046",   # 悬浮底（hover）
    "slate_700": "#3a4157",   # 边框
    "slate_600": "#4a5170",   # 激活边框 / 卡片顶边提亮

    # 前景/文字
    "fg_primary": "#dce0e8",    # 主文字（off-white，不纯白）
    "fg_secondary": "#959aa8",  # 次级文字（6.86:1）
    "fg_muted": "#767b8a",      # 禁用/占位符（4.57:1，达 WCAG AA）
    "fg_inverse": "#0c0e14",    # 反色文字（在强调色背景上）

    # 唯一强调色 — 青蓝（示波器/工控台传统色）
    "accent": "#00b4d8",        # 主强调（按钮/链接/选中）
    "accent_dim": "#007c99",    # 深强调（按下态）
    "accent_bg": "#0a1a22",     # 强调色底（标签背景）

    # 语义状态色 — 电力行业惯例
    "ok": "#2ecc71",            # 正常/运行（绿）
    "ok_dim": "#1a7a42",        # 深绿（浅色主题用）
    "ok_bg": "#0a1f12",        # 绿底
    "warn": "#f0c040",          # 告警（黄）
    "warn_dim": "#9a7a20",      # 深黄（浅色主题用）
    "warn_bg": "#1f1a08",
    "fault": "#e74c3c",         # 故障（红）
    "fault_dim": "#8b1f15",     # 深红（浅色主题用）
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
        **{f"chart{i + 1}": c for i, c in enumerate(CHART_PALETTES["dark"])},
        # 语义角色色（串口收发/日志/AI 对话等内联样式消费）
        "rx": BASE_COLORS["ok"],
        "tx": BASE_COLORS["warn"],
        "ai": "#9b59b6",
        "user": BASE_COLORS["info"],
        "log_dim": BASE_COLORS["fg_secondary"],
        # 深浅档 — 语义按钮 hover / 按下态
        "primary_dim": BASE_COLORS["accent_dim"],
        "success_dim": BASE_COLORS["ok_dim"],
        "warning_dim": BASE_COLORS["warn_dim"],
        "danger_dim": BASE_COLORS["fault_dim"],
        # 语义底色 — Toast / 告警行 / 安全停机条消费
        "ok_bg": BASE_COLORS["ok_bg"],
        "warn_bg": BASE_COLORS["warn_bg"],
        "fault_bg": BASE_COLORS["fault_bg"],
        "accent_bg": BASE_COLORS["accent_bg"],
        # 卡片顶边（比普通边框亮一档，制造浮起感）
        "border_top": BASE_COLORS["slate_600"],
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
        **{f"chart{i + 1}": c for i, c in enumerate(CHART_PALETTES["light"])},
        "rx": BASE_COLORS["ok_dim"],
        "tx": BASE_COLORS["warn_dim"],
        "ai": "#6c3483",
        "user": "#2e86c1",
        "log_dim": BASE_COLORS["light_text_dim"],
        # 浅色主题的 hover 档必须在已加深的语义色基础上再压暗
        "primary_dim": "#005f77",
        "success_dim": "#125c30",
        "warning_dim": "#755c18",
        "danger_dim": "#6b180f",
        # 浅色主题的语义底色（低饱和淡色，避免把文字对比度吃掉）
        "ok_bg": "#e8f6ee",
        "warn_bg": "#fdf6e0",
        "fault_bg": "#fbeae7",
        "accent_bg": "#e3f4fa",
        # 浅色界面不适用"顶边更亮"，用同色保持克制
        "border_top": BASE_COLORS["light_border"],
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
        "chart": ["#f9b208", "#2ecc71", "#06ffa5", "#e63946", "#bb9af7",
                  "#2ac3de", "#ff9e64", "#f5b700"],
        **{f"chart{i + 1}": c for i, c in enumerate(
            ["#f9b208", "#2ecc71", "#06ffa5", "#e63946", "#bb9af7",
             "#2ac3de", "#ff9e64", "#f5b700"])},
        # 语义色与 dark/light 统一色相（翠绿），仅明度随主题调整
        "rx": "#2ecc71",
        "tx": "#f5b700",
        "ai": "#bb9af7",
        "user": "#2ac3de",
        "log_dim": "#a6adc8",
        "primary_dim": "#c98f06",
        "success_dim": "#1a7a42",
        "warning_dim": "#a87e00",
        "danger_dim": "#a82730",
        "ok_bg": "#0d2417",
        "warn_bg": "#241d07",
        "fault_bg": "#2a0f0e",
        "accent_bg": "#0a1a22",
        "border_top": "#6b4a9e",
    },
}


# ═══════════════════════════════════════════════════════════════
# Layer 2.5: 语义色名与旧 hex 迁移
# ═══════════════════════════════════════════════════════════════

#: 可直接写进 profile 的颜色语义名 —— 比 hex 可读，且自动跟随主题切换
SEMANTIC_COLOR_NAMES = (
    "primary", "accent", "success", "warning", "danger", "info",
    "rx", "tx", "ai", "user", "text", "text_dim",
    "ok", "warn", "fault",
) + tuple(f"chart{i}" for i in range(1, 9))

#: 历史 hex → 语义名。项目早期把 Tokyo Night 调色板直接写进了 profile，
#: 那些值在暗色底上 7~10:1、在浅色底上 1.31~2.53:1（不可见）。
#: 做一次迁移映射，存量 YAML 无需手改即可在浅色主题下正常显示。
LEGACY_HEX_TO_SEMANTIC = {
    "#7aa2f7": "chart6",   # 蓝
    "#7dcfff": "chart1",   # 青
    "#9ece6a": "chart2",   # 绿
    "#bb9af7": "chart5",   # 紫
    "#e0af68": "chart3",   # 黄
    "#f7768e": "chart4",   # 红
    "#00ff00": "success",  # 纯绿（device_profile 的 color_on 默认值）
    "#ff0000": "danger",
    "#666666": "text_dim",  # device_profile 的 color_off 默认值
}


def resolve_color(value, fallback: str = "primary") -> str:
    """把 profile 里的颜色值解析成当前主题可用的 hex。

    接受三种输入：
      - 语义名（"success" / "chart3" / "text_dim"）→ 取主题令牌，随主题切换
      - 历史 hex（"#9ece6a"）→ 经 LEGACY_HEX_TO_SEMANTIC 迁移到语义名
      - 其它 hex → 作者显式指定，原样返回（不随主题变，用于刻意固定的色）
    空值 → fallback 语义名。
    """
    if not value:
        return ui_color(fallback)
    v = str(value).strip()
    low = v.lower()
    if low in LEGACY_HEX_TO_SEMANTIC:
        v = LEGACY_HEX_TO_SEMANTIC[low]
    if v in SEMANTIC_COLOR_NAMES:
        return ui_color(v)
    return v


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


def icons_dir() -> str:
    """UI 图标目录的绝对路径（POSIX 形式），兼容 PyInstaller 打包环境。

    QSS 的 image: url() 只接受文件系统路径，且反斜杠/相对路径在
    frozen 环境下不可靠，统一返回正斜杠绝对路径。
    """
    import sys
    from pathlib import Path
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", None)
        if base:
            bundled = Path(base) / "power_scope" / "ui" / "icons"
            if bundled.is_dir():
                return bundled.as_posix()
    return (Path(__file__).resolve().parent / "icons").as_posix()


def build_palette(theme_name: str) -> QPalette:
    """构造与主题一致的应用级 QPalette。

    QSS 只覆盖显式列出的控件；原生绘制通道（未样式化的箭头 glyph、
    复选框勾、禁用文字、原生对话框部件等）仍读应用调色板。
    不设置深色 palette 时，默认浅色调色板的 ButtonText/WindowText 为黑色，
    在深色主题下表现为「黑色箭头/看不清的按钮」。
    """
    t = get_theme(theme_name)
    B = BASE_COLORS
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(t["bg"]))
    pal.setColor(QPalette.WindowText, QColor(t["text"]))
    pal.setColor(QPalette.Base, QColor(t["bg_alt"]))
    pal.setColor(QPalette.AlternateBase, QColor(t["surface"]))
    pal.setColor(QPalette.Text, QColor(t["text"]))
    pal.setColor(QPalette.Button, QColor(t["surface"]))
    pal.setColor(QPalette.ButtonText, QColor(t["text"]))
    pal.setColor(QPalette.Highlight, QColor(t["primary"]))
    pal.setColor(QPalette.HighlightedText,
                 QColor("#ffffff" if theme_name == "light" else t["bg"]))
    pal.setColor(QPalette.ToolTipBase, QColor(t["bg_alt"]))
    pal.setColor(QPalette.ToolTipText, QColor(t["text"]))
    pal.setColor(QPalette.PlaceholderText, QColor(t["text_dim"]))
    pal.setColor(QPalette.BrightText, QColor(B["fault"]))
    pal.setColor(QPalette.Link, QColor(t["primary"]))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        pal.setColor(QPalette.Disabled, role, QColor(B["fg_muted"]))
    return pal


def ui_color(role: str, theme_name: str | None = None) -> str:
    """读取语义角色色（rx/tx/ai/user/log_dim 及 THEMES 既有键）。

    供无法用 QSS 级联覆盖的内联样式（代码着色、聊天气泡等）使用，
    避免在视图里硬编码 hex。
    """
    t = get_theme(theme_name or _CURRENT_THEME)
    return t.get(role, t["text"])


def style_plot_widget(plot, theme_name: str | None = None,
                      grid_alpha: float = 0.55) -> None:
    """把 pyqtgraph PlotWidget 的背景/网格/坐标轴/图例对齐到当前主题。

    只设全局 setConfigOption("background"/"foreground") 是不够的：
    pyqtgraph 的网格线由 AxisItem 自己画进 picture，颜色跟随 axis pen，
    所以必须遍历四个轴显式 setPen / setTextPen，否则切主题时网格不变色，
    界面上会多出一套与 border 令牌不一致的灰。
    """
    t = get_theme(theme_name or _CURRENT_THEME)
    try:
        import pyqtgraph as pg
    except Exception:
        return
    try:
        plot.setBackground(t["bg_alt"])
        for axis_name in ("left", "bottom", "right", "top"):
            ax = plot.getAxis(axis_name)
            if ax is None:
                continue
            ax.setPen(pg.mkPen(t["border"], width=1))
            ax.setTextPen(pg.mkPen(t["text_dim"]))
            try:
                ax.setGrid(grid_alpha)
            except Exception:
                pass
        legend = plot.getPlotItem().legend
        if legend is not None:
            for sample, label in legend.items:
                try:
                    sample.setPen(pg.mkPen(t["border"]))
                    label.setText(pg.mkPen(t["text"]))
                except Exception:
                    pass
    except Exception:
        pass


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
      - 所有箭头子控件（下拉框/SpinBox）显式指定图标，
        不留原生回退（否则深底上出现黑色不可见箭头）
    """
    t = get_theme(theme_name)
    set_current_theme(theme_name)
    B = BASE_COLORS  # 直接引用 Base 令牌
    S = SPACING
    R = RADII
    T = TYPOGRAPHY
    icons = icons_dir()
    # light 主题底为浅色 → 用深色字形；dark/solar → 浅色字形
    _g = "_dark" if theme_name == "light" else ""
    arrow_up = f"{icons}/arrow_up{_g}.png"
    arrow_down = f"{icons}/arrow_down{_g}.png"
    arrow_up_dim = f"{icons}/arrow_up{_g}_dim.png"
    arrow_down_dim = f"{icons}/arrow_down{_g}_dim.png"
    # 复选框对勾：勾的颜色取决于 indicator 底色（= primary）的明暗。
    # dark/solar 的 primary 是亮青 → 用深色勾；light 的 primary 是深青 → 用浅色勾。
    # 注意与箭头的 _dark 命名方向相反，故这里不用 _g，直接按主题取语义名。
    _chk = "light" if theme_name == "light" else "dark"
    check = f"{icons}/check_{_chk}.png"
    check_dim = f"{icons}/check_{_chk}_dim.png"
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
        border-color: {t['bg_alt']};
    }}
    QComboBox:disabled, QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{
        border-color: {t['bg_alt']};
    }}
    /* ═══ 连接按钮 — 由动态属性 state 驱动，替代 objectName hack ═══ */
    QPushButton[state="idle"] {{
        background-color: {t['success']};
        color: {t['bg']};
        border-color: {t['success']};
    }}
    QPushButton[state="idle"]:hover {{ background-color: {t['success_dim']}; }}
    QPushButton[state="connecting"] {{
        background-color: {t['surface']};
        color: {t['text_dim']};
        border-color: {t['border']};
    }}
    QPushButton[state="connected"] {{
        background-color: {t['danger']};
        color: {t['bg']};
        border-color: {t['danger']};
    }}
    QPushButton[state="connected"]:hover {{ background-color: {t['danger_dim']}; }}
    QPushButton[state="retry"] {{
        background-color: {t['warning']};
        color: {t['bg']};
        border-color: {t['warning']};
    }}
    QPushButton[state="retry"]:hover {{ background-color: {t['warning_dim']}; }}
    QPushButton[state="connecting"]:disabled {{
        color: {t['text_dim']};
        background-color: {t['surface']};
        border-color: {t['border']};
    }}

    /* 语义按钮 — 一律走 t['success'/'warning'/'danger']，随主题切换深浅档。
       旧写法直读 BASE_COLORS，导致浅色主题下语义按钮仍是暗色专用饱和色。 */
    QPushButton#btn_primary {{
        background-color: {t['primary']};
        color: {t['bg']};
        border-color: {t['primary']};
        font-weight: {T['weight_bold']};
    }}
    QPushButton#btn_primary:hover {{
        background-color: {t['primary_dim']};
    }}
    QPushButton#btn_success {{
        background-color: {t['success']};
        color: {t['bg']};
        border-color: {t['success']};
    }}
    QPushButton#btn_success:hover {{
        background-color: {t['success_dim']};
    }}
    QPushButton#btn_danger {{
        background-color: {t['danger']};
        color: {t['bg']};
        border-color: {t['danger']};
    }}
    QPushButton#btn_danger:hover {{
        background-color: {t['danger_dim']};
    }}
    QPushButton#btn_warning {{
        background-color: {t['warning']};
        color: {t['bg']};
        border-color: {t['warning']};
    }}
    QPushButton#btn_warning:hover {{
        background-color: {t['warning_dim']};
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
    QLabel[role="ok"] {{ color: {t['success']}; }}
    QLabel[role="warn"] {{ color: {t['warning']}; }}
    QLabel[role="err"] {{ color: {t['danger']}; }}
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
    QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{
        color: {B['fg_muted']};
        background-color: {t['bg_alt']};
    }}

    /* ═══ SpinBox 步进按钮 — 显式图标 + 可见按钮面 ═══ */
    QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{
        subcontrol-origin: border;
        width: 18px;
        background-color: {t['surface']};
        border-left: 1px solid {t['border']};
    }}
    QAbstractSpinBox::up-button {{
        subcontrol-position: top right;
        border-bottom: 1px solid {t['border']};
        border-top-right-radius: {R['input']};
    }}
    QAbstractSpinBox::down-button {{
        subcontrol-position: bottom right;
        border-bottom-right-radius: {R['input']};
    }}
    QAbstractSpinBox::up-button:hover, QAbstractSpinBox::down-button:hover {{
        background-color: {t['border']};
    }}
    QAbstractSpinBox::up-button:pressed, QAbstractSpinBox::down-button:pressed {{
        background-color: {t['primary']};
    }}
    QAbstractSpinBox::up-arrow {{
        image: url({arrow_up});
        width: 10px;
        height: 10px;
    }}
    QAbstractSpinBox::down-arrow {{
        image: url({arrow_down});
        width: 10px;
        height: 10px;
    }}
    QAbstractSpinBox::up-arrow:disabled, QAbstractSpinBox::up-arrow:off {{
        image: url({arrow_up_dim});
    }}
    QAbstractSpinBox::down-arrow:disabled, QAbstractSpinBox::down-arrow:off {{
        image: url({arrow_down_dim});
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
    QComboBox:disabled {{
        color: {B['fg_muted']};
        background-color: {t['bg_alt']};
    }}
    QComboBox QAbstractItemView {{
        background-color: {t['bg_alt']};
        border: 1px solid {t['border']};
        selection-background-color: {t['primary']};
        selection-color: {t['bg']};
        outline: none;
    }}
    /* 下拉按钮区：独立底色 + 分隔线，确保在深底上可辨识 */
    QComboBox::drop-down {{
        subcontrol-origin: padding;
        subcontrol-position: top right;
        width: 24px;
        background-color: {t['bg_alt']};
        border-left: 1px solid {t['border']};
        border-top-right-radius: {R['input']};
        border-bottom-right-radius: {R['input']};
    }}
    QComboBox::drop-down:hover {{
        background-color: {t['border']};
    }}
    QComboBox::drop-down:disabled {{
        background-color: {t['bg']};
    }}
    QComboBox::down-arrow {{
        image: url({arrow_down});
        width: 12px;
        height: 12px;
    }}
    QComboBox::down-arrow:disabled {{
        image: url({arrow_down_dim});
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
    /* 左侧竖排导航（QTabWidget West）：选中指示条必须在靠内容区的右边 */
    QTabBar[tabPosition="West"]::tab:selected {{
        border-right: 2px solid {t['primary']};
        border-bottom: 1px solid {t['border']};
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
    QHeaderView::section:last {{
        border-right: none;
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
        image: url({check});
        background-color: {t['primary']};
        border-color: {t['primary']};
    }}
    QCheckBox::indicator:checked:disabled {{
        image: url({check_dim});
        background-color: {t['bg_alt']};
        border-color: {t['border']};
    }}
    QCheckBox::indicator:unchecked:hover {{
        border-color: {B['fg_secondary']};
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
        border-radius: {R['input']};
    }}

    /* ═══ 卡片面板 ═══ */
    QFrame#card {{
        background-color: {t['bg_alt']};
        border: 1px solid {t['border']};
        border-top: 1px solid {t['border_top']};
        border-radius: {R['panel']};
    }}
    QGroupBox {{
        background-color: {t['bg_alt']};
        border: 1px solid {t['border']};
        border-top: 1px solid {t['border_top']};
        border-radius: {R['card']};
        margin-top: 14px;
        padding: {S['lg']}px {S['xl']}px {S['lg']}px {S['xl']}px;
        font-weight: {T['weight_bold']};
        color: {t['text']};
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: {S['lg']}px;
        padding: 0 {S['sm']}px;
        color: {t['text_dim']};
    }}

    /* ═══ 列表控件 ═══ */
    QListWidget {{
        background-color: {t['bg']};
        border: 1px solid {t['border']};
        border-radius: {R['input']};
        font-size: {T['size_sm']};
        outline: none;
    }}
    /* 焦点环 — outline:none 只去掉原生虚线框，可见焦点由下面的边框提亮补回 */
    QListWidget:focus, QTableWidget:focus, QTreeWidget:focus,
    QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus {{
        border-color: {t['primary']};
    }}
    QPushButton:focus {{
        border-color: {t['primary']};
        background-color: {t['surface']};
    }}
    QCheckBox:focus, QRadioButton:focus {{
        color: {t['primary']};
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

    /* ═══ 收发日志表格（串口监控中栏）═══ */
    QTableView {{
        background-color: {t['bg']};
        border: 1px solid {t['border']};
        border-radius: {R['input']};
        font-family: {T['font_mono']};
        font-size: {T['size_sm']};
        gridline-color: transparent;
        selection-background-color: {t['primary']};
        selection-color: {t['bg']};
    }}
    QTableView::item {{
        padding: 2px 6px;
        border: none;
    }}
    QTableView::item:selected {{
        background-color: {t['primary']};
        color: {t['bg']};
    }}
    QTableView::indicator {{
        width: 14px;
        height: 14px;
    }}

    /* ═══ 系统消息小日志（串口监控右栏）═══ */
    QPlainTextEdit#syslog {{
        background-color: {t['bg']};
        font-size: {T['size_xs']};
    }}

    /* ═══ Hex / ASCII 分段控件 ═══ */
    QPushButton#seg_first, QPushButton#seg_last {{
        padding: 3px 10px;
        min-height: 20px;
        border-radius: 0;
    }}
    QPushButton#seg_first {{
        border-top-left-radius: {R['input']};
        border-bottom-left-radius: {R['input']};
    }}
    QPushButton#seg_last {{
        border-top-right-radius: {R['input']};
        border-bottom-right-radius: {R['input']};
        border-left: none;
    }}
    QPushButton#seg_first:checked, QPushButton#seg_last:checked {{
        background-color: {t['primary']};
        color: {t['bg']};
        border-color: {t['primary']};
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

