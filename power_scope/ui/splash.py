"""splash.py — 启动加载界面

「软件开启过程需要有加载界面」：双击 exe 到主窗口可见之间，PySide6 应用
要加载配置、编译 QSS、构建 8+ 个视图、初始化采样/安全/会话服务 ——
冷启动 1~3 秒的「白屏+无响应」是半成品感最直接的来源。

加载界面（品牌卡 + 步骤进度 + 当前动作）把这段等待变成「可感知的启动」：
  1. 立即显示（QApplication 创建后第一件事）
  2. 每个初始化步骤推进度条与文案
  3. 主窗口 show() 后淡出关闭

样式全部走主题令牌（dark/light/solar 三主题一致）。
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, QPropertyAnimation
from PySide6.QtGui import QGuiApplication, QPixmap
from PySide6.QtWidgets import (
    QLabel, QProgressBar, QVBoxLayout, QWidget,
)

from .theme import RADII, SPACING, TYPOGRAPHY, get_theme, current_theme
from .widgets import tab_icons


#: 启动步骤（文案 + 进度百分比）——与 main.py 的初始化顺序一一对应
STARTUP_STEPS = (
    ("正在加载设备配置…", 10),
    ("正在初始化主题与设计令牌…", 25),
    ("正在启动会话与协议服务…", 45),
    ("正在构建调试界面…", 75),
    ("正在接线事件总线…", 90),
    ("就绪", 100),
)


class SplashScreen(QWidget):
    """无边框品牌加载卡，屏幕居中显示。"""

    def __init__(self, app_icon_path: str | None = None,
                 app_name: str = "PowerScope"):
        super().__init__(None, Qt.SplashScreen | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self._app_name = app_name
        self._icon_path = app_icon_path
        self._build(app_name)
        self._center()

    # ---- UI ----
    def _build(self, app_name: str):
        self.setFixedSize(420, 240)
        self.setObjectName("splash")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 26, 28, 22)
        lay.setSpacing(SPACING["md"])

        # 图标：优先 app.png，缺省时画矢量波形标
        self._icon = QLabel()
        self._icon.setFixedSize(56, 56)
        self._icon.setAlignment(Qt.AlignCenter)
        lay.addWidget(self._icon, 0, Qt.AlignHCenter)

        self._title = QLabel(app_name)
        self._title.setAlignment(Qt.AlignCenter)
        lay.addWidget(self._title, 0, Qt.AlignHCenter)

        self._subtitle = QLabel("电力电子调试工具")
        self._subtitle.setAlignment(Qt.AlignCenter)
        lay.addWidget(self._subtitle, 0, Qt.AlignHCenter)

        lay.addStretch(1)

        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._bar.setTextVisible(False)
        self._bar.setFixedHeight(4)
        lay.addWidget(self._bar)

        self._status = QLabel("正在启动…")
        self._status.setAlignment(Qt.AlignCenter)
        self._status.setWordWrap(True)
        lay.addWidget(self._status)

        self._apply_style()
        self._paint_icon()

    def _apply_style(self):
        t = get_theme(current_theme())
        self.setStyleSheet(
            f"QWidget#splash {{ background-color:{t['bg_alt']};"
            f"border:1px solid {t['border']};"
            f"border-top:2px solid {t['primary']};"
            f"border-radius:{RADII['panel']}; }}"
        )
        self._title.setStyleSheet(
            f"font-size:{TYPOGRAPHY['size_xl']};font-weight:"
            f"{TYPOGRAPHY['weight_bold']};color:{t['text']};"
            f"background:transparent;")
        self._subtitle.setStyleSheet(
            f"font-size:{TYPOGRAPHY['size_sm']};color:{t['text_dim']};"
            f"background:transparent;")
        self._status.setStyleSheet(
            f"font-size:{TYPOGRAPHY['size_sm']};color:{t['primary']};"
            f"background:transparent;")
        self._bar.setStyleSheet(
            f"QProgressBar {{ background-color:{t['bg']};"
            f"border:1px solid {t['border']};"
            f"border-radius:{RADII['input']}; }}"
            f"QProgressBar::chunk {{ background-color:{t['primary']};"
            f"border-radius:{RADII['input']}; }}")

    def _paint_icon(self):
        """加载 app.png；缺失则用主题色画波形图标。"""
        if self._icon_path:
            pixmap = QPixmap(self._icon_path)
            if not pixmap.isNull():
                self._icon.setPixmap(
                    pixmap.scaled(56, 56, Qt.KeepAspectRatio,
                                  Qt.SmoothTransformation))
                return
        from PySide6.QtCore import QRect
        from PySide6.QtGui import QColor, QPainter
        from .theme import ui_color
        px = QPixmap(56, 56)
        px.fill(Qt.transparent)
        painter = QPainter(px)
        painter.setRenderHint(QPainter.Antialiasing)
        tab_icons.draw_icon(painter, "wave", QRect(0, 0, 56, 56),
                            ui_color("primary"))
        painter.end()
        self._icon.setPixmap(px)

    def _center(self):
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        self.move(geo.center().x() - self.width() // 2,
                  geo.center().y() - self.height() // 2)

    # ---- 进度 ----
    def set_step(self, text: str, percent: int):
        """推进到某步骤（文案 + 百分比）。"""
        self._status.setText(text)
        self._bar.setValue(max(self._bar.value(), min(100, int(percent))))

    def advance(self, index: int):
        """按 STARTUP_STEPS 索引推进。"""
        if 0 <= index < len(STARTUP_STEPS):
            text, percent = STARTUP_STEPS[index]
            self.set_step(text, percent)

    def message(self, text: str):
        self._status.setText(text)

    def finish(self, main_window=None):
        """主窗口可见后淡出并关闭加载界面。"""
        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(160)
        self._fade.setStartValue(1.0)
        self._fade.setEndValue(0.0)
        self._fade.finished.connect(self.close)
        self._fade.start()
        self._splash_anim = self._fade
