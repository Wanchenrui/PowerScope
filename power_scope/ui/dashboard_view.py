"""仪表盘视图 — 配置驱动的多组件布局"""
from PySide6.QtWidgets import QWidget, QVBoxLayout, QGridLayout, QScrollArea
from PySide6.QtCore import Signal, QTimer

from .theme import spacing
from .widgets import (
    WaveformWidget, GaugeWidget, ButtonPanelWidget,
    StatusPanelWidget, InfoPanelWidget, ParamEditorWidget,
)


class DashboardView(QWidget):
    """仪表盘视图 — 从 DeviceProfile.dashboard 配置动态构建组件

    信号:
        button_clicked(id, action, value) — 按钮点击
        param_written(name, raw_value) — 参数写入

    刷新策略：var/updated 前沿立即刷新（交互响应快），
    冷却期(33ms)内的事件合并到下一次定时冲刷 —— 高频流下约 30fps。
    """
    button_clicked = Signal(str, str, object)
    param_written = Signal(str, float)

    def __init__(self, profile):
        super().__init__()
        self._profile = profile
        self._widgets = {}
        self._values = {}
        self._flush_pending = False
        self._flush_timer = QTimer(self)
        self._flush_timer.setSingleShot(True)
        self._flush_timer.setInterval(33)
        self._flush_timer.timeout.connect(self._on_flush_tick)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        self._grid = QGridLayout(container)
        self._grid.setSpacing(spacing("md"))
        scroll.setWidget(container)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
        self._build()
        self._subscribe_events()

    def _subscribe_events(self):
        from ..core.event_bus import EventBus
        EventBus.instance().subscribe("var/updated", self._on_var_updated)

    def _on_var_updated(self, event):
        self._values[event.name] = event.raw_value
        for w in self._widgets.values():
            if hasattr(w, "on_var_event"):
                w.on_var_event(event)
        if self._flush_timer.isActive():
            self._flush_pending = True       # 冷却期内合并
        else:
            self.update_values(self._values)  # 前沿立即刷新
            self._flush_timer.start()

    def _on_flush_tick(self):
        if self._flush_pending:
            self._flush_pending = False
            self.update_values(self._values)
            self._flush_timer.start()

    def rebuild(self):
        """清空并按当前 profile.dashboard 重建（可视化编辑保存后调用）。"""
        for w in list(self._widgets.values()):
            w.setParent(None)
            w.deleteLater()
        self._widgets.clear()
        self._build()

    def _build(self):
        for wd in self._profile.dashboard:
            w = self._create(wd)
            if w:
                self._grid.addWidget(w, wd.y, wd.x, wd.h, wd.w)
                self._widgets[wd.id] = w
                if isinstance(w, ButtonPanelWidget):
                    w.button_clicked.connect(self.button_clicked.emit)
                elif isinstance(w, ParamEditorWidget):
                    w.param_written.connect(self.param_written.emit)

    def _create(self, wd):
        # 统一走组件注册表（运行时与可视化编辑器共用同一工厂）
        from .widgets.registry import create_widget
        return create_widget(wd, self._profile)

    def update_values(self, values):
        for w in self._widgets.values():
            if hasattr(w, "update_values"):
                w.update_values(values)
