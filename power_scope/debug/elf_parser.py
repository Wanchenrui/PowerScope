"""ELF/DWARF 解析器: 从 .elf 文件提取全局变量地址和类型信息"""
from dataclasses import dataclass, field
from typing import Optional
import struct
import logging

logger = logging.getLogger(__name__)

@dataclass
class StructMember:
    name: str
    offset: int
    size: int
    type_name: str

@dataclass
class ElfVariable:
    name: str
    address: int
    size: int
    type_name: str
    is_struct: bool = False
    members: list = field(default_factory=list)
    file: str = ""
    line: int = 0

    def member_address(self, member_name):
        for m in self.members:
            if m.name == member_name:
                return (self.address + m.offset, m.size, m.type_name)
        raise KeyError(f"成员 {member_name} 不存在于 {self.name}")

TYPE_FORMATS = {
    "uint8_t": "<B", "int8_t": "<b", "char": "<b", "unsigned char": "<B",
    "uint16_t": "<H", "int16_t": "<h", "short": "<h", "unsigned short": "<H",
    "uint32_t": "<I", "int32_t": "<i", "int": "<i", "unsigned int": "<I",
    "uint64_t": "<Q", "int64_t": "<q", "float": "<f", "double": "<d",
    "_Bool": "<B", "bool": "<B", "pointer": "<I",
    # GCC DWARF 基础类型名（ARM EABI: long=4 字节）
    "signed char": "<b",
    "short int": "<h", "short unsigned int": "<H",
    "long int": "<i", "long unsigned int": "<I",
    "long long int": "<q", "long long unsigned int": "<Q",
}

def decode_value(raw, type_name):
    """按类型解码原始字节为 Python 值"""
    fmt = TYPE_FORMATS.get(type_name)
    if fmt:
        sz = struct.calcsize(fmt)
        if len(raw) >= sz:
            return struct.unpack(fmt, raw[:sz])[0]
    return raw

