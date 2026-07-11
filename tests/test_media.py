from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from subtitle_tool.errors import DependencyError  # noqa: E402
from subtitle_tool.media import (  # noqa: E402
    ass_ffmpeg_binary,
    burn_subtitle_track,
    extract_audio,
)


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

    def test_burn_subtitle_track_uses_ass_filter_and_copies_audio(self):
        cancel_check = lambda: False
        with tempfile.TemporaryDirectory() as tmpdir, patch(
            "subtitle_tool.media.ass_ffmpeg_binary",
            return_value="/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg",
        ), patch(
            "subtitle_tool.media.run_process",
            return_value=subprocess.CompletedProcess([], 0, "", ""),
        ) as run_process:
            output = burn_subtitle_track(
                Path(tmpdir) / "video.mp4",
                Path(tmpdir) / "captions file.ass",
                Path(tmpdir) / "result.mp4",
                cancel_check=cancel_check,
            )

        command = run_process.call_args.args[0]
        self.assertEqual(command[0], "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg")
        self.assertIn("-vf", command)
        self.assertIn("ass=filename=", command[command.index("-vf") + 1])
        self.assertIn("-c:v", command)
        self.assertEqual(command[command.index("-c:v") + 1], "libx264")
        self.assertEqual(command[command.index("-c:a") + 1], "copy")
        self.assertIs(run_process.call_args.kwargs["cancel_check"], cancel_check)
        self.assertEqual(output.name, "result.mp4")

    def test_ass_ffmpeg_binary_explains_how_to_install_missing_filter(self):
        with patch(
            "subtitle_tool.media._candidate_ffmpeg_binaries",
            return_value=["/usr/local/bin/ffmpeg"],
        ), patch("subtitle_tool.media._ffmpeg_has_filter", return_value=False):
            with self.assertRaises(DependencyError) as raised:
                ass_ffmpeg_binary()

        self.assertIn("brew install ffmpeg-full", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
