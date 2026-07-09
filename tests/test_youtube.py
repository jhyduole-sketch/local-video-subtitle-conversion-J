from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from subtitle_tool.youtube import extract_youtube_id, is_youtube_url  # noqa: E402


class YouTubeTests(unittest.TestCase):
    def test_detects_youtube_urls(self):
        self.assertTrue(is_youtube_url("https://www.youtube.com/watch?v=abc123"))
        self.assertTrue(is_youtube_url("https://youtu.be/abc123"))
        self.assertFalse(is_youtube_url("https://example.com/watch?v=abc123"))

    def test_extracts_video_id(self):
        self.assertEqual(extract_youtube_id("https://www.youtube.com/watch?v=abc123"), "abc123")
        self.assertEqual(extract_youtube_id("https://youtu.be/abc123"), "abc123")

