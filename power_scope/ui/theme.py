"""PowerScope 设计令牌与 Qt 组件样式。"""

from pathlib import Path


BASE_COLORS = {
    "slate_950": "#0b1118",
    "slate_900": "#111a24",
    "slate_850": "#182430",
    "slate_800": "#223242",
    "slate_700": "#2c3d4e",
    "slate_600": "#43586d",
    "fg_primary": "#e5edf5",
    "fg_secondary": "#9aabbd",
    "fg_muted": "#6d7f91",
    "fg_inverse": "#071219",
    "accent": "#48c7e8",
    "accent_dim": "#25a8ca",
    "accent_bg": "#12323e",
    "ok": "#45cf91",
    "ok_dim": "#208557",
    "ok_bg": "#102d25",
    "warn": "#efbd60",
    "warn_dim": "#a87320",
    "warn_bg": "#302717",
    "fault": "#f0747e",
    "fault_dim": "#b83c4b",
    "fault_bg": "#351c24",
    "info": "#72a7f2",
    "light_bg": "#f3f6fa",
    "light_bg_alt": "#ffffff",
    "light_surface": "#e9eff5",
    "light_border": "#d3dde7",
    "light_text": "#1a2b3a",
    "light_text_dim": "#607487",
}

CHART_PALETTES = {
    "dark": [
        "#48c7e8", "#45cf91", "#efbd60", "#f0747e",
        "#ad8cf5", "#72a7f2", "#f59a66", "#4fd1c5",
    ],
    "light": [
        "#087f9c", "#187a4a", "#966309", "#b33545",
        "#7550b5", "#336fc0", "#b75820", "#177f78",
    ],
}

SPACING = {"xs": 2, "sm": 4, "md": 8, "lg": 12, "xl": 16, "2xl": 24}
RADII = {"input": "6px", "button": "6px", "card": "10px", "panel": "12px"}
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
    "size_value": "24px",
    "size_display": "38px",
    "weight_normal": "400",
    "weight_medium": "500",
    "weight_bold": "600",
}

THEMES = {
    "dark": {
        "bg": "#0b1118", "bg_alt": "#111a24", "surface": "#182430",
        "surface_hover": "#223242", "surface_active": "#2b4153",
        "input_bg": "#0d1620", "border": "#2c3d4e", "border_strong": "#43586d",
        "text": "#e5edf5", "text_dim": "#9aabbd", "text_faint": "#6d7f91",
        "primary": "#48c7e8", "primary_hover": "#74d8ef", "on_primary": "#071219",
        "success": "#45cf91", "warning": "#efbd60", "danger": "#f0747e",
        "accent": "#ad8cf5", "cyan": "#48c7e8", "info": "#72a7f2",
        "accent_bg": "#12323e", "success_bg": "#102d25", "warning_bg": "#302717",
        "danger_bg": "#351c24", "info_bg": "#172b42", "hero_bg": "#102630",
        "grid": "#293a49", "chart": CHART_PALETTES["dark"],
        "rx": "#45cf91", "tx": "#efbd60", "ai": "#ad8cf5",
        "user": "#72a7f2", "log_dim": "#9aabbd",
    },
    "light": {
        "bg": "#f3f6fa", "bg_alt": "#ffffff", "surface": "#e9eff5",
        "surface_hover": "#dfe9f2", "surface_active": "#d2e4ee",
        "input_bg": "#ffffff", "border": "#d3dde7", "border_strong": "#a7bacb",
        "text": "#1a2b3a", "text_dim": "#607487", "text_faint": "#8496a7",
        "primary": "#087f9c", "primary_hover": "#06667e", "on_primary": "#f4fcff",
        "success": "#187a4a", "warning": "#966309", "danger": "#b33545",
        "accent": "#7550b5", "cyan": "#087f9c", "info": "#336fc0",
        "accent_bg": "#dceff4", "success_bg": "#e0f3e9", "warning_bg": "#faf0d9",
        "danger_bg": "#f9e5e8", "info_bg": "#e4eefb", "hero_bg": "#e5f3f7",
        "grid": "#d9e3eb", "chart": CHART_PALETTES["light"],
        "rx": "#187a4a", "tx": "#966309", "ai": "#7550b5",
        "user": "#336fc0", "log_dim": "#607487",
    },
    "solar": {
        "bg": "#121923", "bg_alt": "#192532", "surface": "#233448",
        "surface_hover": "#2c4054", "surface_active": "#354d63",
        "input_bg": "#141f2a", "border": "#3a4d61", "border_strong": "#566c81",
        "text": "#f0eee8", "text_dim": "#b6b9b7", "text_faint": "#7f8c97",
        "primary": "#f2bd5b", "primary_hover": "#ffd57c", "on_primary": "#2a210e",
        "success": "#8bd59c", "warning": "#f2bd5b", "danger": "#f18a91",
        "accent": "#d3aef7", "cyan": "#55d6be", "info": "#82b4ed",
        "accent_bg": "#3b3323", "success_bg": "#20392c", "warning_bg": "#3c321e",
        "danger_bg": "#40252a", "info_bg": "#23384b", "hero_bg": "#2c2d28",
        "grid": "#38434e",
        "chart": ["#f2bd5b", "#8bd59c", "#55d6be", "#f18a91",
                  "#d3aef7", "#82b4ed", "#f59a66", "#f0d58c"],
        "rx": "#8bd59c", "tx": "#f2bd5b", "ai": "#d3aef7",
        "user": "#82b4ed", "log_dim": "#b6b9b7",
    },
}

