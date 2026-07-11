from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from subtitle_tool.runtime_paths import cache_root, state_database_path  # noqa: E402


class RuntimePathsTests(unittest.TestCase):
    def test_state_database_moves_out_of_output_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            out_dir = root / "output"
            legacy = out_dir / ".subtitle-tool-state" / "jobs.sqlite3"
            legacy.parent.mkdir(parents=True)
            legacy.write_bytes(b"legacy-state")

            resolved = state_database_path(root, out_dir)

            self.assertEqual(resolved, root / ".subtitle-tool-state" / "jobs.sqlite3")
            self.assertEqual(resolved.read_bytes(), b"legacy-state")
            self.assertFalse((out_dir / ".subtitle-tool-state").exists())

    def test_cache_root_merges_legacy_cache_and_removes_it_from_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            out_dir = root / "output"
            legacy_file = out_dir / ".subtitle-tool-cache" / "audio" / "clip.mp3"
            legacy_file.parent.mkdir(parents=True)
            legacy_file.write_bytes(b"audio")

            resolved = cache_root(out_dir)

            self.assertEqual(resolved, root / ".subtitle-tool-cache")
            self.assertEqual((resolved / "audio" / "clip.mp3").read_bytes(), b"audio")
            self.assertFalse((out_dir / ".subtitle-tool-cache").exists())

    def test_existing_state_database_keeps_legacy_copy_as_archive(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            out_dir = root / "output"
            current = root / ".subtitle-tool-state" / "jobs.sqlite3"
            current.parent.mkdir(parents=True)
            current.write_bytes(b"current-state")
            legacy = out_dir / ".subtitle-tool-state" / "jobs.sqlite3"
            legacy.parent.mkdir(parents=True)
            legacy.write_bytes(b"legacy-state")

            resolved = state_database_path(root, out_dir)

            self.assertEqual(resolved.read_bytes(), b"current-state")
            archives = list(current.parent.glob("jobs.legacy*.sqlite3"))
            self.assertEqual(len(archives), 1)
            self.assertEqual(archives[0].read_bytes(), b"legacy-state")
            self.assertFalse((out_dir / ".subtitle-tool-state").exists())

    def test_custom_output_directory_gets_an_isolated_sibling_cache(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir) / "client-results"

            resolved = cache_root(out_dir)

            self.assertEqual(
                resolved,
                Path(tmpdir) / ".client-results.subtitle-tool-cache",
            )


if __name__ == "__main__":
    unittest.main()
