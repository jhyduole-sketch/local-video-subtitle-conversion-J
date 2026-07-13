from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import subtitle_tool.local_whisper as local_whisper  # noqa: E402
from subtitle_tool.local_whisper import transcribe_with_whisper_cpp  # noqa: E402


class LocalWhisperTests(unittest.TestCase):
    def setUp(self):
        local_whisper._gpu_failed = False

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
        command = run_process.call_args.args[0]
        self.assertEqual(command[command.index("-ml") + 1], "80")

    def test_transcription_uses_gpu_and_vad_when_available(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            audio_path = root / "audio.wav"
            model_path = root / "model.bin"
            vad_model_path = root / "vad.bin"
            audio_path.write_bytes(b"audio")
            model_path.write_bytes(b"model")
            vad_model_path.write_bytes(b"vad")
            logs = []

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
            ), patch("subtitle_tool.local_whisper.run_process", side_effect=fake_run) as run:
                transcribe_with_whisper_cpp(
                    audio_path,
                    "en",
                    model_path,
                    progress_callback=logs.append,
                    use_gpu=True,
                    use_vad=True,
                    vad_model_path=vad_model_path,
                )

        command = run.call_args.args[0]
        self.assertNotIn("-ng", command)
        self.assertIn("--vad", command)
        self.assertEqual(command[command.index("-vm") + 1], str(vad_model_path))
        self.assertTrue(any("Metal/GPU" in message for message in logs))
        self.assertTrue(any("VAD" in message for message in logs))

    def test_transcription_falls_back_to_cpu_and_keeps_vad(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            audio_path = root / "audio.wav"
            model_path = root / "model.bin"
            vad_model_path = root / "vad.bin"
            audio_path.write_bytes(b"audio")
            model_path.write_bytes(b"model")
            vad_model_path.write_bytes(b"vad")
            logs = []
            attempts = []

            def fake_run(command, cancel_check=None):
                attempts.append(command)
                if len(attempts) == 1:
                    return subprocess.CompletedProcess(command, 1, "", "Metal failed")
                output_base = Path(command[command.index("-of") + 1])
                output_base.with_suffix(".srt").write_text(
                    "1\n00:00:00,000 --> 00:00:01,000\nhello\n",
                    encoding="utf-8",
                )
                return subprocess.CompletedProcess(command, 0, "", "")

            with patch(
                "subtitle_tool.local_whisper.shutil.which",
                return_value="/usr/local/bin/whisper-cli",
            ), patch("subtitle_tool.local_whisper.run_process", side_effect=fake_run):
                segments = transcribe_with_whisper_cpp(
                    audio_path,
                    "en",
                    model_path,
                    progress_callback=logs.append,
                    use_gpu=True,
                    use_vad=True,
                    vad_model_path=vad_model_path,
                )

        self.assertEqual(segments[0].text, "hello")
        self.assertEqual(len(attempts), 2)
        self.assertNotIn("-ng", attempts[0])
        self.assertIn("--vad", attempts[0])
        self.assertIn("-ng", attempts[1])
        self.assertIn("--vad", attempts[1])
        self.assertTrue(any("CPU" in message for message in logs))

    def test_transcription_disables_vad_when_cpu_vad_retry_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            audio_path = root / "audio.wav"
            model_path = root / "model.bin"
            vad_model_path = root / "vad.bin"
            audio_path.write_bytes(b"audio")
            model_path.write_bytes(b"model")
            vad_model_path.write_bytes(b"vad")
            attempts = []

            def fake_run(command, cancel_check=None):
                attempts.append(command)
                if len(attempts) < 3:
                    return subprocess.CompletedProcess(command, 1, "", "failed")
                output_base = Path(command[command.index("-of") + 1])
                output_base.with_suffix(".srt").write_text(
                    "1\n00:00:00,000 --> 00:00:01,000\nhello\n",
                    encoding="utf-8",
                )
                return subprocess.CompletedProcess(command, 0, "", "")

            with patch(
                "subtitle_tool.local_whisper.shutil.which",
                return_value="/usr/local/bin/whisper-cli",
            ), patch("subtitle_tool.local_whisper.run_process", side_effect=fake_run):
                transcribe_with_whisper_cpp(
                    audio_path,
                    "en",
                    model_path,
                    use_gpu=True,
                    use_vad=True,
                    vad_model_path=vad_model_path,
                )

        self.assertEqual(len(attempts), 3)
        self.assertIn("-ng", attempts[1])
        self.assertIn("--vad", attempts[1])
        self.assertIn("-ng", attempts[2])
        self.assertNotIn("--vad", attempts[2])
