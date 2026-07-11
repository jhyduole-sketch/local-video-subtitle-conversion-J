from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from subtitle_tool.asset_cache import AssetCache  # noqa: E402


class AssetCacheTests(unittest.TestCase):
    def test_file_fingerprint_changes_with_content(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "video.mp4"
            path.write_bytes(b"first content")
            cache = AssetCache(Path(tmpdir) / "cache")
            first = cache.file_fingerprint(path)
            path.write_bytes(b"second content")
            second = cache.file_fingerprint(path)

        self.assertNotEqual(first, second)

    def test_materialize_video_keeps_cached_source_and_task_copy(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cached = root / "cache" / "videos" / "youtube-abc.mp4"
            cached.parent.mkdir(parents=True)
            cached.write_bytes(b"video")
            target = root / "output" / "task" / "abc.202607110101010.mp4"

            result = AssetCache(root / "cache").materialize_video(cached, target)

            self.assertEqual(result, target)
            self.assertEqual(target.read_bytes(), b"video")
            self.assertTrue(cached.exists())

    def test_summary_and_selective_clear_do_not_touch_output_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cache = AssetCache(root / ".subtitle-tool-cache")
            video = cache.root / "videos" / "video.mp4"
            transcript = cache.root / "transcripts" / "source.srt"
            output = root / "task-output" / "finished.mp4"
            for path, content in (
                (video, b"video"),
                (transcript, b"subtitle"),
                (output, b"finished"),
            ):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)

            before = cache.summary()
            cleared = cache.clear(["videos"])

            self.assertEqual(before["categories"]["videos"]["files"], 1)
            self.assertEqual(before["categories"]["transcripts"]["files"], 1)
            self.assertEqual(cleared["cleared"], ["videos"])
            self.assertFalse(video.exists())
            self.assertTrue(transcript.exists())
            self.assertEqual(output.read_bytes(), b"finished")

    def test_subtitle_detection_cache_round_trip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = AssetCache(Path(tmpdir) / "cache")
            payload = {
                "position": "bottom",
                "confidence": 0.88,
                "sampledFrames": 8,
                "topScore": 0.02,
                "bottomScore": 0.2,
            }

            cache.store_subtitle_detection("video-fingerprint", payload)
            loaded = cache.load_subtitle_detection("video-fingerprint")

        self.assertEqual(loaded, payload)


if __name__ == "__main__":
    unittest.main()
