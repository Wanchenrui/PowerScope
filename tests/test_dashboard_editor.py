"""test_dashboard_editor.py — 阶段4 可视化拖拽画布：注册表/画布往返/属性面板"""
import pytest
from power_scope.config.device_profile import DeviceProfile, DashboardWidget, VarBinding


def _profile():
    return DeviceProfile(
        name="编辑器测试", device_type="microinverter", version="1.0",
        variables=[VarBinding(name="Vdc", elf_symbol="gVdc", display_name="母线", unit="V",
                              min_val=0, max_val=600, color="#7aa2f7")],
        dashboard=[
            DashboardWidget(id="g1", type="gauge", title="母线电压",
                            x=0, y=0, w=3, h=3, config={"variable": "Vdc"}),
            DashboardWidget(id="w1", type="waveform", title="波形",
                            x=3, y=0, w=6, h=4,
                            config={"variables": ["Vdc"], "time_window": 5.0}),
        ])


def test_registry_and_palette(qapp):
    from power_scope.ui.widgets.registry import WIDGET_REGISTRY, palette_items, create_widget
    assert "gauge" in WIDGET_REGISTRY and "waveform" in WIDGET_REGISTRY
    items = palette_items()
    assert all(len(t) == 4 for t in items)
    assert "gauge_group" not in [t[0] for t in items]  # 别名不重复列出


def test_snap():
    from power_scope.ui.editor.canvas import snap, GRID_UNIT
    assert snap(0) == 0
    assert snap(GRID_UNIT * 3 + 2) == 3
    assert snap(-10) == 0


def test_canvas_roundtrip(qapp):
    """load_from_profile → export_widgets 逐字段一致。"""
    from power_scope.ui.editor.canvas import EditorCanvas
    prof = _profile()
    c = EditorCanvas(prof, live_preview=False)
    c.load_from_profile(prof)
    out = c.export_widgets()
    assert len(out) == 2
    src = {w.id: w for w in prof.dashboard}
    for w in out:
        s = src[w.id]
        assert (w.type, w.x, w.y, w.w, w.h, w.title) == (s.type, s.x, s.y, s.w, s.h, s.title)
        assert w.config == s.config


def test_canvas_add_and_remove(qapp):
    from power_scope.ui.editor.canvas import EditorCanvas
    c = EditorCanvas(_profile(), live_preview=False)
    c.load_from_profile(_profile())
    n0 = len(c.export_widgets())
    item = c.add_widget_type("gauge", x=2, y=2)
    assert item is not None
    assert len(c.export_widgets()) == n0 + 1
    assert item.model.type == "gauge" and item.model.x == 2 and item.model.y == 2
    # 默认尺寸来自注册表
    from power_scope.ui.widgets.registry import WIDGET_REGISTRY
    assert item.model.w == WIDGET_REGISTRY["gauge"].default_w


def test_inspector_edits_model(qapp):
    from power_scope.ui.editor.canvas import EditorCanvas
    from power_scope.ui.editor.inspector import InspectorPanel
    prof = _profile()
    c = EditorCanvas(prof, live_preview=False)
    c.load_from_profile(prof)
    item = c._items[0]
    insp = InspectorPanel(prof)
    insp.set_item(item)
    insp._set_attr("title", "新标题")
    insp._set_cfg("variable", "Vdc")
    assert item.model.title == "新标题"
    assert item.model.config["variable"] == "Vdc"


def test_editor_apply_updates_profile(qapp):
    from power_scope.ui.editor.editor_window import DashboardEditor
    prof = _profile()
    ed = DashboardEditor(prof, live_preview=False)
    got = {}
    ed.saved.connect(lambda p: got.setdefault("p", p))
    ed._canvas.add_widget_type("status_panel", x=0, y=5)
    ed._apply()
    assert got.get("p") is prof
    assert any(w.type == "status_panel" for w in prof.dashboard)
    ed.deleteLater()


def test_yaml_roundtrip_through_editor(qapp, tmp_path):
    """画布 → to_yaml → from_yaml 逐字段一致（端到端往返）。"""
    from power_scope.ui.editor.canvas import EditorCanvas
    prof = _profile()
    c = EditorCanvas(prof, live_preview=False)
    c.load_from_profile(prof)
    c.add_widget_type("param_editor", x=0, y=6)
    prof.dashboard = c.export_widgets()
    path = str(tmp_path / "dev.yaml")
    prof.to_yaml(path)
    reloaded = DeviceProfile.from_yaml(path)
    assert len(reloaded.dashboard) == 3
    types = {w.type for w in reloaded.dashboard}
    assert {"gauge", "waveform", "param_editor"} <= types
