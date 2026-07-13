from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from subtitle_tool.errors import CancellationError  # noqa: E402
from subtitle_tool.process_control import run_process, run_process_streaming  # noqa: E402


class ProcessControlTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
