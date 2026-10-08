"""workspace.py — 工作区快照（P1-7 的纯逻辑层）

「关机—搬家—开机」后重搭环境是联调现场最高频的浪费：splitter 位置、
波形通道集合、监视表、快捷命令、窗口尺寸、停留页签此前都不记忆。

WorkspaceSnapshot 把这些统一序列化为可命名快照（JSON，用户数据目录），
支持快速切换与「开机恢复上次工作区」。本模块只做数据模型与持久化，
收集/还原动作由各视图的 collect_workspace()/restore_workspace() 完成。
不 import Qt，可独立单测。
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from .app_paths import user_file

WORKSPACE_FILENAME = "workspaces.json"
MAX_WORKSPACES = 20


@dataclass
class WorkspaceSnapshot:
    """一个完整工作区。"""

    name: str
    saved_at: float
    window_size: tuple[int, int] = (1280, 800)
    active_tab: int = 0
    scope_channels: list[str] = field(default_factory=list)
    watch_items: list[dict] = field(default_factory=list)
    serial_splitters: list[int] = field(default_factory=list)
    scope_splitters: list[int] = field(default_factory=list)
    inspector_splitters: list[int] = field(default_factory=list)
    send_input: str = ""
    quick_commands: list[dict] = field(default_factory=list)

    def summary(self) -> str:
        stamp = time.strftime("%m-%d %H:%M:%S", time.localtime(self.saved_at))
        return (f"{self.name} [{stamp}] 波形通道 {len(self.scope_channels)} / "
                f"监视项 {len(self.watch_items)} / 快捷命令 "
                f"{len(self.quick_commands)}")


def to_dict(snap: WorkspaceSnapshot) -> dict:
    return {
        "name": snap.name,
        "saved_at": snap.saved_at,
        "window_size": list(snap.window_size),
        "active_tab": snap.active_tab,
        "scope_channels": list(snap.scope_channels),
        "watch_items": [dict(i) for i in snap.watch_items],
        "serial_splitters": list(snap.serial_splitters),
        "scope_splitters": list(snap.scope_splitters),
        "inspector_splitters": list(snap.inspector_splitters),
        "send_input": snap.send_input,
        "quick_commands": [dict(c) for c in snap.quick_commands],
    }


def from_dict(data: dict) -> WorkspaceSnapshot:
    size = data.get("window_size") or [1280, 800]
    try:
        size = (int(size[0]), int(size[1]))
    except (TypeError, ValueError, IndexError):
        size = (1280, 800)
    return WorkspaceSnapshot(
        name=str(data.get("name", "未命名")),
        saved_at=float(data.get("saved_at", 0.0)),
        window_size=size,
        active_tab=int(data.get("active_tab", 0) or 0),
        scope_channels=[str(x) for x in data.get("scope_channels", [])],
        watch_items=[dict(x) for x in data.get("watch_items", [])],
        serial_splitters=[int(x) for x in data.get("serial_splitters", [])],
        scope_splitters=[int(x) for x in data.get("scope_splitters", [])],
        inspector_splitters=[int(x) for x in data.get("inspector_splitters", [])],
        send_input=str(data.get("send_input", "")),
        quick_commands=[dict(x) for x in data.get("quick_commands", [])],
    )


class WorkspaceStore:
    """命名工作区快照的 JSON 持久化。"""

    def __init__(self, path: str | Path | None = None):
        self._path = Path(path) if path else user_file(WORKSPACE_FILENAME)

    @property
    def path(self) -> Path:
        return self._path

    def load_all(self) -> list[WorkspaceSnapshot]:
        if not self._path.is_file():
            return []
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            return [from_dict(x) for x in raw.get("workspaces", [])]
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return []

    def save(self, name: str, snap: WorkspaceSnapshot) -> list[WorkspaceSnapshot]:
        snap.name = name.strip() or "未命名工作区"
        snap.saved_at = time.time()
        workspaces = [w for w in self.load_all() if w.name != snap.name]
        workspaces.insert(0, snap)
        self._write(workspaces)
        return workspaces

    def delete(self, name: str) -> list[WorkspaceSnapshot]:
        workspaces = [w for w in self.load_all() if w.name != name]
        self._write(workspaces)
        return workspaces

    def get(self, name: str) -> WorkspaceSnapshot | None:
        for w in self.load_all():
            if w.name == name:
                return w
        return None

    def _write(self, workspaces: list[WorkspaceSnapshot]) -> None:
        payload = {"workspaces": [to_dict(w) for w in workspaces[:MAX_WORKSPACES]]}
        self._path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
