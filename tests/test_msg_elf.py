from power_scope.debug.msg_elf import decode_msg_command_table, parse_msg_commands


ELF_PATH = (
    "D:/codexworkspace/C01/testproject5039/"
    "C01_2in1_20260821_ongridStable/Debug/"
    "C01_2in1_20260821_ongridStable.elf"
)


def test_decode_msg_table_distinguishes_read_write_and_config_index(qapp):
    symbols = {
        0x08000100: "MSG_WriteSimpleCfgData",
        0x08000200: "MSG_ReadSimpleData",
        0x08000300: "MSG_GetUgVolt",
    }
    write_entry = (
        (0x2001).to_bytes(2, "little") + b"\0\0"
        + (0x08000101).to_bytes(4, "little")
        + (1).to_bytes(4, "little")
    )
    read_entry = (
        (0x2108).to_bytes(2, "little") + b"\0\0"
        + (0x08000201).to_bytes(4, "little")
        + (0x08000301).to_bytes(4, "little")
    )
    commands = decode_msg_command_table(
        write_entry + read_entry, symbols_by_address=symbols)

    assert commands[0].direction == "write"
    assert commands[0].handler_name == "配置索引 0x00000001"
    assert commands[1].direction == "read"
    assert commands[1].handler_name == "MSG_GetUgVolt"


def test_current_firmware_elf_has_searchable_msg_catalog(qapp):
    commands = parse_msg_commands(ELF_PATH)
    by_command = {entry.command: entry for entry in commands}

    assert len(commands) == 163
    assert by_command[0x2001].direction == "write"
    assert by_command[0x2108].handler_name == "MSG_GetUgVolt"
    assert by_command[0x2135].handler_name == "MSG_GetSysState"
