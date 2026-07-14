from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from subtitle_tool.job_store import JobStore  # noqa: E402


class JobStoreTests(unittest.TestCase):
    def test_clear_finished_preserves_active_jobs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = JobStore(Path(tmpdir) / "jobs.sqlite3")
            statuses = (
                "queued",
                "running",
                "canceling",
                "succeeded",
                "failed",
                "canceled",
                "interrupted",
            )
            for index, status in enumerate(statuses):
                store.save(
                    {
                        "id": status,
                        "status": status,
                        "logs": [],
                        "result": None,
                        "error": None,
                        "progress": 0,
                        "progress_message": "等待开始",
                        "cancel_requested": False,
                        "payload": {"input": "video.mp4"},
                        "resumed_from": None,
                        "created_at": float(index),
                        "updated_at": float(index),
                    }
                )

            deleted = store.clear_finished()
            remaining = {record["id"] for record in store.list()}

        self.assertEqual(deleted, 4)
        self.assertEqual(remaining, {"queued", "running", "canceling"})

    def test_round_trip_preserves_job_payload_and_result(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = JobStore(Path(tmpdir) / "jobs.sqlite3")
            record = {
                "id": "job-1",
                "status": "succeeded",
                "logs": ["started", "done"],
                "result": {"sourceSubtitlePath": "/tmp/source.srt"},
                "error": None,
                "progress": 100,
                "progress_message": "任务完成",
                "cancel_requested": False,
                "payload": {"input": "video.mp4", "targetLangs": ["ja"]},
                "resumed_from": None,
                "created_at": 10.0,
                "updated_at": 20.0,
            }

            store.save(record)
            loaded = store.get("job-1")

        self.assertEqual(loaded, record)

    def test_startup_marks_inflight_jobs_interrupted(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = JobStore(Path(tmpdir) / "jobs.sqlite3")
            for status in ("queued", "running", "canceling"):
                store.save(
                    {
                        "id": status,
                        "status": status,
                        "logs": [],
                        "result": None,
                        "error": None,
                        "progress": 40,
                        "progress_message": "处理中",
                        "cancel_requested": False,
                        "payload": {"input": "video.mp4"},
                        "resumed_from": None,
                        "created_at": 10.0,
                        "updated_at": 20.0,
                    }
                )

            changed = store.mark_inflight_interrupted()
            records = {record["id"]: record for record in store.list()}

        self.assertEqual(changed, 3)
        self.assertTrue(all(record["status"] == "interrupted" for record in records.values()))
        self.assertTrue(all("服务重启" in record["progress_message"] for record in records.values()))

    def test_save_recreates_database_directory_if_output_was_removed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir) / "output" / ".subtitle-tool-state"
            store = JobStore(state_dir / "jobs.sqlite3")

            for child in state_dir.iterdir():
                child.unlink()
            state_dir.rmdir()
            state_dir.parent.rmdir()

            record = {
                "id": "job-after-cleanup",
                "status": "queued",
                "logs": [],
                "result": None,
                "error": None,
                "progress": 0,
                "progress_message": "等待开始",
                "cancel_requested": False,
                "payload": {"input": "video.mp4"},
                "resumed_from": None,
                "created_at": 10.0,
                "updated_at": 10.0,
            }

            store.save(record)

            self.assertEqual(store.get("job-after-cleanup"), record)


if __name__ == "__main__":
    unittest.main()
