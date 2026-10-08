"""test_quick_commands_store.py — 快捷命令收藏夹（P1-8）"""
from __future__ import annotations

from power_scope.core.quick_commands import (
    QuickCommandStore, build_frame_from_payload, check_frame_crc,
    default_commands,
)


def test_defaults_cover_golden_frames():
    commands = default_commands()
    names = [c.name for c in commands]
    assert "读设备信息" in names and "开机" in names
    for command in commands:
        assert bytes.fromhex("".join(command.frame_hex.split()))


def test_store_roundtrip(tmp_path):
    store = QuickCommandStore(tmp_path / "qc.json")
    commands = store.load()
    assert commands          # 首次自动装默认
    commands.append(QuickCommandStore.normalize("自定义", "A5 5A 01 0C 02 00 00 00 00 00 00 00"))
    store.save(commands)
    reloaded = store.load()
    assert any(c.name == "自定义" for c in reloaded)


def test_store_corrupt_file_falls_back(tmp_path):
    path = tmp_path / "qc.json"
    path.write_text("{broken", encoding="utf-8")
    store = QuickCommandStore(path)
    assert store.load()          # 不抛异常，回退默认


def test_build_frame_crc_and_check():
    frame_hex = build_frame_from_payload(0x07, "")
    ok, message = check_frame_crc(frame_hex)
    assert ok, message
    assert frame_hex.startswith("A5 5A 01 07")

    bad = frame_hex[:-2] + "00 00"
    ok2, message2 = check_frame_crc(bad)
    assert not ok2
    assert "CRC" in message2

    ok3, message3 = check_frame_crc("ZZ ZZ")
    assert not ok3
    assert "Hex" in message3


def test_check_frame_crc_detects_bad_hex():
    ok, message = check_frame_crc("A5 5A GG")
    assert not ok
    assert "失败" in message
