from pathlib import Path
from tempfile import TemporaryDirectory
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from subtitle_tool.estimate_history import load_history, record_processing_time
from subtitle_tool.processing_estimate import estimate_processing


class EstimateHistoryTests(unittest.TestCase):
    def test_calibration_changes_matching_estimates_and_bounds_samples(self):
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "history.json"
            base = estimate_processing(600, 100, ["ja"], "soft", False)
            for _ in range(105):
                record_processing_time(path, base, base.seconds * 2)
            calibrated = estimate_processing(600, 100, ["ja"], "soft", False, history_path=path)
            different = estimate_processing(600, 100, ["ja"], "hard", False, history_path=path)
            self.assertGreater(calibrated.seconds, base.seconds)
            self.assertEqual(calibrated.history_samples, 100)
            self.assertEqual(different.history_samples, 0)
            self.assertEqual(len(load_history(path)), 100)

    def test_corrupt_history_and_invalid_samples_do_not_break_estimation(self):
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "history.json"
            for text in ('{bad', '{"samples": [null, {"ratio": "oops"}]}', '[]'):
                path.write_text(text)
                self.assertEqual(load_history(path), [])
                estimate = estimate_processing(60, 100, ["en"], "soft", False, history_path=path)
                self.assertGreater(estimate.seconds, 0)
            record_processing_time(path, estimate, float("nan"))
            self.assertEqual(load_history(path), [])
