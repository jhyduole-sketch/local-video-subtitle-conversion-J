from __future__ import annotations

from contextlib import contextmanager
import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Iterator


class MissingJobError(ValueError):
    """增量保存所依赖的任务已丢失。 The job required for an incremental save is missing."""


class JobStore:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def save(self, record: dict[str, Any], *, log_start: int | None = None) -> None:
        logs = record.get("logs", [])
        with self._lock, self._connect(write=True) as connection:
            job_id = record["id"]
            persisted_count = self._log_count(connection, job_id)
            if log_start is not None:
                if isinstance(log_start, int) and log_start > 0 and persisted_count == 0:
                    exists = connection.execute(
                        "SELECT 1 FROM jobs WHERE id = ?", (job_id,)
                    ).fetchone()
                    if exists is None:
                        raise MissingJobError(f"Job {job_id!r} is missing; replay all logs from offset 0")
                if not isinstance(log_start, int) or log_start < 0 or log_start != persisted_count:
                    raise ValueError(
                        f"Log offset {log_start!r} does not match stored count {persisted_count}"
                    )
                append_start = log_start
                suffix = logs
            else:
                # 完整保存保留替换语义，仅修改第一个差异之后的日志。
                # Full saves preserve replacement semantics and reuse the unchanged prefix.
                existing = self._logs(connection, job_id)
                append_start = 0
                for old, new in zip(existing, logs):
                    if old != new:
                        break
                    append_start += 1
                if append_start < persisted_count:
                    connection.execute(
                        "DELETE FROM job_logs WHERE job_id = ? AND position >= ?",
                        (job_id, append_start),
                    )
                suffix = logs[append_start:]
            connection.execute(
                """
                INSERT INTO jobs (
                    id, status, logs_json, result_json, error, progress,
                    progress_message, cancel_requested, payload_json,
                    resumed_from, created_at, updated_at
                ) VALUES (?, ?, '[]', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    status=excluded.status,
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
                    job_id,
                    record["status"],
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
            self._append_logs(connection, job_id, append_start, suffix)

    def get(self, job_id: str, *, include_logs: bool = True) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if row is None:
                return None
            logs = self._logs(connection, job_id) if include_logs else []
            return _row_to_record(row, logs)

    def list(
        self, limit: int = 50, offset: int = 0, *, include_logs: bool = True
    ) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
            return [
                _row_to_record(row, self._logs(connection, row["id"]) if include_logs else [])
                for row in rows
            ]

    def count(self) -> int:
        with self._lock, self._connect() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0])

    def read_logs(self, job_id: str, start: int = 0, limit: int = 200) -> tuple[list[str], int]:
        if start < 0 or limit < 0:
            raise ValueError("Log start and limit must be non-negative")
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT entry FROM job_logs WHERE job_id = ? AND position >= ? "
                "ORDER BY position LIMIT ?", (job_id, start, limit)
            ).fetchall()
            return [row["entry"] for row in rows], self._log_count(connection, job_id)

    def delete(self, job_id: str) -> None:
        with self._lock, self._connect(write=True) as connection:
            connection.execute("DELETE FROM jobs WHERE id = ?", (job_id,))

    def clear_finished(self) -> int:
        active_statuses = ("queued", "running", "canceling")
        with self._lock, self._connect(write=True) as connection:
            cursor = connection.execute(
                "DELETE FROM jobs WHERE status NOT IN (?, ?, ?)", active_statuses
            )
            return max(0, cursor.rowcount)

    def mark_inflight_interrupted(self) -> int:
        message = "服务重启，任务已中断，可继续"
        active_statuses = ("queued", "running", "canceling")
        with self._lock, self._connect(write=True) as connection:
            connection.execute(
                """
                INSERT INTO job_logs (job_id, position, entry)
                SELECT id, COALESCE((SELECT MAX(position) + 1 FROM job_logs
                                     WHERE job_id = jobs.id), 0), ?
                FROM jobs WHERE status IN (?, ?, ?)
                """,
                (message, *active_statuses),
            )
            cursor = connection.execute(
                """
                UPDATE jobs SET status = 'interrupted', cancel_requested = 0,
                    progress_message = ?, updated_at = ?
                WHERE status IN (?, ?, ?)
                """,
                (message, time.time(), *active_statuses),
            )
            return max(0, cursor.rowcount)

    def _initialize(self) -> None:
        with self._connect(initialize=True):
            pass

    @contextmanager
    def _connect(
        self, *, write: bool = False, initialize: bool = False
    ) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(self.path), timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            schema_missing = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'jobs'"
            ).fetchone() is None
            if initialize or schema_missing:
                # 先原子提交建表与旧日志迁移，后续保存失败不会留下无表的数据库。
                # Commit schema creation and migration before a failing save can roll them back.
                connection.execute("BEGIN IMMEDIATE")
                self._create_table(connection)
                connection.commit()
            # 写事务先锁定，防止不同存储实例同时使用同一日志偏移。
            # Acquire the write lock before validating offsets across store instances.
            connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _log_count(connection: sqlite3.Connection, job_id: str) -> int:
        return int(connection.execute(
            "SELECT COALESCE(MAX(position) + 1, 0) FROM job_logs WHERE job_id = ?",
            (job_id,),
        ).fetchone()[0])

    @staticmethod
    def _logs(connection: sqlite3.Connection, job_id: str) -> list[str]:
        return [row["entry"] for row in connection.execute(
            "SELECT entry FROM job_logs WHERE job_id = ? ORDER BY position", (job_id,)
        )]

    @staticmethod
    def _append_logs(
        connection: sqlite3.Connection, job_id: str, start: int, logs: list[str]
    ) -> None:
        connection.executemany(
            "INSERT INTO job_logs (job_id, position, entry) VALUES (?, ?, ?)",
            ((job_id, start + index, entry) for index, entry in enumerate(logs)),
        )

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
        connection.execute(
            "CREATE INDEX IF NOT EXISTS jobs_created_at_id ON jobs (created_at DESC, id DESC)"
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS job_logs (
                job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                position INTEGER NOT NULL CHECK(position >= 0),
                entry TEXT NOT NULL,
                PRIMARY KEY (job_id, position)
            ) WITHOUT ROWID
            """
        )
        # 迁移与清空旧字段处于同一事务，重启不会重复写入旧日志。
        # Migrate and clear the legacy field atomically so reopening cannot duplicate logs.
        for row in connection.execute("SELECT id, logs_json FROM jobs WHERE logs_json != '[]'"):
            logs = json.loads(row["logs_json"])
            if not isinstance(logs, list):
                raise ValueError("Legacy logs must be a list")
            JobStore._append_logs(connection, row["id"], 0, logs)
            connection.execute("UPDATE jobs SET logs_json = '[]' WHERE id = ?", (row["id"],))


def _json_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)


def _row_to_record(row: sqlite3.Row, logs: list[str]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "status": row["status"],
        "logs": logs,
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
