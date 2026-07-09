from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from subtitle_tool.srt import (  # noqa: E402
    SubtitleSegment,
    format_timestamp,
    parse_srt,
    parse_timestamp,
    render_srt,
    replace_text,
)


class SrtTests(unittest.TestCase):
    def test_timestamp_round_trip(self):
        value = "01:02:03,456"
        self.assertEqual(format_timestamp(parse_timestamp(value)), value)

    def test_parse_and_render_srt(self):
        content = """1
00:00:01,000 --> 00:00:03,250
Hello
world

2
00:00:04,000 --> 00:00:05,000
Bye
"""
        segments = parse_srt(content)
        self.assertEqual(len(segments), 2)
        self.assertEqual(segments[0].text, "Hello\nworld")
        self.assertEqual(segments[1].start_ms, 4000)
        self.assertEqual(render_srt(segments), content)

    def test_replace_text_preserves_timing(self):
        source = [SubtitleSegment(index=7, start_ms=100, end_ms=900, text="Hello")]
        translated = replace_text(source, {7: "こんにちは"})
        self.assertEqual(translated[0].start_ms, 100)
        self.assertEqual(translated[0].end_ms, 900)
        self.assertEqual(translated[0].text, "こんにちは")


if __name__ == "__main__":
    unittest.main()

