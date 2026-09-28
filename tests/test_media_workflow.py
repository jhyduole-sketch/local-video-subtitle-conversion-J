"""Real FFmpeg smoke coverage, using a tiny generated fixture and no model calls."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from subtitle_tool.media import find_subtitle_streams, mux_subtitle_tracks
from subtitle_tool.pipeline import PipelineOptions, run_pipeline
from subtitle_tool.srt import read_srt


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg smoke test requires ffmpeg and ffprobe")
class MediaWorkflowTests(unittest.TestCase):
    def test_real_multitrack_video_selects_requested_language_and_reuses_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            english = root / "en.srt"
            japanese = root / "ja.srt"
            english.write_text("1\n00:00:00,000 --> 00:00:01,500\nHello world\n", encoding="utf-8")
            japanese.write_text("1\n00:00:00,000 --> 00:00:01,500\nこんにちは世界\n", encoding="utf-8")
            video = root / "video.mp4"
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=160x90:r=5:d=2", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video)], check=True, capture_output=True, timeout=30)
            multitrack = mux_subtitle_tracks(video, [(english, "eng", "en"), (japanese, "jpn", "ja")], root / "multi.mp4")
            self.assertEqual([s.language for s in find_subtitle_streams(multitrack)], ["eng", "jpn"])
            options = PipelineOptions(str(multitrack), ["ja"], "ja", root / "output", "embedded", "srt", embed_subtitles=True)
            result = run_pipeline(options)
            self.assertEqual(read_srt(result.source_subtitle_path)[0].text, "こんにちは世界")
            self.assertTrue(result.subtitled_video_paths["ja"].is_file())
            self.assertEqual(find_subtitle_streams(result.subtitled_video_paths["ja"])[0].language, "jpn")
            cached = run_pipeline(options)
            self.assertEqual(cached.source_kind, "embedded-cache")
            self.assertEqual(read_srt(cached.translated_paths["ja"])[0].text, "こんにちは世界")


if __name__ == "__main__":
    unittest.main()
