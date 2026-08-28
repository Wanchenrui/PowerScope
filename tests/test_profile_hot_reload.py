"""test_profile_hot_reload.py — 阶段5 Profile 热重载 + 组件可拓展性"""
import os
import pytest
from power_scope.config.device_profile import (
    DeviceProfile, VarBinding, DashboardWidget, BUILTIN_PROFILES_DIR, load_profile,
)


def _mk_profile(name, varname, theme="dark"):
    return DeviceProfile(
        name=name, device_type="microinverter", version="1.0", theme=theme,
        variables=[VarBinding(name=varname, elf_symbol="g", display_name=varname,
                              min_val=0, max_val=100)],
        dashboard=[DashboardWidget(id="g1", type="gauge", title=varname,
                                   x=0, y=0, w=3, h=3, config={"variable": varname})],
    )


def test_apply_profile_hot_reload(qapp):
    from power_scope.ui.main_window import MainWindow
    p1 = _mk_profile("设备A", "Va")
    mw = MainWindow(p1)
    try:
        p2 = _mk_profile("设备B", "Vb", theme="light")
        mw.apply_profile(p2)
        assert mw._profile is p2
        assert "设备B" in mw.windowTitle()
        # 波形可选变量已刷新为新 profile
        # 仪表盘已按新 profile 重建（gauge 用 Vb）
        assert mw._dashboard._profile is p2
        assert "g1" in mw._dashboard._widgets
    finally:
        mw.close()


def test_widget_registry_is_extensible(qapp):
    """第三方注册自定义组件 → 出现在组件库 → 可创建（可拓展性）。"""
    from PySide6.QtWidgets import QLabel
    from power_scope.ui.widgets.registry import (
        WIDGET_REGISTRY, WidgetSpec, register, palette_items, create_widget,
    )
    def _factory(wd, profile):
        return QLabel(wd.title or "custom")
    register(WidgetSpec("custom_kpi", "自定义KPI", 2, 2, _factory,
                        [{"key": "unit", "label": "单位", "kind": "text", "default": ""}]))
    try:
        assert "custom_kpi" in WIDGET_REGISTRY
        assert "custom_kpi" in [t for t, l, w, h in palette_items()]
        from power_scope.config.device_profile import DashboardWidget
        wd = DashboardWidget(id="k1", type="custom_kpi", title="KPI", x=0, y=0, w=2, h=2)
        w = create_widget(wd, None)
        assert w is not None and w.text() == "KPI"
    finally:
        WIDGET_REGISTRY.pop("custom_kpi", None)
