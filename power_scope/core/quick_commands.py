"""quick_commands.py — 快捷命令收藏夹（P1-8 的纯逻辑层）

替代串口监控页里硬编码的 4 个 NS800RT 黄金帧：用户可增删改，
每条命令存 JSON（用户数据目录），帧内容为 Hex 文本。

CRC 自动计算：
  - 输入仅载荷 hex 时，按调试帧格式包装并追加 CRC16-Modbus；
  - 输入完整帧 hex 时，校验其尾部 CRC 是否一致（不一致给出提示）。
不 import Qt，可独立单测。
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from .app_paths import user_file

STORE_FILENAME = "quick_commands.json"


@dataclass
class QuickCommand:
    """一条快捷命令。frame_hex 为完整帧的 Hex 文本（空格分隔，大写显示）。"""

    name: str
    frame_hex: str
    note: str = ""
    updated_at: float = 0.0

    @property
    def frame(self) -> bytes:
        return bytes.fromhex("".join(self.frame_hex.split()))

    def display_hex(self) -> str:
        raw = "".join(self.frame_hex.split()).upper()
        return " ".join(raw[i:i + 2] for i in range(0, len(raw), 2))


def default_commands() -> list[QuickCommand]:
    """内置 NS800RT 黄金帧（首次使用/重置时写入）。"""
    from .cffi_loader import DebugProtocol

    def hx(cmd: int, payload: bytes = b"") -> str:
        return DebugProtocol.build_frame(cmd, 1, 0, payload).hex(" ").upper()

    return [
        QuickCommand("读设备信息", hx(0x07), "GET_INFO"),
        QuickCommand("停止采样", hx(0x06, b"\x00"), "STOP_STREAM"),
        QuickCommand("关机", hx(0x0C, b"\x00"), "DEVICE_CONTROL off"),
        QuickCommand("开机", hx(0x0C, b"\x01"), "DEVICE_CONTROL on"),
    ]


def build_frame_from_payload(cmd: int, payload_hex: str = "",
                             seq: int = 1) -> str:
    """载荷 hex → 带 CRC 的完整帧 hex（供编辑器「自动计算 CRC」）。"""
    from .cffi_loader import DebugProtocol
    payload = bytes.fromhex("".join(payload_hex.split()))
    return DebugProtocol.build_frame(cmd, seq, 0, payload).hex(" ").upper()


def check_frame_crc(frame_hex: str) -> tuple[bool, str]:
    """校验完整帧的 CRC16-Modbus 尾部。返回 (ok, message)。"""
    from .cffi_loader import CRC16
    try:
        data = bytes.fromhex("".join(frame_hex.split()))
    except ValueError as exc:
        return False, f"Hex 解析失败: {exc}"
    if len(data) < 4:
        return False, "帧长度不足"
    body, recv = data[:-2], data[-2] | (data[-1] << 8)
    calc = CRC16.calc(body)
    if calc != recv:
        return False, f"CRC 不匹配: 计算 0x{calc:04X} / 帧内 0x{recv:04X}"
    return True, f"CRC OK (0x{recv:04X})"


class QuickCommandStore:
    """JSON 持久化的快捷命令收藏夹。"""

    def __init__(self, path: str | Path | None = None):
        self._path = Path(path) if path else user_file(STORE_FILENAME)

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> list[QuickCommand]:
        if not self._path.is_file():
            return default_commands()
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            items = []
            for entry in raw.get("commands", []):
                try:
                    items.append(QuickCommand(
                        name=str(entry.get("name", "")).strip(),
                        frame_hex=str(entry.get("frame_hex", "")).strip(),
                        note=str(entry.get("note", "")),
                        updated_at=float(entry.get("updated_at", 0.0)),
                    ))
                except (TypeError, ValueError):
                    continue
            return [c for c in items if c.name and c.frame_hex]
        except (OSError, json.JSONDecodeError):
            return default_commands()

    def save(self, commands: list[QuickCommand]) -> None:
        payload = {"commands": [asdict(c) for c in commands]}
        self._path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def reset_defaults(self) -> list[QuickCommand]:
        commands = default_commands()
        self.save(commands)
        return commands

    @staticmethod
    def normalize(name: str, frame_hex: str, note: str = "") -> QuickCommand:
        return QuickCommand(name=name.strip(), frame_hex=frame_hex.strip(),
                            note=note.strip(), updated_at=time.time())
