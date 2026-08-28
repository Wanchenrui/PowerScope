"""registry.py — 仪表盘组件注册表（运行时渲染与可视化编辑器共用）。

把原 DashboardView._create 的硬编码分支抽成注册表：每种组件登记
  - 中文显示名 + 默认网格尺寸（拖入画布时用）
  - 属性 schema（驱动编辑器属性面板自动生成表单）
  - 工厂函数（(DashboardWidget, profile) -> QWidget）
第三方可 register() 新组件，落地"可拓展"。
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable

from . import (
    WaveformWidget, GaugeWidget, ButtonPanelWidget,
    StatusPanelWidget, InfoPanelWidget, ParamEditorWidget,
)


@dataclass
class WidgetSpec:
    type: str
    label: str                         # 中文显示名（组件库/画布用）
    default_w: int
    default_h: int
    factory: Callable                  # (wd, profile) -> QWidget | None
    props: list = field(default_factory=list)  # 属性 schema，见 kind 约定

    # props 项: {"key","label","kind","default"}
    #   kind: "text" | "float" | "int" | "var"(单变量下拉) | "varlist"(逗号分隔)


# ---- 工厂（复用原 _create 构造逻辑，运行时/预览共用） ----

def _make_waveform(wd, profile):
    return WaveformWidget(wd.title, wd.config.get("variables", []),
                          wd.config.get("time_window", 5.0))


def _make_gauge(wd, profile):
    var = profile.find_var(wd.config.get("variable", "")) if profile else None
    if var:
        return GaugeWidget(var.display_name, var.unit, var.min_val, var.max_val, var.color)
    return None


def _make_info(wd, profile):
    return InfoPanelWidget(wd.title, wd.config.get("variables", []), profile)


def _make_buttons(wd, profile):
    return ButtonPanelWidget(wd.title, wd.config.get("buttons", []), profile)


def _make_status(wd, profile):
    return StatusPanelWidget(wd.title, wd.config.get("indicators", []), profile)


def _make_param(wd, profile):
    return ParamEditorWidget(wd.title, wd.config.get("variables", []), profile)


WIDGET_REGISTRY: dict[str, WidgetSpec] = {}


def register(spec: WidgetSpec) -> None:
    WIDGET_REGISTRY[spec.type] = spec


# ---- 内置组件登记 ----

register(WidgetSpec("waveform", "波形图", 6, 4, _make_waveform, [
    {"key": "variables", "label": "变量(逗号分隔)", "kind": "varlist", "default": []},
    {"key": "time_window", "label": "时间窗(s)", "kind": "float", "default": 5.0},
]))
register(WidgetSpec("gauge", "仪表盘", 3, 3, _make_gauge, [
    {"key": "variable", "label": "绑定变量", "kind": "var", "default": ""},
]))
register(WidgetSpec("info_panel", "信息面板", 4, 3, _make_info, [
    {"key": "variables", "label": "变量(逗号分隔)", "kind": "varlist", "default": []},
]))
# gauge_group 是 info_panel 的历史别名
register(WidgetSpec("gauge_group", "信息面板(组)", 4, 3, _make_info, [
    {"key": "variables", "label": "变量(逗号分隔)", "kind": "varlist", "default": []},
]))
register(WidgetSpec("button_panel", "按钮面板", 4, 3, _make_buttons, [
    {"key": "buttons", "label": "按钮列表", "kind": "advanced", "default": []},
]))
register(WidgetSpec("status_panel", "状态面板", 4, 3, _make_status, [
    {"key": "indicators", "label": "指示器列表", "kind": "advanced", "default": []},
]))
register(WidgetSpec("param_editor", "参数编辑", 4, 3, _make_param, [
    {"key": "variables", "label": "变量(逗号分隔)", "kind": "varlist", "default": []},
]))


def create_widget(wd, profile):
    """按 DashboardWidget.type 构造运行时组件；未注册类型返回 None。"""
    spec = WIDGET_REGISTRY.get(wd.type)
    return spec.factory(wd, profile) if spec else None


def palette_items() -> list:
    """组件库可拖入项（去重别名）：[(type, label, default_w, default_h)]。"""
    seen = set()
    out = []
    for spec in WIDGET_REGISTRY.values():
        if spec.type == "gauge_group":   # 别名不重复列出
            continue
        out.append((spec.type, spec.label, spec.default_w, spec.default_h))
    return out
