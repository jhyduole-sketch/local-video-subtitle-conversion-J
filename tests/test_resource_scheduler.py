import sys
from pathlib import Path
import threading
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from subtitle_tool.errors import CancellationError  # noqa: E402
from subtitle_tool.resource_scheduler import HeavyResourceScheduler  # noqa: E402


class HeavyResourceSchedulerTests(unittest.TestCase):
    def test_second_operation_waits_and_reports_active_operation(self):
        scheduler = HeavyResourceScheduler(poll_interval_seconds=0.01)
        entered = threading.Event()
        release = threading.Event()
        waits = []

        def hold_resource():
            with scheduler.reserve("first"):
                entered.set()
                release.wait(timeout=1)

        worker = threading.Thread(target=hold_resource)
        worker.start()
        self.assertTrue(entered.wait(timeout=1))

        def release_soon():
            time.sleep(0.03)
            release.set()

        releaser = threading.Thread(target=release_soon)
        releaser.start()
        with scheduler.reserve("second", wait_callback=waits.append):
            pass
        worker.join(timeout=1)
        releaser.join(timeout=1)

        self.assertIn("first", waits)

    def test_waiting_operation_can_be_cancelled(self):
        scheduler = HeavyResourceScheduler(poll_interval_seconds=0.01)
        with scheduler.reserve("first"):
            with self.assertRaises(CancellationError):
                with scheduler.reserve("second", cancel_check=lambda: True):
                    pass


if __name__ == "__main__":
    unittest.main()
