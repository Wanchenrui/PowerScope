"""Discover firmware MSG commands from the ELF command table."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ElfMsgCommand:
    command: int
    direction: str
    parser_name: str
    handler_name: str


def decode_msg_command_table(
    data: bytes,
    *,
    pointer_size: int = 4,
    little_endian: bool = True,
    symbols_by_address: dict[int, str] | None = None,
) -> list[ElfMsgCommand]:
    """Decode ``MsgCmdCfg`` entries without depending on pyelftools.

    The embedded ARM build uses ``uint16 + padding + pointer + pointer``.
    Keeping this decoder separate makes its layout easy to test.
    """
    if pointer_size not in (4, 8):
        raise ValueError("仅支持 32/64 位 ELF 指针")
    symbols = symbols_by_address or {}
    parser_offset = pointer_size
    handler_offset = pointer_size * 2
    entry_size = pointer_size * 3
    byteorder = "little" if little_endian else "big"
    if len(data) % entry_size:
        raise ValueError(
            f"MSG 命令表大小 {len(data)} 不是表项大小 {entry_size} 的整数倍")

    def symbol_name(address: int) -> str:
        return symbols.get(address) or symbols.get(address & ~1) or ""

    commands = []
    for offset in range(0, len(data), entry_size):
        chunk = data[offset:offset + entry_size]
        command = int.from_bytes(chunk[:2], byteorder)
        if command == 0:
            continue
        parser_address = int.from_bytes(
            chunk[parser_offset:parser_offset + pointer_size], byteorder)
        handler_address = int.from_bytes(
            chunk[handler_offset:handler_offset + pointer_size], byteorder)
        parser_name = symbol_name(parser_address)
        if "CfgData" in parser_name:
            handler_name = f"配置索引 0x{handler_address:0{pointer_size * 2}X}"
        else:
            handler_name = symbol_name(handler_address)
        parser_lower = parser_name.lower()
        direction = "read" if "read" in parser_lower else "write"
        commands.append(ElfMsgCommand(
            command=command,
            direction=direction,
            parser_name=parser_name,
            handler_name=handler_name,
        ))
    return commands


def parse_msg_commands(elf_path: str, table_name: str = "g_msgCmdCfgTbl") -> list[ElfMsgCommand]:
    """Read the firmware's MSG command catalog from an ELF symbol table."""
    try:
        from elftools.elf.elffile import ELFFile
    except ImportError as exc:
        raise RuntimeError("解析 MSG 命令表需要 pyelftools") from exc

    with open(elf_path, "rb") as stream:
        elf = ELFFile(stream)
        symtab = elf.get_section_by_name(".symtab") or elf.get_section_by_name(".dynsym")
        if symtab is None:
            raise ValueError("ELF 中没有符号表")

        table_symbol = None
        symbols_by_address = {}
        for symbol in symtab.iter_symbols():
            address = int(symbol["st_value"])
            if address and symbol.name:
                symbols_by_address.setdefault(address, symbol.name)
                symbols_by_address.setdefault(address & ~1, symbol.name)
            if symbol.name == table_name:
                table_symbol = symbol

        if table_symbol is None:
            raise ValueError(f"ELF 中未找到 {table_name}")
        section_index = table_symbol["st_shndx"]
        if not isinstance(section_index, int):
            raise ValueError(f"{table_name} 没有有效的数据节")
        section = elf.get_section(section_index)
        section_offset = int(table_symbol["st_value"]) - int(section["sh_addr"])
        table_size = int(table_symbol["st_size"])
        if table_size <= 0:
            raise ValueError(f"{table_name} 的大小为 0")
        raw = section.data()[section_offset:section_offset + table_size]
        if len(raw) != table_size:
            raise ValueError(f"{table_name} 超出 ELF 数据节范围")
        return decode_msg_command_table(
            raw,
            pointer_size=elf.elfclass // 8,
            little_endian=elf.little_endian,
            symbols_by_address=symbols_by_address,
        )
