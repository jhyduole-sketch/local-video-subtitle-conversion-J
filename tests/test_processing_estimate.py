from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from subtitle_tool.processing_estimate import estimate_processing


class ProcessingEstimateTests(unittest.TestCase):
    def test_hard_multilingual_video_estimates_more_than_soft_single_language(self):
        soft = estimate_processing(600, 100_000_000, ["ja"], "soft", False)
        hard = estimate_processing(600, 100_000_000, ["ja", "en"], "hard", False)

        self.assertGreater(hard.seconds, soft.seconds)
        self.assertIn("固定位置硬字幕", hard.factors)

    def test_cache_hit_reduces_estimate(self):
        uncached = estimate_processing(600, 100_000_000, ["ja"], "soft", False)
        cached = estimate_processing(600, 100_000_000, ["ja"], "soft", True)

        self.assertLess(cached.seconds, uncached.seconds)


    def test_unknown_duration_has_no_invented_seconds(self):
        for duration in (None, 0, -1, float("nan")):
            self.assertIsNone(estimate_processing(duration, 10, ["ja"], "soft", False).seconds)

    def test_cache_only_reduces_its_own_stage(self):
        common = (600, 100_000_000, ["ja"], "hard", False)
        full = estimate_processing(*common, source_mode="audio", transcriber="local-whisper")
        cached = estimate_processing(*common, source_mode="audio", transcriber="local-whisper", stage_cache={"audio": True})
        self.assertEqual(full.stages["render"], cached.stages["render"])
        self.assertEqual(full.stages["transcription"], cached.stages["transcription"])
        self.assertLess(cached.seconds, full.seconds)
        self.assertLessEqual(full.lower_seconds, full.seconds)
        self.assertGreaterEqual(full.upper_seconds, full.seconds)

    def test_source_and_engine_change_estimate(self):
        common = (600, 100_000_000, ["ja"], "soft", False)
        embedded = estimate_processing(*common, source_mode="embedded")
        local = estimate_processing(*common, source_mode="audio", transcriber="local-whisper")
        self.assertLess(embedded.seconds, local.seconds)
