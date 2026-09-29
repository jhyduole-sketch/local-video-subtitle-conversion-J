import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest


class WebShutdownProcessTests(unittest.TestCase):
    def test_sigint_stops_background_task_and_exits(self):
        source = Path(__file__).resolve().parents[1] / 'src'
        code = textwrap.dedent('''
            import json
            from pathlib import Path
            import threading
            from subtitle_tool import web
            from subtitle_tool.errors import CancellationError
            started = threading.Event()
            def pipeline(options):
                started.set()
                while not options.cancel_check():
                    threading.Event().wait(0.01)
                raise CancellationError('stopped')
            web.run_pipeline = pipeline
            serve = web.ThreadingHTTPServer.serve_forever
            def serving(server):
                job = web.create_pipeline_job({'input': '/tmp/video.mp4'}, web.options_from_payload({'input': '/tmp/video.mp4'}))
                assert started.wait(3)
                Path('ready').write_text(job.id)
                return serve(server)
            web.ThreadingHTTPServer.serve_forever = serving
            web.main(['--host', '127.0.0.1', '--port', '0'])
            Path('result.json').write_text(json.dumps([job.status for job in web.JOBS.values()]))
        ''')
        with tempfile.TemporaryDirectory() as directory:
            env = {**os.environ, 'PYTHONPATH': str(source), 'PYTHONDONTWRITEBYTECODE': '1'}
            process = subprocess.Popen([sys.executable, '-c', code], cwd=directory, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                deadline = time.monotonic() + 8
                while not (Path(directory) / 'ready').exists() and process.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertTrue((Path(directory) / 'ready').exists(), 'child did not start')
                process.send_signal(signal.SIGINT)
                stdout, stderr = process.communicate(timeout=8)
                self.assertEqual(process.returncode, 0, stdout + stderr)
                self.assertEqual(json.loads((Path(directory) / 'result.json').read_text()), ['canceled'])
            finally:
                if process.poll() is None:
                    process.kill()
                process.communicate()
