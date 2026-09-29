from concurrent.futures import Future, ThreadPoolExecutor
import threading
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from subtitle_tool import web
from subtitle_tool.job_store import JobStore
from subtitle_tool.pipeline import PipelineResult


class WebCompletionTests(unittest.TestCase):
    def setUp(self):
        self.jobs_patch = patch.object(web, "JOBS", {})
        self.jobs_patch.start()
        self.store_patch = patch.object(web, "JOB_STORE", None)
        self.store_patch.start()
        self.addCleanup(self.jobs_patch.stop)
        self.addCleanup(self.store_patch.stop)

    def test_cancel_at_pipeline_completion_reaches_terminal_state(self):
        job = web.JobState(id="finish", payload={"input": "/tmp/video.mp4"})
        web.JOBS[job.id] = job
        def complete(options):
            web.request_job_cancel(job.id)
            return PipelineResult(source_subtitle_path=None, translated_paths={}, failed_languages={}, source_kind="download")
        with patch.object(web, "run_pipeline", side_effect=complete):
            web._run_job(job.id, web.options_from_payload(job.payload))
        self.assertEqual(job.status, "canceled")
        self.assertIsNone(web.active_job())

    def test_cancel_at_render_completion_reaches_terminal_state(self):
        job = web.JobState(id="render", payload={})
        web.JOBS[job.id] = job
        def complete(*args, **kwargs):
            web.request_job_cancel(job.id)
            return Path('/tmp/done.mp4')
        with patch.object(web, "safe_output_path", side_effect=lambda root, path, suffix: path), patch.object(web, "render_edited_subtitle_video", side_effect=complete):
            web._run_subtitle_render_job(job.id, {"videoPath": "/tmp/video.mp4", "subtitlePath": "/tmp/source.srt"})
        self.assertEqual(job.status, "canceled")
        self.assertIsNone(web.active_job())

    def test_persistence_failure_does_not_publish_queued_job(self):
        with patch.object(web, "_persist_job", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                web._reserve_job({"input": "video.mp4"})
        self.assertEqual(web.JOBS, {})

    def test_submit_failure_is_terminal_in_memory_and_database(self):
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory) / "jobs.sqlite3")
            with patch.object(web, "JOB_STORE", store), patch.object(web.JOB_EXECUTOR, "submit", side_effect=RuntimeError("executor closed")):
                with self.assertRaises(RuntimeError):
                    web.create_pipeline_job({"input": "/tmp/video.mp4"}, web.options_from_payload({"input": "/tmp/video.mp4"}))
                self.assertIsNone(web.active_job())
                self.assertTrue(all(row['status'] == 'failed' for row in store.list()))

    def test_cancel_racing_with_failure_is_terminal(self):
        job = web.JobState(id="failure", cancel_requested=True, status="canceling")
        web.JOBS[job.id] = job
        web._update_job(job.id, status="failed", error="failed")
        self.assertEqual(job.status, "canceled")

    def test_worker_exception_during_final_persistence_is_observed(self):
        job = web.JobState(id="worker-failure")
        web.JOBS[job.id] = job
        future = Future()
        with patch.object(web.JOB_EXECUTOR, "submit", return_value=future), patch.object(web, "_persist_job", side_effect=OSError("disk full")):
            web._submit_job(job, lambda *args: None, None)
            future.set_exception(OSError("disk full"))
        self.assertEqual(job.status, "failed")
        self.assertIsNone(web.active_job())
        self.assertIn("保存失败", job.logs[-1])

    def test_shutdown_waits_for_real_worker_cooperative_cleanup(self):
        executor = ThreadPoolExecutor(max_workers=1)
        started = threading.Event()
        job = web.JobState(id="real-shutdown")
        web.JOBS[job.id] = job
        def worker(*args):
            started.set()
            if not job.cancel_event.wait(2):
                raise AssertionError("shutdown did not signal cancellation")
            web._update_job(job.id, status="canceled")
        try:
            with patch.object(web, "JOB_EXECUTOR", executor):
                web._submit_job(job, worker, None)
                self.assertTrue(started.wait(2))
                web.shutdown_jobs()
            self.assertEqual(job.status, "canceled")
        finally:
            executor.shutdown(wait=True)
            web.SERVICE_STOPPING.clear()

    def test_shutdown_signals_jobs_before_waiting_for_executor(self):
        job = web.JobState(id="shutdown", status="running")
        web.JOBS[job.id] = job
        executor = Mock()
        def shutdown(**kwargs):
            self.assertTrue(job.cancel_event.is_set())
            self.assertTrue(kwargs['wait'])
            web._update_job(job.id, status="canceled")
        executor.shutdown.side_effect = shutdown
        try:
            with patch.object(web, "JOB_EXECUTOR", executor):
                web.shutdown_jobs()
            self.assertEqual(job.status, "canceled")
            with self.assertRaises(web.SubtitleToolError):
                web._reserve_job({})
        finally:
            if hasattr(web, 'SERVICE_STOPPING'):
                web.SERVICE_STOPPING.clear()


if __name__ == '__main__':
    unittest.main()
