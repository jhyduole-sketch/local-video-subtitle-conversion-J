from io import BytesIO
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from subtitle_tool.errors import SubtitleToolError  # noqa: E402
from subtitle_tool.pipeline import PipelineOptions, run_pipeline  # noqa: E402
from subtitle_tool.talksmith import (  # noqa: E402
    TalkSmithVideo,
    download_video,
    extract_scenario_id,
    find_available_video,
    is_talksmith_url,
)


class TalkSmithTests(unittest.TestCase):
    def test_identifies_talksmith_share_url(self):
        self.assertTrue(is_talksmith_url("https://service.talk-smith.com/s?id=abc"))
        self.assertFalse(is_talksmith_url("https://example.com/s?id=abc"))

    def test_extract_scenario_id(self):
        self.assertEqual(
            extract_scenario_id("https://service.talk-smith.com/s?id=cmd123"),
            "cmd123",
        )

    def test_extract_scenario_id_requires_id(self):
        with self.assertRaises(SubtitleToolError):
            extract_scenario_id("https://service.talk-smith.com/s")

    def test_find_available_video(self):
        video = find_available_video(
            {
                "publishedSlides": [
                    {"type": "SELECTION"},
                    {
                        "type": "VIDEO",
                        "publishedVideoSlideContent": {
                            "video": {"status": "AVAILABLE", "url": "https://cdn/video"}
                        },
                    },
                ]
            },
            "cmd123",
        )
        self.assertEqual(video.scenario_id, "cmd123")
        self.assertEqual(video.video_url, "https://cdn/video")

    def test_download_video_uses_timestamp_suffix(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("subtitle_tool.talksmith.urllib.request.urlopen") as urlopen:
                urlopen.return_value.__enter__.return_value = BytesIO(b"video")
                path = download_video(
                    TalkSmithVideo("cmd123", "https://cdn/video.mp4"),
                    Path(tmpdir),
                    timestamp_suffix="202607091530129",
                )

        self.assertEqual(path.name, "cmd123.202607091530129.mp4")

    def test_download_only_skips_subtitle_generation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            video_path = Path(tmpdir) / "cmd123" / "cmd123.202607091530129.mp4"
            video_path.parent.mkdir()
            video_path.write_bytes(b"video")
            with patch(
                "subtitle_tool.pipeline.resolve_talksmith_input", return_value=video_path
            ) as resolve, patch(
                "subtitle_tool.pipeline._load_source_segments"
            ) as load_segments:
                result = run_pipeline(
                    PipelineOptions(
                        input_value="https://service.talk-smith.com/s?id=cmd123",
                        target_langs=[],
                        source_lang=None,
                        out_dir=Path(tmpdir),
                        source="auto",
                        output_format="srt",
                        download_only=True,
                    )
                )
                downloaded_name = result.downloaded_video_path.name
                downloaded_bytes = result.downloaded_video_path.read_bytes()

        resolve.assert_called_once()
        load_segments.assert_not_called()
        self.assertRegex(downloaded_name, r"cmd123\.\d{15}\.mp4")
        self.assertEqual(downloaded_bytes, b"video")
        self.assertIsNone(result.source_subtitle_path)


if __name__ == "__main__":
    unittest.main()
