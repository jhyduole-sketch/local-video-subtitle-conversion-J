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
            run_pipeline.return_value.subtitled_video_paths = None
            exit_code = main(
                ["input.mp4", "--source-lang", "ja", "--transcriber", "local-whisper"]
            )
        self.assertEqual(exit_code, 0)

    def test_zai_translator_option_is_passed_to_pipeline(self):
        with patch("subtitle_tool.cli.run_pipeline") as run_pipeline:
            run_pipeline.return_value.source_subtitle_path = Path("/tmp/source.zh.srt")
            run_pipeline.return_value.translated_paths = {"ja": Path("/tmp/subtitles.ja.srt")}
            run_pipeline.return_value.failed_languages = {}
            run_pipeline.return_value.source_kind = "audio-local-whisper"
            run_pipeline.return_value.downloaded_video_path = None
            run_pipeline.return_value.subtitled_video_paths = None
            exit_code = main(
                [
                    "input.mp4",
                    "--source-lang",
                    "zh",
                    "--target-lang",
                    "ja",
                    "--translator",
                    "z-ai",
                ]
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(run_pipeline.call_args.args[0].translator, "z-ai")

    def test_local_nllb_translator_option_is_passed_to_pipeline(self):
        with patch("subtitle_tool.cli.run_pipeline") as run_pipeline:
            run_pipeline.return_value.source_subtitle_path = Path("/tmp/source.zh.srt")
            run_pipeline.return_value.translated_paths = {"vi": Path("/tmp/subtitles.vi.srt")}
            run_pipeline.return_value.failed_languages = {}
            run_pipeline.return_value.source_kind = "audio-local-whisper"
            run_pipeline.return_value.downloaded_video_path = None
            run_pipeline.return_value.subtitled_video_paths = None
            exit_code = main(
                [
                    "input.mp4",
                    "--source-lang",
                    "zh",
                    "--target-lang",
                    "vi",
                    "--translator",
                    "local-nllb",
                ]
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(run_pipeline.call_args.args[0].translator, "local-nllb")

    def test_hard_subtitle_video_options_are_passed_to_pipeline(self):
        with patch("subtitle_tool.cli.run_pipeline") as run_pipeline:
            run_pipeline.return_value.source_subtitle_path = Path("/tmp/source.ja.srt")
            run_pipeline.return_value.translated_paths = {"en": Path("/tmp/en.srt")}
            run_pipeline.return_value.failed_languages = {}
            run_pipeline.return_value.source_kind = "audio-local-whisper"
            run_pipeline.return_value.downloaded_video_path = None
            run_pipeline.return_value.subtitled_video_paths = {
                "en": Path("/tmp/en.fixed-sub.mp4")
            }
            exit_code = main(
                [
                    "input.mp4",
                    "--target-lang",
                    "en",
                    "--embed-subtitles",
                    "--subtitle-video-mode",
                    "hard",
                    "--subtitle-position",
                    "above-bottom",
                ]
            )

        self.assertEqual(exit_code, 0)
        options = run_pipeline.call_args.args[0]
        self.assertEqual(options.subtitle_video_mode, "hard")
        self.assertEqual(options.subtitle_position, "above-bottom")


if __name__ == "__main__":
    unittest.main()
