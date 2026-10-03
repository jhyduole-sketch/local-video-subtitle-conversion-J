from http.client import HTTPConnection
from pathlib import Path
import json
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from subtitle_tool import web
from subtitle_tool.web_security import AccessPolicy


class WebBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.server = web.ThreadingHTTPServer(("127.0.0.1", 0), web.SubtitleToolHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def request(self, method, path, body=None, headers=None):
        connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        self.addCleanup(connection.close)
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        return response.status, response.read(), dict(response.getheaders())

    def test_complete_log_download_streams_beyond_memory_window_and_redacts_secrets(self):
        from subtitle_tool.job_store import JobStore
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(Path(directory) / "jobs.sqlite3")
            job = web.JobState("download", logs=[f"line-{i}" for i in range(1200)] + ["token=private-secret"])
            with patch.object(web, "JOB_STORE", store), patch.dict(web.JOBS, {job.id: job}, clear=True):
                web._persist_job(job)
                self.assertLessEqual(len(job.logs), 1000)
                status, body, headers = self.request("GET", "/api/jobs/download/logs")
                store.path.unlink()
                recovery_status, recovered, _ = self.request("GET", "/api/jobs/download/logs")
                self.assertEqual(recovery_status, 200)
                self.assertIn("较早日志", recovered.decode().splitlines()[0])
                self.assertEqual(len(recovered.decode().splitlines()), 1001)
            self.assertEqual(status, 200)
            lines = body.decode().splitlines()
            self.assertEqual(len(lines), 1201)
            self.assertEqual(lines[0], "line-0")
            self.assertEqual(lines[1199], "line-1199")
            self.assertNotIn(b"private-secret", body)
            self.assertIn("attachment", headers["Content-Disposition"])

    def test_retained_cleanup_requires_allowed_output_root_and_same_origin(self):
        status, _, _ = self.request("POST", "/api/inputs/clear", json.dumps({"outDir": "/"}),
                                    {"Content-Type": "application/json"})
        self.assertEqual(status, 403)
        status, _, _ = self.request("POST", "/api/inputs/clear", "{}",
                                    {"Content-Type": "application/json", "Origin": "https://attacker.invalid"})
        self.assertEqual(status, 403)

    def test_client_cannot_authorize_arbitrary_subtitle_root(self):
        from urllib.parse import urlencode
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "private.srt"
            path.write_text("1\n00:00:00,000 --> 00:00:01,000\nPrivate\n")
            query = urlencode({"outDir": "/", "path": str(path)})
            status, body, _ = self.request("GET", "/api/subtitles?" + query)
        self.assertEqual(status, 403)
        self.assertNotIn(b"Private", body)

    def test_untrusted_host_is_rejected(self):
        status, _, _ = self.request("GET", "/api/jobs", headers={"Host": "attacker.invalid"})
        self.assertEqual(status, 403)

    def test_cross_origin_mutation_is_rejected(self):
        status, _, _ = self.request("POST", "/api/jobs/clear", body=b"{}", headers={
            "Origin": "https://attacker.invalid", "Content-Type": "application/json",
        })
        self.assertEqual(status, 403)

    def test_json_endpoint_rejects_plain_text(self):
        status, _, _ = self.request("POST", "/api/run", body=b"{}", headers={
            "Content-Type": "text/plain",
        })
        self.assertEqual(status, 415)

    def test_allowed_subtitle_and_range_preview_still_work(self):
        from urllib.parse import urlencode
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            self.server.access_policy = AccessPolicy((root,), (root,))
            subtitle = root / "allowed.srt"
            subtitle.write_text("1\n00:00:00,000 --> 00:00:01,000\nHello\n")
            video = root / "allowed.mp4"
            video.write_bytes(b"0123456789")
            status, body, _ = self.request("GET", "/api/subtitles?" + urlencode({"outDir": root, "path": subtitle}))
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body)["segments"][0]["text"], "Hello")
            status, body, headers = self.request("GET", "/api/media?" + urlencode({"outDir": root, "path": video}), headers={"Range": "bytes=2-4"})
            self.assertEqual((status, body), (206, b"234"))
            self.assertEqual(headers["Content-Range"], "bytes 2-4/10")

    def test_symlink_cannot_escape_allowed_directory(self):
        from urllib.parse import urlencode
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            root = base / "output"
            root.mkdir()
            outside = base / "private.srt"
            outside.write_text("private")
            link = root / "escape.srt"
            link.symlink_to(outside)
            self.server.access_policy = AccessPolicy((root,), (root,))
            status, _, _ = self.request("GET", "/api/subtitles?" + urlencode({"outDir": root, "path": link}))
            self.assertEqual(status, 403)

    def test_token_session_is_required_and_http_only(self):
        self.server.access_policy = AccessPolicy((Path.cwd(),), (Path.cwd(),), token="test-access-token-not-a-secret")
        status, _, _ = self.request("GET", "/api/jobs")
        self.assertEqual(status, 401)
        status, _, headers = self.request("POST", "/api/session", json.dumps({"token": "wrong"}), {"Content-Type": "application/json"})
        self.assertEqual(status, 401)
        status, _, headers = self.request("POST", "/api/session", json.dumps({"token": "test-access-token-not-a-secret"}), {"Content-Type": "application/json"})
        self.assertEqual(status, 200)
        self.assertIn("HttpOnly", headers["Set-Cookie"])
        self.assertNotIn("test-access-token", headers["Set-Cookie"])
        status, _, _ = self.request("GET", "/api/jobs", headers={"Cookie": headers["Set-Cookie"].split(";", 1)[0]})
        self.assertEqual(status, 200)

    def test_oversized_request_is_rejected_before_body_read(self):
        self.server.access_policy = AccessPolicy((Path.cwd(),), (Path.cwd(),), max_upload_bytes=10)
        status, _, _ = self.request("POST", "/api/upload", b"", {"Content-Length": "1000", "Content-Type": "application/octet-stream"})
        self.assertEqual(status, 413)

    def test_json_cannot_expand_allowed_output_roots(self):
        self.server.access_policy = AccessPolicy(((Path.cwd() / "output").resolve(),), (Path.cwd(),))
        status, _, _ = self.request("PUT", "/api/settings", json.dumps({"outputDir": "/"}), {"Content-Type": "application/json"})
        self.assertEqual(status, 403)

    def test_whitespace_does_not_bypass_local_input_allowlist(self):
        self.server.access_policy = AccessPolicy(((Path.cwd() / "output").resolve(),), (Path.cwd(),))
        for whitespace in (" ", "\t", "\n"):
            with self.subTest(whitespace=repr(whitespace)), patch.object(web, "create_pipeline_job", return_value=SimpleNamespace(id="unexpected", status="queued")):
                status, _, _ = self.request("POST", "/api/run", json.dumps({"input": whitespace + "/private/tmp/outside.mp4" + whitespace, "downloadOnly": True}), {"Content-Type": "application/json"})
                self.assertEqual(status, 403)


if __name__ == "__main__":
    unittest.main()
