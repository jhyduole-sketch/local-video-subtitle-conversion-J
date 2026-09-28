from pathlib import Path
from io import BytesIO
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from subtitle_tool import web
from subtitle_tool.upload_store import UploadStore
from subtitle_tool.errors import SubtitleToolError


class WebLifecycleTests(unittest.TestCase):
    def test_retention_failure_keeps_upload_for_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            uploads = UploadStore(root / "uploads", reserve_bytes=0)
            uploaded = uploads.receive(BytesIO(b"video"), 5, "clip.mp4")
            options = web.options_from_payload({"input": str(uploaded), "outDir": str(root / "output")})
            job = web.JobState(id="retention-failure", payload={"input": str(uploaded)})
            web.JOBS[job.id] = job
            try:
                with patch.object(web, "UPLOADS", uploads), patch.object(web, "JOB_STORE", None), patch.object(uploads, "retain", side_effect=OSError("disk full")):
                    web._run_job(job.id, options)
                self.assertEqual(job.status, "failed")
                self.assertEqual(uploaded.read_bytes(), b"video")
            finally:
                web.JOBS.pop(job.id, None)

    def test_conflicting_submission_keeps_upload_for_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            uploads = UploadStore(root / "uploads", reserve_bytes=0)
            uploaded = uploads.receive(BytesIO(b"video"), 5, "clip.mp4")
            web.JOBS["active-conflict"] = web.JobState(id="active-conflict", status="running")
            try:
                with patch.object(web, "UPLOADS", uploads):
                    with self.assertRaises(web.ActiveJobError):
                        web.create_pipeline_job({"input": str(uploaded)}, web.options_from_payload({"input": str(uploaded)}))
                self.assertEqual(uploaded.read_bytes(), b"video")
                uploads.claim(uploaded)
            finally:
                web.JOBS.pop("active-conflict", None)

    def test_structured_diagnostics_are_redacted_without_mutating_saved_result(self):
        result = {"failedLanguages": {"ja": "token=private-value"}, "translationAttempts": {"ja": [{"detail": "password=private-value"}]}, "inputVideoPath": "/tmp/output.mp4"}
        job = web.JobState(id="redact", progress_message="token=private-value", result=result)
        payload = web._job_to_dict(job)
        self.assertNotIn("private-value", str(payload))
        self.assertIn("private-value", str(job.result))
        self.assertEqual(payload["result"]["inputVideoPath"], "/tmp/output.mp4")

    def test_uploaded_input_survives_failure_for_resume_and_temp_is_cleaned(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            uploads = UploadStore(root / "uploads", reserve_bytes=0)
            uploaded = uploads.receive(BytesIO(b"video"), 5, "clip.mp4")
            options = web.options_from_payload({"input": str(uploaded), "outDir": str(root / "output")})
            job = web.JobState(id="upload-failure", payload={"input": str(uploaded), "outDir": str(options.out_dir)})
            web.JOBS[job.id] = job
            try:
                with patch.object(web, "UPLOADS", uploads), patch.object(web, "JOB_STORE", None), patch.object(web, "run_pipeline", side_effect=SubtitleToolError("failure")):
                    web._run_job(job.id, options)
                self.assertEqual(job.status, "failed")
                self.assertFalse(uploaded.exists())
                retained = Path(job.payload["input"])
                self.assertEqual(retained.read_bytes(), b"video")
                self.assertTrue(retained.is_relative_to(options.out_dir))
            finally:
                web.JOBS.pop(job.id, None)

    def test_running_job_prevents_cache_deletion(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            cached = Path(directory) / ".subtitle-tool-cache" / "audio" / "active.mp3"
            cached.parent.mkdir(parents=True)
            cached.write_bytes(b"audio")
            web.JOBS["cache-guard"] = web.JobState(id="cache-guard", status="running")
            try:
                with self.assertRaises(SubtitleToolError):
                    web.clear_cache(output, ["audio"])
                self.assertTrue(cached.exists())
            finally:
                web.JOBS.pop("cache-guard", None)


if __name__ == "__main__":
    unittest.main()
