from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from subtitle_tool.errors import CancellationError  # noqa: E402
from subtitle_tool.process_control import run_process  # noqa: E402


class ProcessControlTests(unittest.TestCase):
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
