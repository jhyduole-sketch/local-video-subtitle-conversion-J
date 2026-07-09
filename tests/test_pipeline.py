from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from subtitle_tool.pipeline import PipelineOptions, run_pipeline  # noqa: E402
from subtitle_tool.srt import SubtitleSegment  # noqa: E402


class PipelineTests(unittest.TestCase):
    def test_generated_files_include_timestamp_suffix(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "input.mp4"
            input_path.write_bytes(b"video")

            with patch(
                "subtitle_tool.pipeline._load_source_segments",
                return_value=(
                    [SubtitleSegment(index=1, start_ms=0, end_ms=1000, text="hello")],
                    "audio-local-whisper",
                ),
            ), patch(
                "subtitle_tool.pipeline.translate_segments",
                return_value={1: "こんにちは"},
            ):
                result = run_pipeline(
                    PipelineOptions(
                        input_value=str(input_path),
                        target_langs=["ja"],
                        source_lang="en",
                        out_dir=Path(tmpdir),
                        source="audio",
                        output_format="srt",
                        translator="openai",
                    )
                )

        self.assertRegex(result.source_subtitle_path.name, r"input\.\d{15}\.source\.en\.srt")
        self.assertRegex(result.translated_paths["ja"].name, r"input\.\d{15}\.ja\.srt")
        self.assertEqual(result.source_subtitle_path.parent.name, "input")
        self.assertEqual(result.source_subtitle_path.parent, result.translated_paths["ja"].parent)


if __name__ == "__main__":
    unittest.main()
