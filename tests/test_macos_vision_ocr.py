from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from subtitle_tool.macos_vision_ocr import MacVisionOcrEngine  # noqa: E402


class MacVisionOcrEngineTests(unittest.TestCase):
    def test_availability_is_optional_outside_macos(self):
        with tempfile.TemporaryDirectory() as tmpdir, patch(
            "subtitle_tool.macos_vision_ocr.sys.platform", "linux"
        ):
            availability = MacVisionOcrEngine(Path(tmpdir)).availability()

        self.assertFalse(availability.available)
        self.assertIn("macOS", availability.detail)

    def test_compiles_helper_once_and_reuses_cached_binary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_root = Path(tmpdir)
            engine = MacVisionOcrEngine(cache_root)

            def fake_run(command, **kwargs):
                output_path = Path(command[command.index("-o") + 1])
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(b"compiled")
                return subprocess.CompletedProcess(command, 0, "", "")

            with patch(
                "subtitle_tool.macos_vision_ocr.run_process", side_effect=fake_run
            ) as run_process:
                first = engine.ensure_helper()
                second = engine.ensure_helper()

        self.assertEqual(first, second)
        self.assertEqual(run_process.call_count, 1)
        command = run_process.call_args.args[0]
        self.assertIn("swiftc", command[0])
        self.assertIn("-O", command)

    def test_builds_fixed_interval_scaled_frame_command(self):
        engine = MacVisionOcrEngine(Path("/cache"), sample_interval_ms=500)

        command = engine.frame_extraction_command(
            Path("/video/input.mp4"), Path("/frames")
        )

        self.assertEqual(command[0], "ffmpeg")
        self.assertIn("fps=2,scale=720:-2", command)
        self.assertEqual(command[-1], "/frames/frame-%08d.jpg")

    def test_parses_helper_json_line_into_frame_result(self):
        engine = MacVisionOcrEngine(Path("/cache"), sample_interval_ms=500)

        result = engine.parse_helper_line(
            '{"frameIndex":3,"observations":[{"text":"料理で発散",'
            '"confidence":0.93,"x":0.2,"y":0.1,"width":0.6,"height":0.08}]}'
        )

        self.assertEqual(result.timestamp_ms, 1_000)
        self.assertEqual(result.observations[0].text, "料理で発散")
        self.assertAlmostEqual(result.observations[0].confidence, 0.93)

    def test_rejects_malformed_helper_output(self):
        engine = MacVisionOcrEngine(Path("/cache"))

        with self.assertRaisesRegex(ValueError, "Vision OCR"):
            engine.parse_helper_line("not json")


if __name__ == "__main__":
    unittest.main()
