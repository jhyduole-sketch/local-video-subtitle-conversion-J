import sys
from pathlib import Path
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from subtitle_tool.errors import MediaError  # noqa: E402
from subtitle_tool.preflight import (  # noqa: E402
    estimate_required_bytes,
    validate_processing_space,
)


class PreflightTests(unittest.TestCase):
    def test_estimate_scales_hard_subtitle_space_per_language(self):
        input_size = 100 * 1024 * 1024

        soft = estimate_required_bytes(input_size, True, "soft", 3)
        hard = estimate_required_bytes(input_size, True, "hard", 3)

        self.assertGreater(hard, soft)
        self.assertGreaterEqual(hard, input_size * 3)

    def test_rejects_empty_input(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video = root / "empty.mp4"
            video.touch()

            with self.assertRaisesRegex(MediaError, "为空"):
                validate_processing_space(video, root / "output", False, "soft", 1)

    def test_reports_required_and_available_space(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video = root / "video.mp4"
            video.write_bytes(b"video")

            with self.assertRaisesRegex(MediaError, "可用空间不足"):
                validate_processing_space(
                    video,
                    root / "output",
                    True,
                    "hard",
                    2,
                    available_bytes=1,
                )


if __name__ == "__main__":
    unittest.main()
