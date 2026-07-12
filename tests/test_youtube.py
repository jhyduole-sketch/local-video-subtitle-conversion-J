from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from subtitle_tool.youtube import (  # noqa: E402
    download_bilibili_video,
    download_youtube_video,
    extract_bilibili_id,
    extract_youtube_id,
    is_bilibili_url,
    is_youtube_url,
)
from subtitle_tool import youtube  # noqa: E402
from subtitle_tool.errors import SubtitleToolError  # noqa: E402


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

    def test_detects_bilibili_urls(self):
        value = "https://www.bilibili.com/video/BV1rR4y197tP/?spm_id_from=333"

        self.assertTrue(is_bilibili_url(value))
        self.assertEqual(extract_bilibili_id(value), "BV1rR4y197tP")
        self.assertFalse(is_bilibili_url("https://example.com/video/BV1rR4y197tP"))

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
                "subtitle_tool.youtube.run_process", side_effect=fake_run
            ):
                video = download_youtube_video(
                    "https://www.youtube.com/watch?v=abc123",
                    out_dir,
                    timestamp_suffix="202607091530129",
                )

        self.assertEqual(video.path.name, "abc123.202607091530129.mp4")
        self.assertIn("bv*[ext=mp4]+ba[ext=m4a]/bv*+ba/b[ext=mp4]/b", commands[0])
        self.assertIn("--no-playlist", commands[0])

    def test_bilibili_download_output_path_uses_timestamp_suffix(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)
            output_path = out_dir / "BV1rR4y197tP.202607091530129.mp4"
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
                "subtitle_tool.youtube.run_process", side_effect=fake_run
            ):
                video = download_bilibili_video(
                    "https://www.bilibili.com/video/BV1rR4y197tP/?spm_id_from=333",
                    out_dir,
                    timestamp_suffix="202607091530129",
                )

        self.assertEqual(video.path.name, "BV1rR4y197tP.202607091530129.mp4")
        self.assertIn("https://www.bilibili.com/video/BV1rR4y197tP/?spm_id_from=333", commands[0])

    def test_generic_download_probes_and_downloads_single_video(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)
            output_path = out_dir / "clip-42.mp4"
            commands = []

            def fake_run(command, **kwargs):
                commands.append(command)

                class Completed:
                    returncode = 0
                    stderr = ""
                    stdout = '{"id":"clip-42","title":"Example","live_status":"not_live"}'

                if "--skip-download" not in command:
                    output_path.write_bytes(b"video")
                    Completed.stdout = ""
                return Completed()

            with patch("subtitle_tool.youtube.shutil.which", return_value="/bin/yt-dlp"), patch(
                "subtitle_tool.youtube.run_process", side_effect=fake_run
            ):
                video = youtube.download_generic_video(
                    "https://media.example/videos/42",
                    out_dir,
                )

        self.assertEqual(video.video_id, "clip-42")
        self.assertEqual(video.path.name, "clip-42.mp4")
        self.assertIn("--dump-single-json", commands[0])
        self.assertIn("--skip-download", commands[0])
        self.assertIn("--no-playlist", commands[1])

    def test_generic_download_rejects_playlist_metadata(self):
        class Completed:
            returncode = 0
            stderr = ""
            stdout = '{"id":"list-1","_type":"playlist","entries":[{"id":"a"}]}'

        with tempfile.TemporaryDirectory() as tmpdir, patch(
            "subtitle_tool.youtube.shutil.which", return_value="/bin/yt-dlp"
        ), patch("subtitle_tool.youtube.run_process", return_value=Completed()):
            with self.assertRaisesRegex(SubtitleToolError, "播放列表"):
                youtube.download_generic_video(
                    "https://media.example/playlist/1",
                    Path(tmpdir),
                )

    def test_generic_download_explains_login_required(self):
        class Completed:
            returncode = 1
            stdout = ""
            stderr = "ERROR: Sign in to confirm your age. Use --cookies-from-browser"

        with tempfile.TemporaryDirectory() as tmpdir, patch(
            "subtitle_tool.youtube.shutil.which", return_value="/bin/yt-dlp"
        ), patch("subtitle_tool.youtube.run_process", return_value=Completed()):
            with self.assertRaisesRegex(SubtitleToolError, "需要登录"):
                youtube.download_generic_video(
                    "https://media.example/private/1",
                    Path(tmpdir),
                )
