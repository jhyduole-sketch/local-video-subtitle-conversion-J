from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from subtitle_tool.cli import main  # noqa: E402
from subtitle_tool.errors import SubtitleToolError  # noqa: E402


class CliTests(unittest.TestCase):
    def test_missing_input_returns_error(self):
        with patch("subtitle_tool.cli.run_pipeline", side_effect=SubtitleToolError("missing")):
            exit_code = main(["missing.mp4", "--target-lang", "zh-CN"])
        self.assertEqual(exit_code, 1)

    def test_target_language_is_optional_for_source_only_output(self):
        with patch("subtitle_tool.cli.run_pipeline") as run_pipeline:
            run_pipeline.return_value.source_subtitle_path = Path("/tmp/source.ja.srt")
            run_pipeline.return_value.translated_paths = {}
            run_pipeline.return_value.failed_languages = {}
            run_pipeline.return_value.source_kind = "audio-local-whisper"
            run_pipeline.return_value.downloaded_video_path = None
            exit_code = main(
                ["input.mp4", "--source-lang", "ja", "--transcriber", "local-whisper"]
            )
        self.assertEqual(exit_code, 0)


if __name__ == "__main__":
    unittest.main()
