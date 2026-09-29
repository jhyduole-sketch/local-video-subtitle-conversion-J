from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from subtitle_tool.job_store import JobStore  # noqa: E402


LEGACY_SCHEMA = """
CREATE TABLE jobs (
    id TEXT PRIMARY KEY, status TEXT NOT NULL, logs_json TEXT NOT NULL,
    result_json TEXT, error TEXT, progress INTEGER NOT NULL,
    progress_message TEXT NOT NULL, cancel_requested INTEGER NOT NULL,
    payload_json TEXT NOT NULL, resumed_from TEXT, created_at REAL NOT NULL,
    updated_at REAL NOT NULL
)
"""


def record(job_id="job", logs=None, **changes):
    value = dict(id=job_id, status="running", logs=logs or [], result=None,
                 error=None, progress=20, progress_message="处理中",
                 cancel_requested=False, payload={"input": "视频.mp4"},
                 resumed_from=None, created_at=10.0, updated_at=20.0)
    value.update(changes)
    return value


class IncrementalJobStoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "jobs.sqlite3"

    def legacy_database(self, logs_json='["开始", "完成"]'):
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute(LEGACY_SCHEMA)
            connection.execute(
                "INSERT INTO jobs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("legacy", "running", logs_json, None, None, 20, "处理中",
                 0, '{"input": "视频.mp4"}', None, 10.0, 20.0),
            )

    def test_legacy_logs_migrate_once_and_keep_roundtrip(self):
        self.legacy_database()
        store = JobStore(self.path)
        self.assertEqual(store.get("legacy"), record("legacy", ["开始", "完成"]))
        with closing(sqlite3.connect(self.path)) as connection:
            self.assertEqual(connection.execute("SELECT logs_json FROM jobs").fetchone()[0], "[]")
        reopened = JobStore(self.path)
        self.assertEqual(reopened.read_logs("legacy"), (["开始", "完成"], 2))

    def test_bad_legacy_json_rolls_back_entire_migration(self):
        self.legacy_database()
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("INSERT INTO jobs SELECT 'broken', status, 'invalid', result_json, error, progress, progress_message, cancel_requested, payload_json, resumed_from, created_at, updated_at FROM jobs")
        with self.assertRaises((ValueError, json.JSONDecodeError)):
            JobStore(self.path)
        with closing(sqlite3.connect(self.path)) as connection:
            self.assertEqual(connection.execute("SELECT logs_json FROM jobs WHERE id='legacy'").fetchone()[0], '["开始", "完成"]')
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("DELETE FROM jobs WHERE id='broken'")
        self.assertEqual(JobStore(self.path).read_logs("legacy"), (["开始", "完成"], 2))

    def test_incremental_append_preserves_existing_rows_and_metadata(self):
        store = JobStore(self.path)
        store.save(record(logs=["first"]), log_start=0)
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.executescript("""
                CREATE TRIGGER forbid_log_update BEFORE UPDATE ON job_logs
                BEGIN SELECT RAISE(ABORT, 'old log updated'); END;
                CREATE TRIGGER forbid_log_delete BEFORE DELETE ON job_logs
                BEGIN SELECT RAISE(ABORT, 'old log deleted'); END;
            """)
        store.save(record(logs=["second", "第三"], progress=70), log_start=1)
        store.save(record(logs=[], progress=80), log_start=3)
        self.assertEqual(store.read_logs("job", start=1, limit=1), (["second"], 3))
        self.assertEqual(store.read_logs("job", start=5), ([], 3))
        self.assertEqual(store.get("job")["progress"], 80)
        self.assertEqual(store.get("job")["logs"], ["first", "second", "第三"])
        with closing(sqlite3.connect(self.path)) as connection:
            self.assertEqual(connection.execute("SELECT logs_json FROM jobs").fetchone()[0], "[]")

    def test_incremental_offsets_reject_gaps_duplicates_and_negatives(self):
        store = JobStore(self.path)
        store.save(record(logs=["first"]))
        for offset in (-1, 0, 2):
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                store.save(record(logs=["bad"], progress=90), log_start=offset)
        self.assertEqual(store.get("job")["progress"], 20)
        self.assertEqual(store.read_logs("job"), (["first"], 1))
        with self.assertRaises(ValueError):
            store.save(record("missing", ["bad"]), log_start=1)
        self.assertIsNone(store.get("missing"))

    def test_removed_database_reports_missing_job_and_allows_full_replay(self):
        store = JobStore(self.path)
        store.save(record(logs=["first"]), log_start=0)
        self.path.unlink()
        with self.assertRaises(ValueError) as error:
            store.save(record(logs=["second"]), log_start=1)
        self.assertEqual(type(error.exception).__name__, "MissingJobError")
        self.assertEqual(store.count(), 0)
        store.save(record(logs=["first", "second"]), log_start=0)
        self.assertEqual(store.read_logs("job"), (["first", "second"], 2))

    def test_failed_first_save_on_empty_database_leaves_schema_usable(self):
        store = JobStore(self.path)
        self.path.unlink()
        self.path.touch()
        with self.assertRaises(KeyError):
            store.save({"id": "invalid", "logs": []}, log_start=0)
        store.save(record(logs=["recovered"]), log_start=0)
        self.assertEqual(store.read_logs("job"), (["recovered"], 1))
        self.assertIsNone(store.get("invalid"))

    def test_existing_job_wrong_offset_is_not_reported_as_missing(self):
        store = JobStore(self.path)
        for logs in ([], ["first"]):
            store.save(record(logs=logs))
            with self.assertRaises(ValueError) as error:
                store.save(record(logs=["bad"]), log_start=2)
            self.assertEqual(type(error.exception), ValueError)
            self.assertEqual(store.get("job")["logs"], logs)

    def test_full_save_replaces_and_truncates_logs(self):
        store = JobStore(self.path)
        for entries in (["first", "second"], ["replaced"], [], ["new"]):
            store.save(record(logs=entries))
            self.assertEqual(store.get("job")["logs"], entries)
            self.assertEqual(store.read_logs("job"), (entries, len(entries)))

    def test_log_insert_failure_rolls_back_metadata_and_entire_suffix(self):
        store = JobStore(self.path)
        store.save(record(logs=["old"]))
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("""CREATE TRIGGER reject_third_log BEFORE INSERT ON job_logs
                WHEN (SELECT COUNT(*) FROM job_logs) >= 2
                BEGIN SELECT RAISE(ABORT, 'disk failure'); END""")
        with self.assertRaises(sqlite3.IntegrityError):
            store.save(record(logs=["new", "rejected"], progress=99), log_start=1)
        self.assertEqual(store.get("job"), record(logs=["old"]))

    def test_metadata_reads_omit_log_loading_without_changing_record_shape(self):
        store = JobStore(self.path)
        store.save(record(logs=["large log"]))
        self.assertEqual(store.get("job", include_logs=False), record())
        self.assertEqual(store.list(include_logs=False), [record()])
        self.assertIsNone(store.get("unknown", include_logs=False))
        self.assertEqual(store.read_logs("unknown"), ([], 0))

    def test_pagination_is_stable_for_more_than_fifty_jobs_with_tied_dates(self):
        store = JobStore(self.path)
        for index in range(63):
            store.save(record(f"job-{index:03d}"))
        self.assertEqual(store.count(), 63)
        self.assertEqual(len(store.list()), 50)
        self.assertEqual([item["id"] for item in store.list(10, 50)], [f"job-{index:03d}" for index in range(12, 2, -1)])
        self.assertEqual([item["id"] for item in store.list(10, 60)], ["job-002", "job-001", "job-000"])
        self.assertEqual(store.list(10, 63), [])

    def test_delete_and_clear_finished_remove_log_rows(self):
        store = JobStore(self.path)
        store.save(record("active", ["active"]))
        store.save(record("done", ["done"], status="succeeded"))
        store.save(record("failed", ["failed"], status="failed"))
        store.delete("failed")
        store.delete("unknown")
        self.assertEqual(store.read_logs("failed"), ([], 0))
        self.assertEqual(store.clear_finished(), 1)
        self.assertEqual(store.read_logs("done"), ([], 0))
        self.assertEqual(store.count(), 1)
        with closing(sqlite3.connect(self.path)) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM job_logs").fetchone()[0], 1)

    def test_interrupt_marks_active_jobs_beyond_first_thousand(self):
        store = JobStore(self.path)
        store.save(record("old-active", ["before"], created_at=0, cancel_requested=True))
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.executemany("INSERT INTO jobs SELECT ?, 'succeeded', '[]', result_json, error, progress, progress_message, 0, payload_json, resumed_from, 100, updated_at FROM jobs WHERE id='old-active'", [(f"done-{index}",) for index in range(1001)])
        self.assertEqual(store.mark_inflight_interrupted(), 1)
        recovered = store.get("old-active")
        self.assertEqual(recovered["status"], "interrupted")
        self.assertFalse(recovered["cancel_requested"])
        self.assertEqual(recovered["logs"][0], "before")
        self.assertEqual(len(recovered["logs"]), 2)
        self.assertEqual(store.mark_inflight_interrupted(), 0)


if __name__ == "__main__":
    unittest.main()
