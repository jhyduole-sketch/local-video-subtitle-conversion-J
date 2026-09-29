from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from subtitle_tool import web
from subtitle_tool.job_store import JobStore


class WebHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = JobStore(Path(self.temp.name) / 'jobs.sqlite3')
        for target, value in [('JOBS', {}), ('JOB_STORE', self.store)]:
            guard = patch.object(web, target, value)
            guard.start()
            self.addCleanup(guard.stop)

    def save_job(self, index, logs=None):
        job = web.JobState(id=f'job-{index:03}', status='failed', created_at=float(index), payload={'input': '/tmp/video.mp4'}, logs=logs or [])
        self.store.save(web._job_record(job))
        return job

    def test_pages_include_history_older_than_fifty_jobs(self):
        for i in range(75):
            self.save_job(i, ['private log'])
        first = web.jobs_payload(limit=50, offset=0)
        second = web.jobs_payload(limit=50, offset=50)
        self.assertEqual(first['total'], 75)
        self.assertTrue(first['hasMore'])
        self.assertFalse(second['hasMore'])
        self.assertEqual(len(second['jobs']), 25)
        self.assertEqual(second['jobs'][-1]['id'], 'job-000')
        self.assertTrue(all(job['logs'] == [] for job in first['jobs']))
        self.assertEqual(web.JOBS, {})

    def test_old_task_can_be_read_and_resumed_without_startup_preload(self):
        self.save_job(0, ['first', 'token=private'])
        self.assertEqual(len(web.job_payload('job-000')['logs']), 2)
        data = web.job_payload('job-000', log_offset=1, log_limit=1)
        self.assertNotIn('private', str(data))
        self.assertEqual(data['logOffset'], 1)
        self.assertEqual(data['nextLogOffset'], 2)
        self.assertFalse(data['hasMoreLogs'])
        with patch.object(web.JOB_EXECUTOR, 'submit'):
            resumed = web.resume_job('job-000')
        self.assertEqual(resumed.resumed_from, 'job-000')
        self.assertEqual(resumed.payload['input'], '/tmp/video.mp4')

    def test_live_logs_use_cursor_and_persist_only_new_entries(self):
        job = web._reserve_job({'input': '/tmp/video.mp4'})
        with patch.object(self.store, 'save', wraps=self.store.save) as save:
            web._update_job(job.id, log='first')
            web._update_job(job.id, log='second')
            web._update_job(job.id, progress=10)
        self.assertEqual([len(call.args[0]['logs']) for call in save.call_args_list], [1, 1, 0])
        self.assertEqual([call.kwargs['log_start'] for call in save.call_args_list], [0, 1, 2])
        first = web.job_payload(job.id, log_offset=0, log_limit=1)
        self.assertTrue(first['hasMoreLogs'])
        second = web.job_payload(job.id, log_offset=first['nextLogOffset'], log_limit=1)
        self.assertIn('second', second['logs'][0])
        self.assertFalse(second['hasMoreLogs'])
        self.assertEqual(web.job_payload(job.id, log_offset=2, log_limit=1)['logs'], [])
        self.assertEqual(len(self.store.get(job.id)['logs']), 2)

    def test_deleted_state_database_is_rebuilt_from_live_job(self):
        job = web._reserve_job({'input': '/tmp/video.mp4'})
        web._update_job(job.id, log='before deletion')
        self.store.path.unlink()
        web._update_job(job.id, log='after deletion')
        restored = self.store.get(job.id)
        self.assertEqual(len(restored['logs']), 2)
        self.assertIn('before deletion', restored['logs'][0])
        self.assertIn('after deletion', restored['logs'][1])
        self.assertEqual(job.persisted_log_count, 2)

    def test_startup_does_not_preload_historical_logs(self):
        self.save_job(0, ['entry'] * 100)
        web.configure_job_store(self.store.path)
        self.assertEqual(web.JOBS, {})
        self.assertEqual(web.job_payload('job-000', log_offset=99, log_limit=1)['logs'], ['entry'])


if __name__ == '__main__':
    unittest.main()
