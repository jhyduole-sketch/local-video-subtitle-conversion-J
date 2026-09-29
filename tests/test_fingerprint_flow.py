from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
import os
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from subtitle_tool.asset_cache import AssetCache
from subtitle_tool.errors import CancellationError
from subtitle_tool.pipeline import PipelineOptions, _load_source_segments, run_pipeline
from subtitle_tool.runtime_paths import cache_root
from subtitle_tool.srt import SubtitleSegment, read_srt, write_srt


@contextmanager
def observe_video_reads(video, on_read=None):
    original_open = Path.open
    reads = []

    class Reader:
        def __init__(self, handle):
            self.handle = handle

        def __enter__(self):
            self.handle.__enter__()
            return self

        def __exit__(self, *args):
            return self.handle.__exit__(*args)

        def read(self, size):
            data = self.handle.read(size)
            reads.append(len(data))
            if on_read is not None:
                on_read(data)
            return data

        def __getattr__(self, name):
            return getattr(self.handle, name)

    def open_path(path, mode="r", *args, **kwargs):
        handle = original_open(path, mode, *args, **kwargs)
        return Reader(handle) if path.name == video.name and mode == "rb" else handle

    with patch.object(Path, "open", open_path):
        yield reads


class FingerprintFlowTests(unittest.TestCase):
    def test_pipeline_reads_video_once_and_uses_matching_source_cache(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            video = root / "input.mp4"
            video.write_bytes(b"video bytes" * 100)
            options = PipelineOptions(str(video), [], "en", root / "output", "embedded", "srt")
            cache = AssetCache(cache_root(options.out_dir))
            fingerprint = cache.file_fingerprint(video)
            expected = [SubtitleSegment(1, 0, 1000, "This is the cached caption.")]
            write_srt(cache.source_subtitle_path(fingerprint, "embedded-en"), expected)
            progress = []
            options = replace(options, progress_callback=lambda message, percent: progress.append(message))
            with observe_video_reads(video) as reads, patch(
                "subtitle_tool.pipeline.probe_duration_seconds", return_value=1
            ):
                result = run_pipeline(options)
            self.assertEqual(read_srt(result.source_subtitle_path), expected)
            self.assertEqual(result.source_kind, "embedded-cache")
            self.assertEqual(sum(reads), video.stat().st_size)
            self.assertTrue(any("指纹" in message for message in progress))

    def test_supplied_fingerprint_avoids_reopening_input(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            video = root / "not-opened.mp4"
            cache = AssetCache(root / "cache")
            expected = [SubtitleSegment(1, 0, 1000, "Cached caption.")]
            write_srt(cache.source_subtitle_path("provided", "embedded-en"), expected)
            options = PipelineOptions(str(video), [], "en", root, "embedded", "srt")
            segments, kind = _load_source_segments(options, video, cache, video_fingerprint="provided")
            self.assertEqual(segments, expected)
            self.assertEqual(kind, "embedded-cache")

    def test_independent_source_calls_rehash_changed_content(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            video = root / "input.mp4"
            cache = AssetCache(root / "cache")
            options = PipelineOptions(str(video), [], "en", root, "embedded", "srt")
            fingerprints = []
            for content, caption in ((b"first", "First caption."), (b"other", "Other caption.")):
                video.write_bytes(content)
                os.utime(video, ns=(1_700_000_000_000_000_000, 1_700_000_000_000_000_000))
                expected = [SubtitleSegment(1, 0, 1000, caption)]
                fingerprint = cache.file_fingerprint(video)
                fingerprints.append(fingerprint)
                write_srt(cache.source_subtitle_path(fingerprint, "embedded-en"), expected)
                segments, _ = _load_source_segments(options, video, cache)
                self.assertEqual(segments, expected)
            self.assertNotEqual(fingerprints[0], fingerprints[1])

    def test_hash_cancels_before_opening_input(self):
        with TemporaryDirectory() as directory:
            cache = AssetCache(Path(directory) / "cache")
            with self.assertRaises(CancellationError):
                cache.file_fingerprint(Path(directory) / "missing", cancel_check=lambda: True)

    def test_hash_checks_cancellation_between_bounded_reads(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            video = root / "input.mp4"
            video.write_bytes(b"x" * (4 * 1024 * 1024))
            cache = AssetCache(root / "cache")
            cancelled = [False]
            def cancel_after_read(data):
                cancelled[0] = True
            with observe_video_reads(video, cancel_after_read) as reads:
                with self.assertRaises(CancellationError):
                    cache.file_fingerprint(video, cancel_check=lambda: cancelled[0])
            self.assertLessEqual(sum(reads), 1024 * 1024)
            self.assertGreater(sum(reads), 0)

    def test_hash_cancels_after_final_progress_callback(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            video = root / "input.mp4"
            video.write_bytes(b"video")
            cancelled = [False]
            def progress(done, total):
                if done == total:
                    cancelled[0] = True
            with self.assertRaises(CancellationError):
                AssetCache(root / "cache").file_fingerprint(
                    video, cancel_check=lambda: cancelled[0], progress_callback=progress
                )

    def test_hash_progress_is_throttled_and_reports_completion(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            video = root / "input.mp4"
            video.write_bytes(b"x" * (8 * 1024 * 1024))
            clock = [0.0]
            events = []
            def advance(data):
                if data:
                    clock[0] += 0.2
            with observe_video_reads(video, advance), patch(
                "subtitle_tool.asset_cache.monotonic", side_effect=lambda: clock[0], create=True
            ):
                fingerprint = AssetCache(root / "cache").file_fingerprint(
                    video, progress_callback=lambda done, total: events.append((clock[0], done, total))
                )
            self.assertEqual(events[0][1:], (0, video.stat().st_size))
            self.assertEqual(events[-1][1:], (video.stat().st_size, video.stat().st_size))
            self.assertGreater(len(events), 2)
            self.assertLess(len(events), 8)
            self.assertTrue(all(later[0] - earlier[0] >= 0.5 for earlier, later in zip(events[:-2], events[1:-1])))
            self.assertEqual(fingerprint, AssetCache(root / "cache").file_fingerprint(video))

    def test_independent_source_hash_honors_cancellation(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            video = root / "input.mp4"
            video.write_bytes(b"x" * (4 * 1024 * 1024))
            cancelled = [False]
            options = PipelineOptions(str(video), [], "en", root, "embedded", "srt", cancel_check=lambda: cancelled[0])
            def cancel_after_read(data):
                cancelled[0] = True
            with observe_video_reads(video, cancel_after_read) as reads:
                with self.assertRaises(CancellationError):
                    _load_source_segments(options, video, AssetCache(root / "cache"))
            self.assertLessEqual(sum(reads), 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
