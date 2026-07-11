from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from subtitle_tool.srt import SubtitleSegment  # noqa: E402
from subtitle_tool.subtitle_layout import (  # noqa: E402
    display_width,
    layout_subtitles,
    write_ass,
)


class SubtitleLayoutTests(unittest.TestCase):
    def test_wraps_english_to_at_most_two_lines_without_losing_words(self):
        source = [
            SubtitleSegment(
                index=1,
                start_ms=0,
                end_ms=4000,
                text="one two three four five six",
            )
        ]

        result = layout_subtitles(source, max_width=10, max_lines=2)

        self.assertGreater(len(result), 1)
        self.assertEqual(
            " ".join(
                word
                for segment in result
                for word in segment.text.replace("\n", " ").split()
            ),
            source[0].text,
        )
        for segment in result:
            lines = segment.text.splitlines()
            self.assertLessEqual(len(lines), 2)
            self.assertTrue(all(display_width(line) <= 10 for line in lines))

    def test_counts_cjk_characters_as_double_width(self):
        source = [
            SubtitleSegment(
                index=4,
                start_ms=100,
                end_ms=4100,
                text="你好世界字幕测试完成",
            )
        ]

        result = layout_subtitles(source, max_width=6, max_lines=2)

        self.assertEqual("".join(item.text.replace("\n", "") for item in result), source[0].text)
        self.assertTrue(all(display_width(line) <= 6 for item in result for line in item.text.splitlines()))
        self.assertEqual([item.index for item in result], list(range(1, len(result) + 1)))

    def test_repairs_overlapping_timestamps(self):
        source = [
            SubtitleSegment(index=1, start_ms=0, end_ms=1000, text="First"),
            SubtitleSegment(index=2, start_ms=800, end_ms=1600, text="Second"),
        ]

        result = layout_subtitles(source, min_gap_ms=40)

        self.assertLessEqual(result[0].end_ms + 40, result[1].start_ms)
        self.assertGreater(result[0].end_ms, result[0].start_ms)
        self.assertGreater(result[1].end_ms, result[1].start_ms)

    def test_short_cue_keeps_all_text_when_it_cannot_be_safely_split(self):
        source = [
            SubtitleSegment(
                index=1,
                start_ms=0,
                end_ms=300,
                text="A sentence that is much too long for this short cue",
            )
        ]

        result = layout_subtitles(source, max_width=10, max_lines=2)

        self.assertEqual(
            " ".join(
                word for item in result for word in item.text.replace("\n", " ").split()
            ),
            source[0].text,
        )
        self.assertTrue(all(item.end_ms > item.start_ms for item in result))

    def test_ass_above_bottom_uses_extra_bottom_margin(self):
        segments = [
            SubtitleSegment(index=1, start_ms=1000, end_ms=2500, text="Hello\nworld")
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "subtitle.ass"
            write_ass(path, segments, "above-bottom")
            content = path.read_text(encoding="utf-8")

        self.assertIn("Alignment=2", content)
        self.assertIn("MarginV=190", content)
        self.assertIn("Style: Default,Arial Unicode MS", content)
        self.assertIn("Dialogue: 0,0:00:01.00,0:00:02.50", content)
        self.assertIn("Hello\\Nworld", content)

    def test_ass_top_uses_top_alignment(self):
        segments = [SubtitleSegment(index=1, start_ms=0, end_ms=1000, text="Top")]
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "subtitle.ass"
            write_ass(path, segments, "top")
            content = path.read_text(encoding="utf-8")

        self.assertIn("Alignment=8", content)
        self.assertIn("MarginV=70", content)


if __name__ == "__main__":
    unittest.main()
