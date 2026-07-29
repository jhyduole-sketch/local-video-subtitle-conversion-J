import sys
from pathlib import Path
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from subtitle_tool.atomic_files import (  # noqa: E402
    atomic_output_path,
    atomic_write_text,
    commit_output,
)


class AtomicFileTests(unittest.TestCase):
    def test_atomic_text_write_replaces_existing_content(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "captions.srt"
            path.write_text("old", encoding="utf-8")

            atomic_write_text(path, "new")

            self.assertEqual(path.read_text(encoding="utf-8"), "new")
            self.assertEqual(list(path.parent.glob("*.partial-*")), [])

    def test_generated_output_keeps_final_extension_and_commits(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            final_path = Path(tmpdir) / "video.mp4"
            temporary_path = atomic_output_path(final_path)
            temporary_path.write_bytes(b"complete")

            commit_output(temporary_path, final_path)

            self.assertEqual(temporary_path.suffix, ".mp4")
            self.assertEqual(final_path.read_bytes(), b"complete")
            self.assertFalse(temporary_path.exists())


if __name__ == "__main__":
    unittest.main()
