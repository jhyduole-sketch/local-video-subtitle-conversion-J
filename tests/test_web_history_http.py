from http.client import HTTPConnection
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from subtitle_tool import web
from subtitle_tool.job_store import JobStore
from subtitle_tool.web_security import AccessPolicy


class WebHistoryHttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = JobStore(self.root / 'jobs.sqlite3')
        for target, value in [('JOBS', {}), ('JOB_STORE', self.store)]:
            guard = patch.object(web, target, value)
            guard.start()
            self.addCleanup(guard.stop)
        for i in range(55):
            job = web.JobState(id=f'history-{i:03}', status='failed', created_at=float(i),
                logs=['first', 'token=private', 'third'], payload={'input': str(self.root / 'video.mp4'), 'outDir': str(self.root)})
            self.store.save(web._job_record(job))
        self.server = web.ThreadingHTTPServer(('127.0.0.1', 0), web.SubtitleToolHandler)
        self.server.access_policy = AccessPolicy((self.root.resolve(),), (self.root.resolve(),))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)

    def request(self, path, method='GET'):
        connection = HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        try:
            connection.request(method, path, body=b'' if method == 'POST' else None)
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def test_page_and_log_cursor_round_trip(self):
        status, page = self.request('/api/jobs?offset=50&limit=50')
        self.assertEqual(status, 200)
        self.assertEqual(page['total'], 55)
        self.assertEqual(len(page['jobs']), 5)
        self.assertFalse(page['hasMore'])
        self.assertEqual(page['jobs'][-1]['id'], 'history-000')
        self.assertEqual(page['jobs'][-1]['logs'], [])
        status, first = self.request('/api/jobs/history-000?logOffset=0&logLimit=2')
        self.assertEqual(status, 200)
        self.assertTrue(first['hasMoreLogs'])
        self.assertNotIn('private', str(first))
        status, last = self.request('/api/jobs/history-000?logOffset=2&logLimit=2')
        self.assertEqual(last['logs'], ['third'])
        self.assertFalse(last['hasMoreLogs'])
        status, legacy = self.request('/api/jobs/history-000')
        self.assertEqual(len(legacy['logs']), 3)

    def test_old_history_resume_is_validated_and_submitted(self):
        with patch.object(web.JOB_EXECUTOR, 'submit') as submit:
            status, result = self.request('/api/jobs/history-000/resume', 'POST')
        self.assertEqual(status, 202)
        submit.assert_called_once()
        self.assertEqual(web.JOBS[result['jobId']].resumed_from, 'history-000')

    def test_old_history_resume_still_checks_server_directories(self):
        self.server.access_policy = AccessPolicy(((self.root / 'allowed').resolve(),), ((self.root / 'allowed').resolve(),))
        with patch.object(web.JOB_EXECUTOR, 'submit') as submit:
            status, result = self.request('/api/jobs/history-000/resume', 'POST')
        self.assertEqual(status, 403)
        submit.assert_not_called()

    def test_invalid_pagination_is_rejected(self):
        for path in ['/api/jobs?offset=-1', '/api/jobs?limit=101', '/api/jobs?limit=2&limit=3',
                     '/api/jobs/history-000?logOffset=bad', '/api/jobs/history-000?logLimit=1001']:
            with self.subTest(path=path):
                self.assertEqual(self.request(path)[0], 400)
