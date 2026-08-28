"""F8 — 结构体/数组叶子解析、成员采样与按地址监视。"""
from __future__ import annotations

from dataclasses import dataclass

from power_scope.config.device_profile import DeviceProfile, VarBinding
from power_scope.core.debug_service import build_sample_channels
from power_scope.debug.elf_parser import ELFParser, ElfVariable, StructMember


@dataclass
class _Attr:
    value: object


class _Die:
    """最小 DWARF DIE 替身，仅覆盖 F8 类型解析所需接口。"""

    def __init__(self, tag, offset, *, attrs=None, children=None, type_die=None,
                 refs=None):
        self.tag = tag
        self.offset = offset
        self.attributes = {k: _Attr(v) for k, v in (attrs or {}).items()}
        self._children = list(children or [])
        self._type_die = type_die
        self._refs = dict(refs or {})

    def iter_children(self):
        return iter(self._children)

    def get_DIE_from_attribute(self, name):
        if name in self._refs:
            return self._refs[name]
        assert name == "DW_AT_type"
        return self._type_die


def _fake_parser():
    parser = object.__new__(ELFParser)
    parser._type_cache = {}
    return parser


def test_dwarf_flattens_array_of_struct_to_leaf_paths():
    f32 = _Die("DW_TAG_base_type", 1,
               attrs={"DW_AT_name": b"float", "DW_AT_byte_size": 4})
    kp = _Die("DW_TAG_member", 3,
              attrs={"DW_AT_name": b"kp", "DW_AT_data_member_location": 0},
              type_die=f32)
    ki = _Die("DW_TAG_member", 4,
              attrs={"DW_AT_name": b"ki", "DW_AT_data_member_location": 4},
              type_die=f32)
    loop = _Die("DW_TAG_structure_type", 2,
                attrs={"DW_AT_name": b"Loop", "DW_AT_byte_size": 8},
                children=[kp, ki])
    bound = _Die("DW_TAG_subrange_type", 6,
                 attrs={"DW_AT_lower_bound": 0, "DW_AT_upper_bound": 1})
    loops = _Die("DW_TAG_array_type", 5,
                 attrs={"DW_AT_byte_size": 16}, children=[bound], type_die=loop)
    member = _Die("DW_TAG_member", 8,
                  attrs={"DW_AT_name": b"loops", "DW_AT_data_member_location": 4},
                  type_die=loops)
    controller = _Die("DW_TAG_structure_type", 7,
                      attrs={"DW_AT_name": b"Controller", "DW_AT_byte_size": 20},
                      children=[member])

    info = _fake_parser()._describe_type(controller)
    assert [(m.name, m.offset, m.size, m.type_name) for m in info["members"]] == [
        ("loops[0].kp", 4, 4, "float"),
        ("loops[0].ki", 8, 4, "float"),
        ("loops[1].kp", 12, 4, "float"),
        ("loops[1].ki", 16, 4, "float"),
    ]


def test_variable_definition_uses_declaration_specification():
    decl = _Die("DW_TAG_variable", 20,
                attrs={"DW_AT_name": b"g_obj", "DW_AT_type": 1})
    definition = _Die(
        "DW_TAG_variable", 21,
        attrs={"DW_AT_specification": 20,
               "DW_AT_location": [3, 0, 16, 0, 32]},
        refs={"DW_AT_specification": decl})
    parser = _fake_parser()
    assert parser._declaration_die(definition) is decl


def _controller_var():
    return ElfVariable(
        "g_controller", 0x20001000, 20, "Controller", is_struct=True,
        members=[
            StructMember("loops[0].kp", 4, 4, "float"),
            StructMember("loops[0].ki", 8, 4, "float"),
            StructMember("loops[1].kp", 12, 4, "float"),
        ],
    )


def test_resolve_symbol_path_returns_absolute_leaf():
    from power_scope.debug.elf_parser import resolve_symbol_path

    leaf = resolve_symbol_path({"g_controller": _controller_var()},
                               "g_controller.loops[1].kp")
    assert leaf is not None
    assert leaf.name == "g_controller.loops[1].kp"
    assert leaf.address == 0x2000100C
    assert leaf.size == 4 and leaf.type_name == "float"


def test_profile_can_stream_struct_member_path():
    profile = DeviceProfile(
        name="f8", device_type="microinverter", version="1",
        variables=[VarBinding(
            name="loop1_kp", elf_symbol="g_controller.loops[1].kp",
            update_rate=10, scale=2.0, unit="A")],
    )
    channels = build_sample_channels(profile, {"g_controller": _controller_var()})
    assert len(channels) == 1
    assert channels[0].address == 0x2000100C
    assert channels[0].size == 4
    assert channels[0].type_name == "float"


