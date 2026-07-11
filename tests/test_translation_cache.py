from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from subtitle_tool.srt import SubtitleSegment  # noqa: E402
from subtitle_tool.translation_cache import TranslationCache  # noqa: E402


class TranslationCacheTests(unittest.TestCase):
    def test_round_trip_preserves_translations_and_engine(self):
        segments = [
            SubtitleSegment(index=1, start_ms=0, end_ms=1000, text="hello"),
            SubtitleSegment(index=2, start_ms=1000, end_ms=2000, text="world"),
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = TranslationCache(Path(tmpdir))

            cache.store(segments, "en", "ja", "z-ai", {1: "こんにちは", 2: "世界"}, "z.ai")
            entry = cache.load(segments, "en", "ja", "z-ai")

        self.assertIsNotNone(entry)
        self.assertEqual(entry.translations, {1: "こんにちは", 2: "世界"})
        self.assertEqual(entry.engine, "z.ai")

    def test_changed_source_text_does_not_hit_cache(self):
        original = [SubtitleSegment(index=1, start_ms=0, end_ms=1000, text="hello")]
        changed = [SubtitleSegment(index=1, start_ms=0, end_ms=1000, text="hello again")]
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = TranslationCache(Path(tmpdir))
            cache.store(original, "en", "ja", "z-ai", {1: "こんにちは"}, "z.ai")

            entry = cache.load(changed, "en", "ja", "z-ai")

        self.assertIsNone(entry)

    def test_partial_entry_is_available_for_resume_but_not_complete_cache(self):
        segments = [
            SubtitleSegment(index=1, start_ms=0, end_ms=1000, text="hello"),
            SubtitleSegment(index=2, start_ms=1000, end_ms=2000, text="world"),
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = TranslationCache(Path(tmpdir))
            cache.store_partial(
                segments, "en", "ja", "z-ai", {1: "こんにちは"}, "z.ai"
            )

            complete = cache.load(segments, "en", "ja", "z-ai")
            partial = cache.load_partial(segments, "en", "ja", "z-ai")

        self.assertIsNone(complete)
        self.assertEqual(partial.translations, {1: "こんにちは"})
        self.assertFalse(partial.complete)


if __name__ == "__main__":
    unittest.main()
