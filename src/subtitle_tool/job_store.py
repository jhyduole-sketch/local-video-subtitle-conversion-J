from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any


class JobStore:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def save(self, record: dict[str, Any]) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO jobs (
                    id, status, logs_json, result_json, error, progress,
                    progress_message, cancel_requested, payload_json,
                    resumed_from, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    status=excluded.status,
                    logs_json=excluded.logs_json,
                    result_json=excluded.result_json,
                    error=excluded.error,
                    progress=excluded.progress,
                    progress_message=excluded.progress_message,
                    cancel_requested=excluded.cancel_requested,
                    payload_json=excluded.payload_json,
                    resumed_from=excluded.resumed_from,
                    created_at=excluded.created_at,
                    updated_at=excluded.updated_at
                """,
                (
                    record["id"],
                    record["status"],
                    json.dumps(record.get("logs", []), ensure_ascii=False),
                    _json_or_none(record.get("result")),
                    record.get("error"),
                    int(record.get("progress", 0)),
                    record.get("progress_message", "等待开始"),
                    1 if record.get("cancel_requested") else 0,
                    json.dumps(record.get("payload", {}), ensure_ascii=False),
                    record.get("resumed_from"),
                    float(record.get("created_at", time.time())),
                    float(record.get("updated_at", time.time())),
                ),
            )

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
        return _row_to_record(row) if row else None

    def list(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [_row_to_record(row) for row in rows]

    def mark_inflight_interrupted(self) -> int:
        records = [
            record
            for record in self.list(limit=1000)
            if record["status"] in {"queued", "running", "canceling"}
        ]
        for record in records:
            record["status"] = "interrupted"
            record["cancel_requested"] = False
            record["progress_message"] = "服务重启，任务已中断，可继续"
            record["logs"].append("服务重启，任务已中断，可继续")
            record["updated_at"] = time.time()
            self.save(record)
        return len(records)

    def _initialize(self) -> None:
        with self._connect() as connection:
            self._create_table(connection)

    def _connect(self) -> sqlite3.Connection:
        database_missing = not self.path.exists()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(self.path), timeout=10)
        connection.row_factory = sqlite3.Row
        if database_missing:
            self._create_table(connection)
        return connection

    @staticmethod
    def _create_table(connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                logs_json TEXT NOT NULL,
                result_json TEXT,
                error TEXT,
                progress INTEGER NOT NULL,
                progress_message TEXT NOT NULL,
                cancel_requested INTEGER NOT NULL,
                payload_json TEXT NOT NULL,
                resumed_from TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
            """
        )


def _json_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)


def _row_to_record(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "status": row["status"],
        "logs": json.loads(row["logs_json"]),
        "result": json.loads(row["result_json"]) if row["result_json"] else None,
        "error": row["error"],
        "progress": int(row["progress"]),
        "progress_message": row["progress_message"],
        "cancel_requested": bool(row["cancel_requested"]),
        "payload": json.loads(row["payload_json"]),
        "resumed_from": row["resumed_from"],
        "created_at": float(row["created_at"]),
        "updated_at": float(row["updated_at"]),
    }
