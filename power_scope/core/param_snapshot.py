"""param_snapshot.py — 参数还原点（P1-12 的纯逻辑层）

调参/批量写入前把当前参数集存成「还原点」，「一键回滚」时按
{name: value} 重新下发。JSON 持久化在用户数据目录，最多保留 20 个。
不 import Qt，可独立单测。
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from .app_paths import user_file

SNAPSHOT_FILENAME = "param_restore_points.json"
MAX_SNAPSHOTS = 20


@dataclass
class RestorePoint:
    """一个还原点。"""

    id: str
    created_at: float
    label: str
    values: dict[str, float] = field(default_factory=dict)
    source: str = "manual"      # manual / auto

    def summary(self) -> str:
        stamp = time.strftime("%m-%d %H:%M:%S", time.localtime(self.created_at))
        body = ", ".join(f"{k}={v:.6g}" for k, v in list(self.values.items())[:4])
        more = "" if len(self.values) <= 4 else f" 等 {len(self.values)} 项"
        return f"[{stamp}] {self.label}: {body}{more}"


class ParamSnapshotStore:
    """还原点集合的 JSON 持久化。"""

    def __init__(self, path: str | Path | None = None):
        self._path = Path(path) if path else user_file(SNAPSHOT_FILENAME)

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> list[RestorePoint]:
        if not self._path.is_file():
            return []
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            out = []
            for entry in raw.get("points", []):
                try:
                    values = {
                        str(k): float(v)
                        for k, v in dict(entry.get("values", {})).items()
                    }
                    out.append(RestorePoint(
                        id=str(entry.get("id", "")),
                        created_at=float(entry.get("created_at", 0.0)),
                        label=str(entry.get("label", "")),
                        values=values,
                        source=str(entry.get("source", "manual")),
                    ))
                except (TypeError, ValueError):
                    continue
            return out
        except (OSError, json.JSONDecodeError):
            return []

    def save(self, points: list[RestorePoint]) -> None:
        payload = {"points": [
            {"id": p.id, "created_at": p.created_at, "label": p.label,
             "values": p.values, "source": p.source}
            for p in points[:MAX_SNAPSHOTS]
        ]}
        self._path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def add(self, label: str, values: dict[str, float],
            source: str = "manual") -> RestorePoint:
        points = self.load()
        point = RestorePoint(
            id=f"{int(time.time() * 1000)}", created_at=time.time(),
            label=label.strip() or "还原点", values=dict(values), source=source)
        points.insert(0, point)
        self.save(points)
        return point

    def latest(self) -> RestorePoint | None:
        points = self.load()
        return points[0] if points else None