class ELFParser:
    """ELF 文件解析器: 提取全局变量符号表 + DWARF 类型信息"""

    def __init__(self, elf_path):
        self.path = elf_path
        self.f = open(elf_path, "rb")
        self.elf = None
        self._type_cache = {}
        self._cache = None
        self._cache_mtime = None
        from elftools.elf.elffile import ELFFile
        self.f.seek(0)
        self.elf = ELFFile(self.f)

    def parse_variables(self):
        """解析所有全局变量（按 mtime 缓存）, 返回 ElfVariable 列表"""
        mtime = self._current_mtime()
        if self._cache is not None and mtime == self._cache_mtime:
            return self._cache
        variables = self._do_parse()
        self._cache = variables
        self._cache_mtime = mtime
        return variables

    def _current_mtime(self):
        import os
        try:
            return os.path.getmtime(self.path)
        except OSError:
            return None

    def _do_parse(self):
        """实际解析逻辑（无缓存）"""
        dwarf_vars = {}
        if self.elf.has_dwarf_info():
            try:
                dwarf_vars = self._parse_dwarf()
            except Exception as e:
                logger.warning(f"DWARF 解析失败: {e}")
        variables = []
        symtab = self.elf.get_section_by_name(".symtab") or self.elf.get_section_by_name(".dynsym")
        if not symtab:
            return []
        for sym in symtab.iter_symbols():
            if sym["st_info"]["type"] != "STT_OBJECT":
                continue
            if sym["st_shndx"] == "SHN_UNDEF":
                continue
            addr = sym["st_value"]
            size = sym["st_size"]
            if addr == 0 or size == 0:
                continue
            di = dwarf_vars.get(sym.name)
            if di:
                var = ElfVariable(name=sym.name, address=addr, size=size,
                    type_name=di["type_name"], is_struct=di["is_struct"],
                    members=di.get("members", []), file=di.get("file",""), line=di.get("line",0))
            else:
                var = ElfVariable(name=sym.name, address=addr, size=size,
                    type_name=self._guess_type(size))
            variables.append(var)
        return variables

    def _parse_dwarf(self):
        dwarf = self.elf.get_dwarf_info()
        result = {}
        for CU in dwarf.iter_CUs():
            cu_name = ""
            top = CU.get_top_DIE()
            na = top.attributes.get("DW_AT_name")
            if na:
                cu_name = na.value.decode() if isinstance(na.value, bytes) else str(na.value)
            for die in CU.iter_DIEs():
                if die.tag != "DW_TAG_variable":
                    continue
                declaration = self._declaration_die(die)
                name = (self._gs(die, "DW_AT_name", "")
                        or self._gs(declaration, "DW_AT_name", ""))
                if not name:
                    continue
                loc_attr = die.attributes.get("DW_AT_location")
                if not loc_attr:
                    continue
                loc = loc_attr.value
                if isinstance(loc, (list, bytes)) and len(loc) >= 5 and loc[0] == 0x03:
                    addr = struct.unpack("<I", bytes(loc[1:5]))[0]
                else:
                    continue
                type_owner = die if "DW_AT_type" in die.attributes else declaration
                ti = self._describe_type(self._type_die(type_owner))
                result[name] = {
                    "type_name": ti["name"] if ti else "unknown",
                    "is_struct": bool(ti and ti.get("kind") in ("struct", "union", "array")),
                    "members": ti.get("members", []) if ti else [],
                    "file": cu_name,
                    "line": self._gi(die, "DW_AT_line",
                                     self._gi(declaration, "DW_AT_line", 0)),
                }
        return result

    def _declaration_die(self, die):
        """Follow a definition's specification/origin to its named declaration."""
        for attr_name in ("DW_AT_specification", "DW_AT_abstract_origin"):
            if attr_name not in die.attributes:
                continue
            try:
                target = die.get_DIE_from_attribute(attr_name)
                if target is not None:
                    return target
            except (KeyError, AttributeError, TypeError):
                pass
        return die
    def _type_die(self, die):
        """Return the DIE referenced by DW_AT_type (CU-relative refs included)."""
        try:
            return die.get_DIE_from_attribute("DW_AT_type")
        except (KeyError, AttributeError, TypeError):
            return None

    def _member_offset(self, die):
        attr = die.attributes.get("DW_AT_data_member_location")
        if not attr:
            return 0
        value = attr.value
        if isinstance(value, int):
            return value
        # Common DW_OP_plus_uconst, decoded as ULEB128.
        if isinstance(value, (list, bytes)) and len(value) >= 2 and value[0] == 0x23:
            shift = 0
            result = 0
            for byte in value[1:]:
                result |= (byte & 0x7F) << shift
                if (byte & 0x80) == 0:
                    return result
                shift += 7
        return 0

    def _array_dimensions(self, die):
        """Return DWARF array extents in source order."""
        dimensions = []
        for child in die.iter_children():
            if child.tag != "DW_TAG_subrange_type":
                continue
            if "DW_AT_count" in child.attributes:
                dim = int(child.attributes["DW_AT_count"].value)
            elif "DW_AT_upper_bound" in child.attributes:
                lower_attr = child.attributes.get("DW_AT_lower_bound")
                lower = int(lower_attr.value) if lower_attr else 0
                dim = int(child.attributes["DW_AT_upper_bound"].value) - lower + 1
            else:
                dim = 0
            dimensions.append(max(0, dim))
        return dimensions

    def _array_count(self, die):
        dimensions = self._array_dimensions(die)
        count = 1
        for dim in dimensions:
            count *= dim
        return count if dimensions else 0

    def _describe_type(self, die):
        """Recursively describe a DWARF type and flatten composite leaves."""
        if die is None:
            return None
        cached = self._type_cache.get(die.offset)
        if cached is not None:
            return cached

        tag = die.tag
        if tag == "DW_TAG_base_type":
            info = {
                "name": self._gs(die, "DW_AT_name", "unknown"),
                "size": self._gi(die, "DW_AT_byte_size", 0),
                "kind": "base",
            }
        elif tag == "DW_TAG_pointer_type":
            info = {
                "name": "pointer",
                "size": self._gi(die, "DW_AT_byte_size", 4),
                "kind": "pointer",
            }
        elif tag in ("DW_TAG_const_type", "DW_TAG_volatile_type", "DW_TAG_restrict_type"):
            info = self._describe_type(self._type_die(die))
            if info is None:
                return None
            self._type_cache[die.offset] = info
            return info
        elif tag == "DW_TAG_typedef":
            target = self._describe_type(self._type_die(die))
            if target is None:
                return None
            alias = self._gs(die, "DW_AT_name", "")
            info = dict(target)
            if alias in TYPE_FORMATS:
                info["name"] = alias
        elif tag == "DW_TAG_enumeration_type":
            size = self._gi(die, "DW_AT_byte_size", 4)
            info = {
                "name": {1: "uint8_t", 2: "uint16_t", 4: "uint32_t",
                         8: "uint64_t"}.get(size, "unknown"),
                "size": size,
                "kind": "base",
            }
        elif tag == "DW_TAG_array_type":
            element = self._describe_type(self._type_die(die))
            dimensions = self._array_dimensions(die)
            count = 1
            for dim in dimensions:
                count *= dim
            if element is None or count <= 0:
                return None
            size = self._gi(die, "DW_AT_byte_size", element["size"] * count)
            suffix = "".join(f"[{dim}]" for dim in dimensions)
            info = {
                "name": f'{element["name"]}{suffix}',
                "size": size,
                "kind": "array",
                "element": element,
                "count": count,
                "dimensions": dimensions,
                "members": [],
            }
            self._type_cache[die.offset] = info
            info["members"] = self._flatten_type("", 0, info)
            return info
        elif tag in ("DW_TAG_structure_type", "DW_TAG_union_type"):
            kind = "struct" if tag == "DW_TAG_structure_type" else "union"
            info = {
                "name": self._gs(die, "DW_AT_name", "anon"),
                "size": self._gi(die, "DW_AT_byte_size", 0),
                "kind": kind,
                "fields": [],
                "members": [],
            }
            # Cache a placeholder first to break recursive type cycles.
            self._type_cache[die.offset] = info
            for child in die.iter_children():
                if child.tag != "DW_TAG_member":
                    continue
                name = self._gs(child, "DW_AT_name", "")
                child_type = self._describe_type(self._type_die(child))
                if name and child_type is not None:
                    info["fields"].append(
                        (name, self._member_offset(child), child_type))
            info["members"] = self._flatten_type("", 0, info)
            return info
        else:
            return None

        self._type_cache[die.offset] = info
        return info

    def _flatten_type(self, prefix, offset, info):
        kind = info.get("kind")
        if kind in ("base", "pointer"):
            if not prefix or info.get("size", 0) <= 0:
                return []
            return [StructMember(prefix, offset, info["size"], info["name"])]
        if kind in ("struct", "union"):
            leaves = []
            for name, member_offset, child in info.get("fields", []):
                child_name = f"{prefix}.{name}" if prefix else name
                leaves.extend(self._flatten_type(
                    child_name, offset + member_offset, child))
            return leaves
        if kind == "array":
            leaves = []
            element = info["element"]
            element_size = element.get("size", 0)
            dimensions = info.get("dimensions") or [info["count"]]
            if element_size <= 0:
                return leaves

            def visit_dimension(depth, child_prefix, linear_index):
                if depth == len(dimensions):
                    leaves.extend(self._flatten_type(
                        child_prefix, offset + linear_index * element_size,
                        element))
                    return
                for index in range(dimensions[depth]):
                    visit_dimension(
                        depth + 1, f"{child_prefix}[{index}]",
                        linear_index * dimensions[depth] + index)

            visit_dimension(0, prefix, 0)
            return leaves
        return []

    def _resolve(self, offset):
        visited = set()
        while offset and offset not in visited:
            visited.add(offset)
            t = self._type_cache.get(offset)
            if not t:
                return None
            if t["kind"] in ("base","struct","pointer"):
                return t
            if t["kind"] == "typedef":
                offset = t.get("ref")
            else:
                return t
        return None

    def _guess_type(self, size):
        return {1:"uint8_t",2:"uint16_t",4:"uint32_t",8:"uint64_t"}.get(size, f"uint8_t[{size}]")

    def _gs(self, die, attr, default=""):
        a = die.attributes.get(attr)
        if a:
            v = a.value
            return v.decode() if isinstance(v, bytes) else str(v)
        return default

    def _gi(self, die, attr, default=0):
        a = die.attributes.get(attr)
        return a.value if a else default

    def get_variable(self, name):
        for var in self.parse_variables():
            if var.name == name:
                return var
        return None

    def close(self):
        if self.f:
            self.f.close()
            self.f = None

    def __enter__(self):
        return self
    def __exit__(self, *args):
        self.close()