_CURRENT_THEME = "dark"
_RESOURCE_DIR = Path(__file__).with_name("resources")


def get_theme(name: str | None = None) -> dict:
    return THEMES.get(name or _CURRENT_THEME, THEMES["dark"])


def get_base_color(key: str) -> str:
    return BASE_COLORS.get(key, "#000000")


def chart_color(index: int, theme_name: str | None = None) -> str:
    palette = get_theme(theme_name or _CURRENT_THEME).get("chart") or CHART_PALETTES["dark"]
    return palette[index % len(palette)]


def spacing(key: str) -> int:
    return SPACING.get(key, 8)


def radius(key: str) -> str:
    return RADII.get(key, "6px")


def font_size(key: str) -> str:
    return TYPOGRAPHY.get(f"size_{key}", TYPOGRAPHY["size_body"])


def set_current_theme(name: str) -> None:
    global _CURRENT_THEME
    if name in THEMES:
        _CURRENT_THEME = name


def current_theme() -> str:
    return _CURRENT_THEME


def ui_color(role: str, theme_name: str | None = None) -> str:
    theme = get_theme(theme_name or _CURRENT_THEME)
    return theme.get(role, theme["text"])


def apply_pyqtgraph_theme(theme_name: str | None = None) -> None:
    theme = get_theme(theme_name or _CURRENT_THEME)
    try:
        import pyqtgraph as pg
        pg.setConfigOption("background", theme["bg_alt"])
        pg.setConfigOption("foreground", theme["text_dim"])
    except Exception:
        pass


