"""write_audit.py — 参数写入审计日志（P1-12 的纯逻辑层）

每次参数写入（手动 / 调参 / AI 建议 / 回滚）追加一条 JSONL 记录：
时间、变量、旧值、新值、来源、结果。供「写入审计」窗口与调试报告消费。

JSONL 追加写：单条记录损坏不影响其他记录；超过上限自动截断老记录。
不 import Qt，可独立单测。
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

from .app_paths import user_file

AUDIT_FILENAME = "write_audit.jsonl"
MAX_RECORDS = 2000


@dataclass(frozen=True)
class AuditRecord:
    timestamp: float
    var: str
    old_value: float | None
    new_value: float
    source: str
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "var": self.var,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "source": self.source,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AuditRecord":
        return cls(
            timestamp=float(data.get("timestamp", 0.0)),
            var=str(data.get("var", "")),
            old_value=(float(data["old_value"])
                       if data.get("old_value") is not None else None),
            new_value=float(data.get("new_value", 0.0)),
            source=str(data.get("source", "")),
            note=str(data.get("note", "")),
        )

    def stamp(self) -> str:
        return time.strftime("%m-%d %H:%M:%S", time.localtime(self.timestamp))


class WriteAuditLog:
    """JSONL 审计日志。"""

    def __init__(self, path: str | Path | None = None):
        self._path = Path(path) if path else user_file(AUDIT_FILENAME)

    @property
    def path(self) -> Path:
        return self._path

    def append(self, var: str, new_value, old_value=None,
               source: str = "manual", note: str = "") -> AuditRecord:
        record = AuditRecord(
            timestamp=time.time(), var=str(var),
            old_value=None if old_value is None else float(old_value),
            new_value=float(new_value), source=source, note=note)
        try:
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")
        except OSError:
            pass
        self._truncate_if_needed()
        return record

    def records(self, limit: int = 200) -> list[AuditRecord]:
        if not self._path.is_file():
            return []
        out: list[AuditRecord] = []
        try:
            with self._path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        out.append(AuditRecord.from_dict(json.loads(line)))
                    except (json.JSONDecodeError, TypeError, ValueError):
                        continue    # 单条损坏不拖垮整份日志
        except OSError:
            return []
        return out[-limit:]

    def _truncate_if_needed(self) -> None:
        try:
            if not self._path.is_file():
                return
            lines = self._path.read_text(encoding="utf-8").splitlines()
            if len(lines) > MAX_RECORDS:
                keep = lines[-MAX_RECORDS:]
                self._path.write_text("\n".join(keep) + "\n", encoding="utf-8")
        except OSError:
            pass
