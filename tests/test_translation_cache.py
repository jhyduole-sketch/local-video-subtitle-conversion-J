from pathlib import Path
import sys
import json
import sqlite3
import subprocess
import os
from unittest.mock import patch
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from subtitle_tool.srt import SubtitleSegment  # noqa: E402
from subtitle_tool.translation_cache import TranslationCache  # noqa: E402


class TranslationCacheTests(unittest.TestCase):
    def test_malformed_cache_is_a_miss(self):
        segments = [SubtitleSegment(1, 0, 1000, "hello")]
        for invalid in (None, [], {"1": None}, {"1": 42}, {"1": {}}, {"1": "  "}, {"bad": "text"}):
            with self.subTest(value=invalid), tempfile.TemporaryDirectory() as directory:
                cache = TranslationCache(Path(directory))
                cache._path(segments, "en", "ja", "z-ai").write_text(
                    json.dumps({"translations": invalid, "engine": "z.ai"})
                )
                self.assertIsNone(cache.load_partial(segments, "en", "ja", "z-ai"))
        for engine in (None, [], 42, ""):
            with self.subTest(engine=engine), tempfile.TemporaryDirectory() as directory:
                cache = TranslationCache(Path(directory))
                cache._path(segments, "en", "ja", "z-ai").write_text(
                    json.dumps({"translations": {"1": "hello"}, "engine": engine})
                )
                self.assertIsNone(cache.load_partial(segments, "en", "ja", "z-ai"))

    def test_bound_session_computes_identity_once_and_writes_only_changed_rows(self):
        segments = [SubtitleSegment(i, 0, 1000, str(i)) for i in range(1, 4)]
        with tempfile.TemporaryDirectory() as directory:
            cache = TranslationCache(Path(directory))
            with patch.object(cache, "_path", wraps=cache._path) as identity:
                session = cache.bind(segments, "en", "ja", "z-ai")
                self.assertIsNone(session.load_partial())
                session.store_partial({1: "one"}, "z.ai")
                with sqlite3.connect(session.path) as db:
                    db.executescript("CREATE TABLE writes (n INTEGER); INSERT INTO writes VALUES (0); "
                                     "CREATE TRIGGER count_updates AFTER UPDATE ON translations "
                                     "BEGIN UPDATE writes SET n=n+1; END;")
                session.store_partial({1: "one", 2: "two"}, "z.ai")
                session.store_partial({1: "one", 2: "two", 3: "three"}, "z.ai")
                self.assertEqual(identity.call_count, 1)
                with sqlite3.connect(session.path) as db:
                    self.assertEqual(db.execute("SELECT n FROM writes").fetchone()[0], 0)
                self.assertTrue(session.load_partial().complete)

    def test_independent_sessions_merge_and_force_clear_discards_old_checkpoint(self):
        segments = [SubtitleSegment(i, 0, 1000, str(i)) for i in (1, 2)]
        with tempfile.TemporaryDirectory() as directory:
            cache = TranslationCache(Path(directory))
            first = cache.bind(segments, "en", "ja", "z-ai")
            second = cache.bind(segments, "en", "ja", "z-ai")
            first.load_partial()
            second.load_partial()
            first.store_partial({1: "one"}, "z.ai")
            second.store_partial({2: "two"}, "z.ai")
            self.assertEqual(cache.load(segments, "en", "ja", "z-ai").translations, {1: "one", 2: "two"})
            fresh = cache.bind(segments, "en", "ja", "z-ai")
            fresh.clear()
            fresh.store_partial({2: "new"}, "z.ai")
            self.assertEqual(cache.load_partial(segments, "en", "ja", "z-ai").translations, {2: "new"})

    def test_corrupt_sqlite_cache_recovers_on_next_successful_batch(self):
        segments = [SubtitleSegment(1, 0, 1000, "hello")]
        with tempfile.TemporaryDirectory() as directory:
            cache = TranslationCache(Path(directory))
            session = cache.bind(segments, "en", "ja", "z-ai")
            session.path.write_bytes(b"not a database")
            self.assertIsNone(session.load_partial())
            session.store_partial({1: "new"}, "z.ai")
            self.assertEqual(cache.load(segments, "en", "ja", "z-ai").translations, {1: "new"})

    def test_invalid_sqlite_value_does_not_poison_future_checkpoints(self):
        segments = [SubtitleSegment(i, 0, 1000, str(i)) for i in (1, 2)]
        with tempfile.TemporaryDirectory() as directory:
            cache = TranslationCache(Path(directory))
            session = cache.bind(segments, "en", "ja", "z-ai")
            session.store_partial({1: "valid"}, "z.ai")
            with sqlite3.connect(session.path) as db:
                db.execute("UPDATE translations SET text=x'ff'")
            fresh = cache.bind(segments, "en", "ja", "z-ai")
            self.assertIsNone(fresh.load_partial())
            fresh.store_partial({2: "new"}, "z.ai")
            self.assertEqual(cache.load_partial(segments, "en", "ja", "z-ai").translations, {2: "new"})

    def test_corrupt_table_page_recovers_during_read_and_write(self):
        segments = [SubtitleSegment(i, 0, 1000, str(i)) for i in (1, 2)]
        for operation in ("read", "write"):
            with self.subTest(operation=operation), tempfile.TemporaryDirectory() as directory:
                cache = TranslationCache(Path(directory))
                session = cache.bind(segments, "en", "ja", "z-ai")
                session.store_partial({1: "old"}, "z.ai")
                with sqlite3.connect(session.path) as db:
                    page = db.execute("SELECT rootpage FROM sqlite_master WHERE name='translations'").fetchone()[0]
                    size = db.execute("PRAGMA page_size").fetchone()[0]
                with session.path.open("r+b") as file:
                    file.seek((page - 1) * size)
                    file.write(b"\x00")
                if operation == "read":
                    session = cache.bind(segments, "en", "ja", "z-ai")
                    self.assertIsNone(session.load_partial())
                session.store_partial({2: "new"}, "z.ai")
                self.assertEqual(cache.load_partial(segments, "en", "ja", "z-ai").translations.get(2), "new")
                self.assertTrue(session.path.with_suffix(".corrupt").exists())

    def test_two_processes_keep_all_independent_checkpoint_rows(self):
        segments = [SubtitleSegment(i, 0, 1000, str(i)) for i in range(1, 21)]
        code = """
from pathlib import Path
import sys, time
from subtitle_tool.translation_cache import TranslationCache
from subtitle_tool.srt import SubtitleSegment
segments = [SubtitleSegment(i, 0, 1000, str(i)) for i in range(1, 21)]
session = TranslationCache(Path(sys.argv[1])).bind(segments, 'en', 'ja', 'z-ai')
session.load_partial()
for index in range(int(sys.argv[2]), 21, 2):
    session.store_partial({index: str(index)}, 'z.ai')
    time.sleep(.002)
"""
        with tempfile.TemporaryDirectory() as directory:
            env = {**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'src')}
            children = [subprocess.Popen([sys.executable, '-c', code, directory, str(start)],
                                         env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for start in (1, 2)]
            try:
                for child in children:
                    out, error = child.communicate(timeout=10)
                    self.assertEqual(child.returncode, 0, error.decode())
                result = TranslationCache(Path(directory)).load(segments, 'en', 'ja', 'z-ai')
                self.assertEqual(result.translations, {i: str(i) for i in range(1, 21)})
            finally:
                for child in children:
                    if child.poll() is None:
                        child.kill()
                    child.communicate()

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