def build_stylesheet(theme_name: str) -> str:
    theme = get_theme(theme_name)
    set_current_theme(theme_name)
    t = theme
    s = SPACING
    r = RADII
    f = TYPOGRAPHY
    check_icon = (_RESOURCE_DIR / (
        "check_light.svg" if theme_name == "light" else "check_dark.svg"
    )).as_posix()
    return f"""
    QWidget {{
        color: {t['text']};
        font-family: {f['font_family']};
        font-size: {f['size_body']};
        selection-background-color: {t['primary']};
        selection-color: {t['on_primary']};
    }}
    QMainWindow, QDialog {{ background-color: {t['bg']}; }}
    QStackedWidget, QTabWidget {{ background-color: {t['bg']}; }}
    QScrollArea {{ background: transparent; border: none; }}
    QScrollArea > QWidget > QWidget {{ background: transparent; }}

    QMenuBar {{
        background-color: {t['bg']};
        border-bottom: 1px solid {t['border']};
        padding: 3px 10px;
    }}
    QMenuBar::item {{ background: transparent; padding: 5px 10px; border-radius: 5px; }}
    QMenuBar::item:selected {{ background-color: {t['surface_hover']}; color: {t['text']}; }}
    QMenuBar::item:pressed {{ background-color: {t['surface_active']}; }}
    QMenu {{
        background-color: {t['bg_alt']};
        border: 1px solid {t['border_strong']};
        border-radius: 8px;
        padding: 5px;
    }}
    QMenu::item {{ padding: 7px 26px 7px 12px; border-radius: 5px; }}
    QMenu::item:selected {{ background-color: {t['accent_bg']}; color: {t['primary']}; }}
    QMenu::item:disabled {{ color: {t['text_faint']}; }}
    QMenu::separator {{ height: 1px; background: {t['border']}; margin: 5px 8px; }}

    QToolBar {{
        background-color: {t['bg_alt']};
        border: none;
        border-bottom: 1px solid {t['border']};
        padding: 7px 12px;
        spacing: 8px;
    }}
    QToolBar#main_toolbar {{ padding: 10px 16px; spacing: 10px; }}
    QToolBar::separator {{ background: {t['border']}; width: 1px; margin: 6px 5px; }}
    QToolButton {{
        background: transparent; border: 1px solid transparent;
        border-radius: {r['button']}; padding: 6px;
    }}
    QToolButton:hover {{ background-color: {t['surface_hover']}; border-color: {t['border']}; }}
    QToolButton:pressed, QToolButton:checked {{ background-color: {t['accent_bg']}; color: {t['primary']}; }}

    QPushButton {{
        background-color: {t['surface']};
        color: {t['text']};
        border: 1px solid {t['border']};
        border-radius: {r['button']};
        padding: 5px 13px;
        min-height: 28px;
    }}
    QPushButton:hover {{ background-color: {t['surface_hover']}; border-color: {t['border_strong']}; }}
    QPushButton:pressed {{ background-color: {t['surface_active']}; border-color: {t['primary']}; }}
    QPushButton:focus {{ border: 1px solid {t['primary']}; }}
    QPushButton:disabled {{
        color: {t['text_faint']}; background-color: {t['bg_alt']}; border-color: {t['border']};
    }}
    QPushButton:checked {{ background-color: {t['accent_bg']}; color: {t['primary']}; border-color: {t['primary']}; }}
    QPushButton#btn_primary {{
        background-color: {t['primary']}; color: {t['on_primary']};
        border-color: {t['primary']}; font-weight: {f['weight_bold']};
    }}
    QPushButton#btn_primary:hover {{ background-color: {t['primary_hover']}; border-color: {t['primary_hover']}; }}
    QPushButton#btn_primary:pressed {{ background-color: {t['primary']}; }}
    QPushButton#btn_primary:disabled {{
        background-color: {t['surface']}; color: {t['text_faint']}; border-color: {t['border']};
    }}
    QPushButton#btn_success {{ background-color: {t['success_bg']}; color: {t['success']}; border-color: {t['success']}; }}
    QPushButton#btn_success:hover {{ background-color: {t['surface_hover']}; border-color: {t['success']}; }}
    QPushButton#btn_danger {{ background-color: {t['danger_bg']}; color: {t['danger']}; border-color: {t['danger']}; }}
    QPushButton#btn_danger:hover {{ background-color: {t['surface_hover']}; border-color: {t['danger']}; }}
    QPushButton#btn_warning {{ background-color: {t['warning_bg']}; color: {t['warning']}; border-color: {t['warning']}; }}
    QPushButton#btn_warning:hover {{ background-color: {t['surface_hover']}; }}
    QPushButton#btn_ghost {{ background: transparent; border-color: transparent; color: {t['text_dim']}; }}
    QPushButton#btn_ghost:hover {{ background-color: {t['surface_hover']}; color: {t['text']}; border-color: {t['border']}; }}

    QGroupBox {{
        background-color: {t['bg_alt']};
        border: 1px solid {t['border']};
        border-radius: {r['card']};
        margin-top: 16px;
        padding: 14px 14px 12px 14px;
        font-weight: {f['weight_medium']};
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 12px;
        padding: 0 5px;
        color: {t['text_dim']};
        font-size: {f['size_sm']};
        font-weight: {f['weight_bold']};
    }}
    QFrame#card {{
        background-color: {t['bg_alt']};
        border: 1px solid {t['border']};
        border-radius: {r['panel']};
    }}
    QFrame#hero_card {{
        background-color: {t['hero_bg']};
        border: 1px solid {t['primary']};
        border-radius: {r['panel']};
    }}
    QFrame#control_bar {{
        background-color: {t['bg_alt']};
        border: 1px solid {t['border']};
        border-radius: {r['card']};
    }}
    QFrame#inline_panel {{ background-color: {t['input_bg']}; border: 1px solid {t['border']}; border-radius: 8px; }}
    QFrame#status_badge {{ background-color: {t['surface']}; border: 1px solid {t['border']}; border-radius: 10px; }}
    QFrame#status_badge[tone="info"] {{ background-color: {t['accent_bg']}; border-color: {t['primary']}; }}
    QFrame#status_badge[tone="ok"] {{ background-color: {t['success_bg']}; border-color: {t['success']}; }}
    QFrame#status_badge[tone="warning"] {{ background-color: {t['warning_bg']}; border-color: {t['warning']}; }}
    QFrame#status_badge[tone="error"] {{ background-color: {t['danger_bg']}; border-color: {t['danger']}; }}
    QFrame#status_badge QLabel {{ background: transparent; border: none; }}

    QLabel {{ background: transparent; }}
    QLabel#brand_title {{ font-size: 19px; font-weight: 700; color: {t['text']}; }}
    QLabel#brand_subtitle {{ font-size: 10px; color: {t['text_faint']}; }}
    QLabel#device_name {{ font-size: {f['size_body']}; font-weight: {f['weight_bold']}; }}
    QLabel#page_header {{ background: transparent; }}
    QLabel#page_title {{ font-size: {f['size_2xl']}; font-weight: {f['weight_bold']}; color: {t['text']}; }}
    QLabel#page_subtitle {{ font-size: {f['size_sm']}; color: {t['text_dim']}; }}
    QLabel#title, QLabel#section_title {{ font-size: {f['size_md']}; font-weight: {f['weight_bold']}; color: {t['text']}; }}
    QLabel#eyebrow {{ font-size: {f['size_xs']}; font-weight: {f['weight_bold']}; color: {t['primary']}; }}
    QLabel#value, QLabel#metric_value {{
        font-family: {f['font_mono']}; font-size: {f['size_value']}; font-weight: {f['weight_bold']};
    }}
    QLabel#hero_value {{
        font-family: {f['font_mono']}; font-size: {f['size_display']}; font-weight: 700; color: {t['primary']};
    }}
    QLabel#state_value {{ font-family: {f['font_mono']}; font-size: {f['size_body']}; font-weight: {f['weight_bold']}; }}
    QLabel#unit {{ font-size: {f['size_sm']}; color: {t['text_dim']}; }}
    QLabel#dim {{ color: {t['text_dim']}; }}
    QLabel#stat_value {{ font-family: {f['font_mono']}; font-size: {f['size_xs']}; color: {t['text_dim']}; }}
    QLabel[role="dim"] {{ color: {t['text_dim']}; }}
    QLabel#muted {{ color: {t['text_faint']}; }}
    QLabel#hint {{ color: {t['text_dim']}; padding: 3px 0; font-size: {f['size_sm']}; }}
    QLabel#strong {{ font-weight: {f['weight_bold']}; color: {t['text']}; }}
    QLabel#body {{ color: {t['text_dim']}; font-size: {f['size_body']}; padding: 16px; }}
    QLabel#empty_state {{ color: {t['text_faint']}; padding: 24px 12px; font-size: {f['size_body']}; }}
    QLabel#metric_caption {{ color: {t['text_dim']}; font-size: {f['size_sm']}; }}
    QLabel[role="ok"] {{ color: {t['success']}; }}
    QLabel[role="warn"] {{ color: {t['warning']}; }}
    QLabel[role="err"] {{ color: {t['danger']}; }}
    QLabel[role="info"] {{ color: {t['primary']}; }}
    QLabel:disabled {{ color: {t['text_faint']}; }}

    QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
        background-color: {t['input_bg']};
        color: {t['text']};
        border: 1px solid {t['border']};
        border-radius: {r['input']};
        padding: 5px 9px;
        min-height: 28px;
        font-size: {f['size_sm']};
    }}
    QSpinBox, QDoubleSpinBox {{ font-family: {f['font_mono']}; }}
    QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {{
        color: {t['text_faint']}; background-color: {t['surface']};
    }}
    QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover {{ border-color: {t['border_strong']}; }}
    QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border: 1px solid {t['primary']}; }}
    QLineEdit[role="search"] {{ padding-left: 10px; }}
    QComboBox::drop-down {{ border: none; width: 25px; }}
    QComboBox QAbstractItemView {{
        background-color: {t['bg_alt']}; color: {t['text']};
        border: 1px solid {t['border_strong']}; border-radius: 6px;
        padding: 4px; outline: none;
        selection-background-color: {t['accent_bg']}; selection-color: {t['primary']};
    }}
    QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
        width: 17px; background: transparent; border: none;
    }}
    QSpinBox::up-button:hover, QSpinBox::down-button:hover,
    QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover {{ background-color: {t['surface_hover']}; }}

    QTabWidget::pane {{ border: none; background-color: {t['bg']}; }}
    QTabWidget#nav_tabs::pane {{ border-left: 1px solid {t['border']}; }}
    QTabBar::tab {{
        background: transparent; color: {t['text_dim']};
        padding: 7px 16px; border: none; border-bottom: 2px solid transparent;
    }}
    QTabBar::tab:selected {{ color: {t['primary']}; border-bottom-color: {t['primary']}; }}
    QTabBar::tab:hover {{ color: {t['text']}; background-color: {t['surface_hover']}; }}
    QTabBar#primary_nav {{ background-color: {t['bg_alt']}; border: none; }}
    QTabBar#primary_nav::tab {{ background: transparent; border: none; margin: 0; padding: 0; }}

    QAbstractItemView {{ outline: none; }}
    QTableWidget, QTreeWidget, QTableView, QTreeView, QListWidget {{
        background-color: {t['bg_alt']};
        alternate-background-color: {t['input_bg']};
        color: {t['text']};
        gridline-color: {t['border']};
        border: 1px solid {t['border']};
        border-radius: 7px;
        font-size: {f['size_sm']};
        selection-background-color: {t['accent_bg']};
        selection-color: {t['text']};
    }}
    QTableWidget, QTableView {{ font-family: {f['font_mono']}; }}
    QTableWidget::item, QTreeWidget::item, QListWidget::item {{ padding: 5px; border: none; }}
    QTableWidget::item:selected, QTreeWidget::item:selected, QListWidget::item:selected {{
        background-color: {t['accent_bg']}; color: {t['primary']};
    }}
    QTreeWidget::item:hover, QListWidget::item:hover, QTableWidget::item:hover {{ background-color: {t['surface_hover']}; }}
    QTreeWidget::branch {{ background: transparent; }}
    QHeaderView {{ background-color: {t['bg_alt']}; border: none; }}
    QHeaderView::section {{
        background-color: {t['surface']}; color: {t['text_dim']};
        border: none; border-bottom: 1px solid {t['border']}; border-right: 1px solid {t['border']};
        padding: 7px 8px; font-weight: {f['weight_bold']}; font-size: {f['size_xs']};
    }}
    QListWidget::item {{ min-height: 24px; }}
    QListWidget#alarm_list {{ background-color: {t['input_bg']}; }}
    QListWidget#alarm_list::item {{ padding: 7px 9px; }}

    QTextEdit, QPlainTextEdit {{
        background-color: {t['input_bg']}; color: {t['text']};
        border: 1px solid {t['border']}; border-radius: 8px;
        padding: 7px; font-family: {f['font_mono']}; font-size: {f['size_sm']};
        selection-background-color: {t['primary']}; selection-color: {t['on_primary']};
    }}
    QTextEdit:focus, QPlainTextEdit:focus {{ border-color: {t['primary']}; }}
    QTextEdit#chat_history {{ font-family: {f['font_family']}; font-size: {f['size_body']}; padding: 12px; }}

    QCheckBox, QRadioButton {{ background: transparent; spacing: 8px; min-height: 22px; }}
    QCheckBox::indicator, QRadioButton::indicator {{ width: 16px; height: 16px; }}
    QCheckBox::indicator {{
        border: 1px solid {t['border_strong']}; border-radius: 4px; background-color: {t['input_bg']};
    }}
    QCheckBox::indicator:hover, QRadioButton::indicator:hover {{ border-color: {t['primary']}; }}
    QCheckBox::indicator:checked {{
        background-color: {t['primary']}; border-color: {t['primary']}; image: url("{check_icon}");
    }}
    QCheckBox::indicator:disabled {{ background-color: {t['surface']}; border-color: {t['border']}; }}
    QRadioButton::indicator {{ border: 1px solid {t['border_strong']}; border-radius: 8px; background-color: {t['input_bg']}; }}
    QRadioButton::indicator:checked {{ border: 4px solid {t['primary']}; }}

    QSlider::groove:horizontal {{ height: 4px; background: {t['border']}; border-radius: 2px; }}
    QSlider::sub-page:horizontal {{ background: {t['primary']}; border-radius: 2px; }}
    QSlider::handle:horizontal {{
        background: {t['primary']}; border: 2px solid {t['bg_alt']};
        width: 14px; height: 14px; margin: -6px 0; border-radius: 8px;
    }}
    QSlider::handle:horizontal:hover {{ background: {t['primary_hover']}; }}
    QProgressBar {{
        background-color: {t['surface']}; color: {t['text_dim']};
        border: none; border-radius: 4px; text-align: center;
        font-size: {f['size_xs']}; min-height: 15px;
    }}
    QProgressBar::chunk {{ background-color: {t['primary']}; border-radius: 4px; }}
    QProgressBar[compact="true"] {{ min-height: 5px; max-height: 5px; }}

    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 3px; }}
    QScrollBar::handle:vertical {{ background: {t['border_strong']}; min-height: 30px; border-radius: 4px; }}
    QScrollBar::handle:vertical:hover {{ background: {t['text_faint']}; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 3px; }}
    QScrollBar::handle:horizontal {{ background: {t['border_strong']}; min-width: 30px; border-radius: 4px; }}
    QScrollBar::handle:horizontal:hover {{ background: {t['text_faint']}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

    QStatusBar {{
        background-color: {t['bg_alt']}; color: {t['text_dim']};
        border-top: 1px solid {t['border']}; padding: 3px 8px; font-size: {f['size_sm']};
    }}
    QStatusBar::item {{ border: none; }}
    QStatusBar QLabel {{ padding: 0 2px; }}
    QSplitter::handle {{ background: transparent; }}
    QSplitter::handle:horizontal {{ width: 7px; }}
    QSplitter::handle:vertical {{ height: 7px; }}
    QSplitter::handle:hover {{ background: {t['accent_bg']}; }}
    QToolTip {{
        background-color: {t['surface']}; color: {t['text']};
        border: 1px solid {t['border_strong']}; border-radius: 6px;
        padding: 6px 9px; font-size: {f['size_sm']};
    }}
    """
