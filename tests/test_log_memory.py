from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from subtitle_tool import web
from subtitle_tool.job_store import JobStore


class LogMemoryTests(unittest.TestCase):
    def test_memory_tail_keeps_absolute_cursor_and_complete_database_log(self):
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory) / 'jobs.sqlite3')
            job = web.JobState('job', logs=[str(i) for i in range(1200)])
            with patch.object(web, 'JOB_STORE', store), patch.dict(web.JOBS, {'job': job}, clear=True):
                web._persist_job(job)
                self.assertLessEqual(len(job.logs), 1000)
                self.assertEqual(job.persisted_log_count, 1200)
                web._update_job('job', log='last')
                self.assertEqual(store.read_logs('job', 1199, 2)[0][0], '1199')
                self.assertEqual(web.job_payload('job', log_offset=0, log_limit=2)['logs'], ['0', '1'])
                self.assertEqual(web.job_payload('job', log_offset=1200, log_limit=2)['nextLogOffset'], 1201)

    def test_finished_jobs_are_evicted_only_after_durable_save(self):
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory) / 'jobs.sqlite3')
            with patch.object(web, 'JOB_STORE', store), patch.dict(web.JOBS, {}, clear=True):
                for _ in range(25):
                    job = web._reserve_job({})
                    web._update_job(job.id, status='succeeded')
                self.assertLessEqual(len(web.JOBS), 21)
                self.assertEqual(store.count(), 25)

    def test_database_recreation_explains_missing_evicted_history(self):
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory) / 'jobs.sqlite3')
            job = web.JobState('job', logs=[str(i) for i in range(1200)])
            with patch.object(web, 'JOB_STORE', store), patch.dict(web.JOBS, {'job': job}, clear=True):
                web._persist_job(job)
                store.path.unlink()
                web._update_job('job', log='new')
                logs, total = store.read_logs('job', 0, 2000)
                self.assertIn('较早日志', logs[0])
                self.assertTrue(logs[-1].endswith('new'))
                self.assertEqual(total, job.persisted_log_count)

    def test_large_log_entry_is_bounded_in_memory_but_complete_on_disk(self):
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory) / 'jobs.sqlite3')
            message = 'x' * (2 * 1024 * 1024)
            job = web.JobState('job', logs=[message])
            with patch.object(web, 'JOB_STORE', store):
                web._persist_job(job)
                self.assertLessEqual(sum(len(line) for line in job.logs), 1024 * 1024)
                self.assertEqual(store.read_logs('job')[0], [message])

    def test_completed_task_reads_memory_window_after_database_deletion(self):
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory) / 'jobs.sqlite3')
            job = web.JobState('job', status='succeeded', logs=[str(i) for i in range(1200)])
            with patch.object(web, 'JOB_STORE', store), patch.dict(web.JOBS, {'job': job}, clear=True):
                web._persist_job(job)
                store.path.unlink()
                data = web.job_payload('job', log_limit=200)
                self.assertEqual(data['logOffset'], 200)
                self.assertEqual(data['logTotal'], 1200)
                self.assertTrue(data['logTruncated'])
                self.assertEqual(data['logs'][0], '200')
