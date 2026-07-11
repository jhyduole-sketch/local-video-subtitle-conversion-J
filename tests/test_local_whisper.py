from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from subtitle_tool.local_whisper import transcribe_with_whisper_cpp  # noqa: E402


class LocalWhisperTests(unittest.TestCase):
    def test_transcription_forwards_cancel_check(self):
        cancel_check = lambda: False
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            audio_path = root / "audio.mp3"
            model_path = root / "model.bin"
            audio_path.write_bytes(b"audio")
            model_path.write_bytes(b"model")

            def fake_run(command, cancel_check=None):
                output_base = Path(command[command.index("-of") + 1])
                output_base.with_suffix(".srt").write_text(
                    "1\n00:00:00,000 --> 00:00:01,000\nhello\n",
                    encoding="utf-8",
                )
                return subprocess.CompletedProcess(command, 0, "", "")

            with patch(
                "subtitle_tool.local_whisper.shutil.which",
                return_value="/usr/local/bin/whisper-cli",
            ), patch(
                "subtitle_tool.local_whisper.run_process", side_effect=fake_run
            ) as run_process:
                segments = transcribe_with_whisper_cpp(
                    audio_path,
                    "en",
                    model_path,
                    cancel_check=cancel_check,
                )

        self.assertEqual(segments[0].text, "hello")
        self.assertIs(run_process.call_args.kwargs["cancel_check"], cancel_check)