def filter_variables(variables, query):
    """Filter by global name, leaf name, or complete composite path."""
    q = (query or "").strip().lower()
    if not q:
        return [(variable, None) for variable in variables]

    hits = []
    for variable in variables:
        name = variable.name.lower()
        if q in name:
            hits.append((variable, None))
            continue

        matched = []
        for member in getattr(variable, "members", None) or []:
            separator = "" if member.name.startswith("[") else "."
            full_path = f"{variable.name}{separator}{member.name}".lower()
            if q in member.name.lower() or q in full_path:
                matched.append(member)
        if matched:
            hits.append((variable, matched))
    return hits

def resolve_symbol_path(symbol_lookup, path):
    """Resolve a global symbol or flattened struct/array leaf to an address."""
    lookup = symbol_lookup.get if hasattr(symbol_lookup, "get") else symbol_lookup
    direct = lookup(path)
    if direct is not None:
        return direct

    base_name = None
    base_var = None
    if hasattr(symbol_lookup, "keys"):
        candidates = [
            name for name in symbol_lookup.keys()
            if path.startswith(name + ".") or path.startswith(name + "[")
        ]
        if candidates:
            base_name = max(candidates, key=len)
            base_var = lookup(base_name)
    else:
        positions = [p for p in (path.find("."), path.find("[")) if p > 0]
        if positions:
            base_name = path[:min(positions)]
            base_var = lookup(base_name)

    if base_var is None or base_name is None:
        return None
    suffix = path[len(base_name):]
    if suffix.startswith("."):
        suffix = suffix[1:]
    for member in getattr(base_var, "members", None) or []:
        if member.name == suffix and member.size in (1, 2, 4, 8):
            return ElfVariable(
                name=path,
                address=int(base_var.address) + int(member.offset),
                size=int(member.size),
                type_name=member.type_name,
                file=getattr(base_var, "file", ""),
                line=getattr(base_var, "line", 0),
            )
    return None

def type_size(type_name):
    """返回类型的字节宽度；未知类型返回 0。"""
    fmt = TYPE_FORMATS.get(type_name)
    return struct.calcsize(fmt) if fmt else 0


def encode_value(value, type_name):
    """把 Python 值（或字符串）按类型编码为小端字节，是 decode_value 的逆。

    整数类型支持 "0x.." / 十进制字符串；浮点类型支持小数字符串。
    未知类型抛 ValueError。
    """
    fmt = TYPE_FORMATS.get(type_name)
    if not fmt:
        raise ValueError(f"未知类型，无法编码: {type_name}")
    is_float = fmt[-1] in ("f", "d")
    if isinstance(value, str):
        value = value.strip()
        v = float(value) if is_float else int(value, 0)
    else:
        v = float(value) if is_float else int(value)
    return struct.pack(fmt, v)