def test_tree_member_double_click_adds_absolute_address(qapp):
    from power_scope.ui.variable_inspector_view import VariableInspectorView

    view = VariableInspectorView(profile=None)
    view._populate_tree([_controller_var()])
    file_item = view._tree.topLevelItem(0)
    var_item = file_item.child(0)
    member_item = var_item.child(2)
    view._on_var_double_click(member_item, 0)

    assert view._watch_table.rowCount() == 1
    assert view._watch_table.item(0, 0).text() == "g_controller.loops[1].kp"
    assert view._watch_table.item(0, 2).text() == "0x2000100C"


def test_tree_container_is_not_added_as_scalar(qapp):
    from power_scope.ui.variable_inspector_view import VariableInspectorView

    view = VariableInspectorView(profile=None)
    view._populate_tree([_controller_var()])
    var_item = view._tree.topLevelItem(0).child(0)
    view._on_var_double_click(var_item, 0)
    assert view._watch_table.rowCount() == 0


def test_tree_caps_large_array_until_user_filters(qapp):
    from power_scope.ui.variable_inspector_view import VariableInspectorView

    array = ElfVariable(
        "g_big", 0x20010000, 1200, "float[300]", is_struct=True,
        members=[StructMember(f"[{i}]", i * 4, 4, "float") for i in range(300)])
    view = VariableInspectorView(profile=None)
    view._populate_tree([array])
    var_item = view._tree.topLevelItem(0).child(0)
    assert var_item.childCount() == 257  # 256 leaves + one explanatory placeholder

    view._apply_filter("[299]")
    filtered = view._tree.topLevelItem(0).child(0)
    assert filtered.childCount() == 1
    assert filtered.child(0).text(2) == "0x200104AC"


def test_manual_address_add_validates_and_formats(qapp):
    from power_scope.ui.variable_inspector_view import VariableInspectorView

    view = VariableInspectorView(profile=None)
    assert view.add_watch_address("scratch", "uint32_t", "0x20001234") is True
    assert view._watch_table.item(0, 2).text() == "0x20001234"
    assert view.add_watch_address("bad", "Controller", "0x20000000") is False
    assert view.add_watch_address("bad2", "float", "not-an-address") is False
    assert view._watch_table.rowCount() == 1

def test_dwarf_preserves_multidimensional_array_indices():
    u16 = _Die("DW_TAG_base_type", 30,
               attrs={"DW_AT_name": b"uint16_t", "DW_AT_byte_size": 2})
    rows = _Die("DW_TAG_subrange_type", 31,
                attrs={"DW_AT_lower_bound": 0, "DW_AT_upper_bound": 1})
    cols = _Die("DW_TAG_subrange_type", 32,
                attrs={"DW_AT_lower_bound": 0, "DW_AT_upper_bound": 2})
    matrix = _Die("DW_TAG_array_type", 33,
                  attrs={"DW_AT_byte_size": 12}, children=[rows, cols],
                  type_die=u16)

    info = _fake_parser()._describe_type(matrix)
    assert info["name"] == "uint16_t[2][3]"
    assert [(m.name, m.offset) for m in info["members"]] == [
        ("[0][0]", 0), ("[0][1]", 2), ("[0][2]", 4),
        ("[1][0]", 6), ("[1][1]", 8), ("[1][2]", 10),
    ]


def test_filter_accepts_full_array_leaf_path():
    from power_scope.debug.elf_parser import filter_variables

    array = ElfVariable(
        "g_big", 0x20010000, 1200, "float[300]", is_struct=True,
        members=[StructMember(f"[{i}]", i * 4, 4, "float") for i in range(300)])
    hits = filter_variables([array], "g_big[299]")
    assert len(hits) == 1
    assert [member.name for member in hits[0][1]] == ["[299]"]

def test_filter_accepts_full_nested_array_member_path():
    from power_scope.debug.elf_parser import filter_variables

    hits = filter_variables([_controller_var()], "g_controller.loops[1].kp")
    assert len(hits) == 1
    assert [member.name for member in hits[0][1]] == ["loops[1].kp"]

def test_filter_accepts_array_of_struct_full_path():
    from power_scope.debug.elf_parser import filter_variables

    value = ElfVariable(
        "g_sircObj", 0x20002870, 60, "Sirc[1]", is_struct=True,
        members=[StructMember("[0].data[1].out", 32, 4, "float")])
    hits = filter_variables([value], "g_sircObj[0].data[1].out")
    assert len(hits) == 1
    assert [member.name for member in hits[0][1]] == ["[0].data[1].out"]

