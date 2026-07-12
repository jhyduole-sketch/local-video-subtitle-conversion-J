from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from subtitle_tool.errors import SubtitleToolError  # noqa: E402
from subtitle_tool.media_preview import build_media_response  # noqa: E402


class MediaPreviewTests(unittest.TestCase):
    def test_full_media_response_stays_inside_output_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir) / "output"
            video = out_dir / "task" / "video.mp4"
            video.parent.mkdir(parents=True)
            video.write_bytes(b"0123456789")

            response = build_media_response(out_dir, video, None)

        self.assertEqual(response.status, 200)
        self.assertEqual((response.start, response.end, response.length), (0, 9, 10))
        self.assertEqual(response.content_type, "video/mp4")

    def test_range_response_returns_requested_bytes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir) / "output"
            video = out_dir / "task" / "video.mp4"
            video.parent.mkdir(parents=True)
            video.write_bytes(b"0123456789")

            response = build_media_response(out_dir, video, "bytes=2-5")

        self.assertEqual(response.status, 206)
        self.assertEqual((response.start, response.end, response.length), (2, 5, 4))
        self.assertEqual(response.content_range, "bytes 2-5/10")

    def test_suffix_range_returns_tail(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir) / "output"
            video = out_dir / "video.webm"
            video.parent.mkdir(parents=True)
            video.write_bytes(b"0123456789")

            response = build_media_response(out_dir, video, "bytes=-3")

        self.assertEqual((response.start, response.end), (7, 9))

    def test_preview_rejects_path_outside_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            out_dir = root / "output"
            outside = root / "private.mp4"
            outside.write_bytes(b"video")

            with self.assertRaisesRegex(SubtitleToolError, "输出目录"):
                build_media_response(out_dir, outside, None)

    def test_preview_rejects_non_video_extension_and_invalid_range(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir) / "output"
            text = out_dir / "notes.txt"
            text.parent.mkdir(parents=True)
            text.write_text("notes", encoding="utf-8")
            video = out_dir / "video.mp4"
            video.write_bytes(b"1234")

            with self.assertRaisesRegex(SubtitleToolError, "视频文件"):
                build_media_response(out_dir, text, None)
            with self.assertRaisesRegex(SubtitleToolError, "Range"):
                build_media_response(out_dir, video, "bytes=9-12")


if __name__ == "__main__":
    unittest.main()
