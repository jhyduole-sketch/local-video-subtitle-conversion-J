from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from subtitle_tool.media import extract_audio  # noqa: E402


class MediaTests(unittest.TestCase):
    def test_extract_audio_forwards_cancel_check(self):
        cancel_check = lambda: False
        with tempfile.TemporaryDirectory() as tmpdir, patch(
            "subtitle_tool.media.ensure_ffmpeg"
        ), patch(
            "subtitle_tool.media.run_process",
            return_value=subprocess.CompletedProcess([], 0, "", ""),
        ) as run_process:
            extract_audio(
                Path(tmpdir) / "video.mp4",
                Path(tmpdir) / "audio.mp3",
                cancel_check=cancel_check,
            )

        self.assertIs(run_process.call_args.kwargs["cancel_check"], cancel_check)


if __name__ == "__main__":
    unittest.main()
