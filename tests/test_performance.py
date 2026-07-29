import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from subtitle_tool.performance import StageTimer  # noqa: E402


class StageTimerTests(unittest.TestCase):
    def test_records_accumulated_stage_and_total_durations(self):
        values = iter([10.0, 11.0, 13.5, 14.0, 15.0, 17.0])
        timer = StageTimer(clock=lambda: next(values))

        timer.start("translation")
        timer.finish("translation")
        timer.start("translation")
        timer.finish("translation")

        self.assertEqual(timer.durations(), {"translation": 3.5})
        self.assertEqual(timer.total_duration_seconds(), 7.0)

    def test_stage_context_finishes_when_operation_raises(self):
        values = iter([2.0, 3.0, 5.5])
        timer = StageTimer(clock=lambda: next(values))

        with self.assertRaisesRegex(RuntimeError, "boom"):
            with timer.stage("source"):
                raise RuntimeError("boom")

        self.assertEqual(timer.durations(), {"source": 2.5})


if __name__ == "__main__":
    unittest.main()
