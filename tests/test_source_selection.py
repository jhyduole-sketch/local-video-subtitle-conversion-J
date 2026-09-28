from pathlib import Path
from tempfile import TemporaryDirectory
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from subtitle_tool.asset_cache import AssetCache
from subtitle_tool.errors import CancellationError, MediaError
from subtitle_tool.media import SubtitleStream
from subtitle_tool.pipeline import PipelineOptions, _load_source_segments
from subtitle_tool.srt import SubtitleSegment, write_srt


class EmbeddedCacheRecoveryTests(unittest.TestCase):
    def test_interrupted_extraction_is_not_reused_as_complete_cache(self):
        for error in (CancellationError("cancelled"), MediaError("ffmpeg failed")):
            with self.subTest(error=type(error).__name__), TemporaryDirectory() as directory:
                root = Path(directory)
                video = root / "video.mp4"
                video.write_bytes(b"video")
                cache = AssetCache(root / "cache")
                options = PipelineOptions(str(video), [], "en", root / "out", "embedded", "srt")
                first = [SubtitleSegment(1, 0, 1000, "First caption")]
                complete = first + [SubtitleSegment(2, 1000, 2000, "Second caption")]
                def interrupted(video, output, cancel_check):
                    write_srt(output, first)
                    raise error
                def successful(video, output, cancel_check):
                    write_srt(output, complete)
                with patch("subtitle_tool.pipeline.find_subtitle_streams", return_value=[SubtitleStream(1, "subrip", "eng", None)]):
                    with patch("subtitle_tool.pipeline.extract_first_subtitle", side_effect=interrupted):
                        with self.assertRaises(type(error)):
                            _load_source_segments(options, video, cache)
                    with patch("subtitle_tool.pipeline.extract_first_subtitle", side_effect=successful):
                        segments, _ = _load_source_segments(options, video, cache)
                self.assertEqual(segments, complete)
                self.assertFalse(list((cache.root / "source-subtitles").glob(".*partial*")))
