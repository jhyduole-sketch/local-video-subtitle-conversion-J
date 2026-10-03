from pathlib import Path
import sys
import subprocess
import os
import signal
import tempfile
from unittest.mock import patch
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from subtitle_tool.errors import CancellationError, ProcessTimeoutError  # noqa: E402
from subtitle_tool.process_control import run_process, run_process_streaming  # noqa: E402


class ProcessControlTests(unittest.TestCase):
    def test_callback_exceptions_reap_children(self):
        for streaming in (False, True):
            children = []
            original = subprocess.Popen

            def launch(*args, **kwargs):
                child = original(*args, **kwargs)
                children.append(child)
                return child

            def broken(*args):
                raise RuntimeError("callback failed")

            try:
                with self.subTest(streaming=streaming), patch(
                    "subtitle_tool.process_control.subprocess.Popen", side_effect=launch
                ):
                    call = run_process_streaming if streaming else run_process
                    kwargs = {"stdout_line_callback": broken} if streaming else {
                        "heartbeat_callback": broken, "heartbeat_interval_seconds": 0.01
                    }
                    with self.assertRaisesRegex(RuntimeError, "callback failed"):
                        call([sys.executable, "-c",
                              "import time; print('ready', flush=True); time.sleep(5)"], **kwargs)
                    self.assertIsNotNone(children[0].poll(), "child survived callback failure")
            finally:
                for child in children:
                    if child.poll() is None:
                        child.kill()
                    child.communicate()

    def test_timeout_still_applies_after_output_pipes_close(self):
        started = time.monotonic()
        with self.assertRaises(ProcessTimeoutError):
            run_process_streaming(
                [sys.executable, "-c", "import os,time; os.close(1); os.close(2); time.sleep(1)"],
                timeout_seconds=0.1,
            )
        self.assertLess(time.monotonic() - started, 0.8)

    def test_stream_capture_is_bounded_but_callbacks_receive_all_lines(self):
        lines = []
        result = run_process_streaming(
            [sys.executable, "-c", "print('abcdefghij\\n' * 100)"] ,
            stdout_line_callback=lines.append, capture_limit_bytes=32,
        )
        self.assertEqual(len(lines), 101)
        self.assertLessEqual(len(result.stdout.encode()), 32)

    def test_callback_failure_terminates_descendants_after_leader_exit(self):
        children = []
        descendant = []
        original = subprocess.Popen
        with tempfile.TemporaryDirectory() as directory:
            stopped = Path(directory) / "stopped"
            ready = Path(directory) / "ready"
            child_code = ("import signal,time; from pathlib import Path; "
                          f"signal.signal(signal.SIGTERM, lambda *args: (Path({str(stopped)!r}).touch(), exit(0))); "
                          f"Path({str(ready)!r}).touch(); time.sleep(10)")
            leader_code = ("import subprocess,sys,time; from pathlib import Path; "
                           f"p=subprocess.Popen([sys.executable, '-c', {child_code!r}]); "
                           f"exec(\"while not Path({str(ready)!r}).exists(): time.sleep(.01)\"); "
                           "print(p.pid, flush=True)")
            def launch(*args, **kwargs):
                process = original(*args, **kwargs)
                children.append(process)
                return process
            def broken(line):
                descendant.append(int(line))
                children[0].wait(timeout=2)
                raise RuntimeError("after leader exit")
            try:
                with patch("subtitle_tool.process_control.subprocess.Popen", side_effect=launch):
                    with self.assertRaisesRegex(RuntimeError, "after leader exit"):
                        run_process_streaming([sys.executable, "-c", leader_code], stdout_line_callback=broken)
                deadline = time.monotonic() + .5
                while not stopped.exists() and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertTrue(stopped.exists(), "descendant did not receive group termination")
            finally:
                for pid in descendant:
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                for child in children:
                    if child.poll() is None:
                        child.kill()
                    child.communicate()

    def test_streaming_process_emits_stdout_lines(self):
        lines = []

        completed = run_process_streaming(
            [
                sys.executable,
                "-c",
                "import sys,time; print('first', flush=True); time.sleep(.1); print('second', flush=True)",
            ],
            stdout_line_callback=lines.append,
        )

        self.assertEqual(completed.returncode, 0)
        self.assertEqual(lines, ["first", "second"])

    def test_invalid_utf8_from_child_process_is_replaced(self):
        completed = run_process(
            [
                sys.executable,
                "-c",
                "import os; os.write(1, b'valid\\xfftext'); os.write(2, b'err\\xfetext')",
            ]
        )

        self.assertEqual(completed.returncode, 0)
        self.assertEqual(completed.stdout, "valid\ufffdtext")
        self.assertEqual(completed.stderr, "err\ufffdtext")

    def test_cancellation_terminates_running_child_process(self):
        checks = 0

        def cancel_check():
            nonlocal checks
            checks += 1
            return checks >= 2

        started_at = time.monotonic()
        with self.assertRaises(CancellationError):
            run_process(
                [sys.executable, "-c", "import time; time.sleep(10)"],
                cancel_check=cancel_check,
            )

        self.assertLess(time.monotonic() - started_at, 3.0)

    def test_process_timeout_terminates_running_child_process(self):
        started_at = time.monotonic()

        with self.assertRaises(ProcessTimeoutError) as raised:
            run_process(
                [sys.executable, "-c", "import time; time.sleep(10)"],
                timeout_seconds=0.1,
                operation_name="测试进程",
            )

        self.assertLess(time.monotonic() - started_at, 3.0)
        self.assertIn("测试进程", str(raised.exception))
        self.assertIn("超时", str(raised.exception))

    def test_streaming_inactivity_timeout_terminates_stalled_process(self):
        started_at = time.monotonic()

        with self.assertRaises(ProcessTimeoutError) as raised:
            run_process_streaming(
                [
                    sys.executable,
                    "-c",
                    "import time; print('started', flush=True); time.sleep(10)",
                ],
                inactivity_timeout_seconds=0.15,
                operation_name="流式测试",
            )

        self.assertLess(time.monotonic() - started_at, 3.0)
        self.assertIn("长时间没有进度", str(raised.exception))

    def test_process_emits_periodic_heartbeat(self):
        heartbeats = []

        completed = run_process(
            [sys.executable, "-c", "import time; time.sleep(.18)"],
            heartbeat_interval_seconds=0.05,
            heartbeat_callback=heartbeats.append,
        )

        self.assertEqual(completed.returncode, 0)
        self.assertGreaterEqual(len(heartbeats), 2)
        self.assertTrue(all(value > 0 for value in heartbeats))


if __name__ == "__main__":
    unittest.main()
