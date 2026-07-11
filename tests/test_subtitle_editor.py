from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from subtitle_tool.errors import SubtitleToolError  # noqa: E402
from subtitle_tool.subtitle_editor import (  # noqa: E402
    load_subtitle_document,
    save_subtitle_document,
)


SRT_CONTENT = """1
00:00:01,000 --> 00:00:02,000
Hello

2
00:00:03,000 --> 00:00:04,000
World
"""


class SubtitleEditorTests(unittest.TestCase):
    def test_loads_subtitles_inside_output_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "output"
            path = root / "task" / "subtitles.en.srt"
            path.parent.mkdir(parents=True)
            path.write_text(SRT_CONTENT, encoding="utf-8")

            document = load_subtitle_document(root, path)

        self.assertEqual(document["path"], str(path.resolve()))
        self.assertEqual(len(document["segments"]), 2)
        self.assertEqual(document["segments"][0]["start"], "00:00:01,000")

    def test_rejects_subtitle_path_outside_output_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "output"
            outside = Path(tmpdir) / "outside.srt"
            outside.write_text(SRT_CONTENT, encoding="utf-8")

            with self.assertRaises(SubtitleToolError):
                load_subtitle_document(root, outside)

    def test_saves_valid_edits_and_creates_backup(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "output"
            path = root / "task" / "subtitles.en.srt"
            path.parent.mkdir(parents=True)
            path.write_text(SRT_CONTENT, encoding="utf-8")
            segments = [
                {
                    "start": "00:00:01,200",
                    "end": "00:00:02,400",
                    "text": "Edited subtitle",
                }
            ]

            result = save_subtitle_document(root, path, segments)

            saved = path.read_text(encoding="utf-8")
            backup = path.with_name("subtitles.en.backup.srt")
            backup_text = backup.read_text(encoding="utf-8")

        self.assertEqual(result["count"], 1)
        self.assertIn("Edited subtitle", saved)
        self.assertIn("Hello", backup_text)

    def test_rejects_end_time_before_start_time(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "output"
            path = root / "task" / "subtitles.en.srt"
            path.parent.mkdir(parents=True)
            path.write_text(SRT_CONTENT, encoding="utf-8")

            with self.assertRaisesRegex(SubtitleToolError, "结束时间"):
                save_subtitle_document(
                    root,
                    path,
                    [{"start": "00:00:03,000", "end": "00:00:02,000", "text": "Bad"}],
                )


if __name__ == "__main__":
    unittest.main()
