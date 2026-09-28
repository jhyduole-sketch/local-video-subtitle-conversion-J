from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from subtitle_tool.source_quality import score_source_segments
from subtitle_tool.srt import SubtitleSegment


class SourceQualityTests(unittest.TestCase):
    def test_repeated_short_transcript_scores_lower_than_varied_text(self):
        repeated = [
            SubtitleSegment(index=index, start_ms=index * 1000, end_ms=index * 1000 + 900, text="请上汤。")
            for index in range(1, 21)
        ]
        varied = [
            SubtitleSegment(index=1, start_ms=0, end_ms=1200, text="第一句字幕内容。"),
            SubtitleSegment(index=2, start_ms=1200, end_ms=2600, text="第二句字幕内容。"),
            SubtitleSegment(index=3, start_ms=2600, end_ms=4000, text="第三句字幕内容。"),
        ]

        repeated_quality = score_source_segments(repeated, "zh-CN")
        varied_quality = score_source_segments(varied, "zh-CN")

        self.assertLess(repeated_quality.score, varied_quality.score)
        self.assertIn("重复比例过高", repeated_quality.reasons)

    def test_empty_segments_are_unusable(self):
        quality = score_source_segments([], "ja")

        self.assertEqual(quality.score, 0)
        self.assertIn("没有可用字幕片段", quality.reasons)


    def test_short_valid_caption_is_usable(self):
        self.assertGreaterEqual(score_source_segments([SubtitleSegment(1, 0, 800, "Hi")], "en").score, 60)

    def test_wrong_script_is_rejected(self):
        quality = score_source_segments([SubtitleSegment(1, 0, 800, "This is an English caption")], "zh")
        self.assertLess(quality.score, 35)

    def test_empty_fraction_and_invalid_timing_reduce_quality(self):
        valid = [SubtitleSegment(1, 0, 800, "Hello there")]
        empty = valid + [SubtitleSegment(i, 1000, 2000, "") for i in range(2, 12)]
        invalid = [SubtitleSegment(1, 1000, 900, "Hello there")]
        self.assertLess(score_source_segments(empty, "en").score, 35)
        self.assertLess(score_source_segments(invalid, "en").score, 35)
