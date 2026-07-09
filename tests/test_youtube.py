from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from subtitle_tool.youtube import download_youtube_video, extract_youtube_id, is_youtube_url  # noqa: E402


class YouTubeTests(unittest.TestCase):
    def test_detects_youtube_urls(self):
        self.assertTrue(is_youtube_url("https://www.youtube.com/watch?v=abc123"))
        self.assertTrue(is_youtube_url("https://youtu.be/abc123"))
        self.assertFalse(is_youtube_url("https://example.com/watch?v=abc123"))

    def test_extracts_video_id(self):
        self.assertEqual(extract_youtube_id("https://www.youtube.com/watch?v=abc123"), "abc123")
        self.assertEqual(extract_youtube_id("https://youtu.be/abc123"), "abc123")

    def test_ignores_trailing_sentence_punctuation(self):
        value = "https://www.youtube.com/watch?v=ftWe_pVrtho。"

        self.assertTrue(is_youtube_url(value))
        self.assertEqual(extract_youtube_id(value), "ftWe_pVrtho")

    def test_download_output_path_uses_timestamp_suffix(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)
            output_path = out_dir / "abc123.202607091530129.mp4"
            commands = []

            def fake_run(*args, **kwargs):
                commands.append(args[0])
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(b"video")

                class Completed:
                    returncode = 0
                    stdout = ""
                    stderr = ""

                return Completed()

            with patch("subtitle_tool.youtube.shutil.which", return_value="/bin/yt-dlp"), patch(
                "subtitle_tool.youtube.subprocess.run", side_effect=fake_run
            ):
                video = download_youtube_video(
                    "https://www.youtube.com/watch?v=abc123",
                    out_dir,
                    timestamp_suffix="202607091530129",
                )

        self.assertEqual(video.path.name, "abc123.202607091530129.mp4")
        self.assertIn("bv*[ext=mp4]+ba[ext=m4a]/bv*+ba/b[ext=mp4]/b", commands[0])
        self.assertIn("--no-playlist", commands[0])
