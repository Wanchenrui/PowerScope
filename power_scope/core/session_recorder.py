"""session_recorder.py — 会话录制/时光机

基于 SQLite 的轻量持久化，记录 var/updated 事件历史，支持回放。

使用方式:
    recorder = SessionRecorder("session.db")
    recorder.start_session("microinverter_test")
    recorder.record_var("Vdc_bus", 0.0, 380.5, "V", source="mock")
    
    # 回放
    for event in recorder.playback("Vdc_bus", start=0.0, end=10.0):
        print(event.timestamp, event.phys_value)
"""
from __future__ import annotations
import sqlite3
import time
from dataclasses import dataclass
from typing import Optional, Iterator
from pathlib import Path


@dataclass
class RecordedVar:
    """录制的变量数据点"""
    name: str
    timestamp: float
    raw_value: float
    phys_value: float
    unit: str
    source: str


class SessionRecorder:
    """会话录制器 — SQLite 持久化

    自动创建表结构，支持多会话隔离。
    """

    def __init__(self, db_path: str = "power_scope_sessions.db") -> None:
        self._db_path = Path(db_path)
        self._conn: Optional[sqlite3.Connection] = None
        self._session_id: Optional[int] = None
        self._init_db()

    # ------------------------------------------------------------------
    # 数据库初始化
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        """初始化 SQLite 表结构"""
        self._conn = sqlite3.connect(str(self._db_path))
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                created_at REAL NOT NULL,
                device_name TEXT
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS variables (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                timestamp REAL NOT NULL,
                raw_value REAL,
                phys_value REAL,
                unit TEXT,
                source TEXT,
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            )
        """)
        # 索引加速回放查询
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_var_session_name
            ON variables(session_id, name, timestamp)
        """)
        self._conn.commit()

    # ------------------------------------------------------------------
    # 会话管理
    # ------------------------------------------------------------------

    def start_session(self, name: str, device_name: str = "") -> int:
        """开始新会话，返回 session_id"""
        cur = self._conn.execute(
            "INSERT INTO sessions (name, created_at, device_name) VALUES (?, ?, ?)",
            (name, time.time(), device_name),
        )
        self._conn.commit()
        self._session_id = cur.lastrowid
        return self._session_id

    def end_session(self) -> None:
        """结束当前会话"""
        self._session_id = None

    @property
    def is_recording(self) -> bool:
        return self._session_id is not None

    # ------------------------------------------------------------------
    # 数据记录
    # ------------------------------------------------------------------

    def record_var(
        self,
        name: str,
        timestamp: float,
        raw_value: float,
        phys_value: float,
        unit: str = "",
        source: str = "",
    ) -> None:
        """记录单个变量数据点"""
        if not self.is_recording:
            return
        self._conn.execute(
            """INSERT INTO variables
               (session_id, name, timestamp, raw_value, phys_value, unit, source)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (self._session_id, name, timestamp, raw_value, phys_value, unit, source),
        )

    def flush(self) -> None:
        """强制提交到磁盘"""
        if self._conn:
            self._conn.commit()

    # ------------------------------------------------------------------
    # 回放
    # ------------------------------------------------------------------

    def playback(
        self,
        var_name: str,
        start: float = 0.0,
        end: float = float("inf"),
        session_id: Optional[int] = None,
    ) -> Iterator[RecordedVar]:
        """按时间顺序回放变量历史"""
        sid = session_id or self._session_id
        if sid is None:
            return
        cur = self._conn.execute(
            """SELECT name, timestamp, raw_value, phys_value, unit, source
               FROM variables
               WHERE session_id = ? AND name = ? AND timestamp >= ? AND timestamp <= ?
               ORDER BY timestamp""",
            (sid, var_name, start, end),
        )
        for row in cur:
            yield RecordedVar(*row)

    def playback_all(
        self,
        start: float = 0.0,
        end: float = float("inf"),
        session_id: Optional[int] = None,
    ) -> Iterator[RecordedVar]:
        """回放所有变量"""
        sid = session_id or self._session_id
        if sid is None:
            return
        cur = self._conn.execute(
            """SELECT name, timestamp, raw_value, phys_value, unit, source
               FROM variables
               WHERE session_id = ? AND timestamp >= ? AND timestamp <= ?
               ORDER BY timestamp""",
            (sid, start, end),
        )
        for row in cur:
            yield RecordedVar(*row)

    # ------------------------------------------------------------------
    # 导出
    # ------------------------------------------------------------------

    def export_csv(
        self,
        var_name: str,
        csv_path: str,
        start: float = 0.0,
        end: float = float("inf"),
        session_id: Optional[int] = None,
    ) -> int:
        """导出变量历史到 CSV，返回导出记录数"""
        import csv
        sid = session_id or self._session_id
        if sid is None:
            return 0
        count = 0
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp", "raw_value", "phys_value", "unit", "source"])
            for rec in self.playback(var_name, start, end, sid):
                writer.writerow([rec.timestamp, rec.raw_value, rec.phys_value, rec.unit, rec.source])
                count += 1
        return count

    # ------------------------------------------------------------------
    # 查询统计
    # ------------------------------------------------------------------

    def list_sessions(self) -> list[dict]:
        """列出所有会话"""
        cur = self._conn.execute(
            "SELECT id, name, created_at, device_name FROM sessions ORDER BY created_at DESC"
        )
        return [
            {"id": r[0], "name": r[1], "created_at": r[2], "device_name": r[3]}
            for r in cur.fetchall()
        ]

    def get_var_names(self, session_id: Optional[int] = None) -> list[str]:
        """获取会话中记录的所有变量名"""
        sid = session_id or self._session_id
        if sid is None:
            return []
        cur = self._conn.execute(
            "SELECT DISTINCT name FROM variables WHERE session_id = ? ORDER BY name",
            (sid,),
        )
        return [r[0] for r in cur.fetchall()]

    def get_stats(self, session_id: Optional[int] = None) -> dict:
        """获取会话统计"""
        sid = session_id or self._session_id
        if sid is None:
            return {}
        cur = self._conn.execute(
            """SELECT COUNT(*), MIN(timestamp), MAX(timestamp)
               FROM variables WHERE session_id = ?""",
            (sid,),
        )
        row = cur.fetchone()
        return {
            "total_records": row[0] or 0,
            "start_time": row[1],
            "end_time": row[2],
        }

    # ------------------------------------------------------------------
    # 清理
    # ------------------------------------------------------------------

    def close(self) -> None:
        """关闭数据库连接"""
        if self._conn:
            self._conn.close()
            self._conn = None
        self._session_id = None
