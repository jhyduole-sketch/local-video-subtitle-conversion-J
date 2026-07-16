from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from subtitle_tool.errors import DependencyError  # noqa: E402
from subtitle_tool.media import (  # noqa: E402
    EncodingProgress,
    ass_ffmpeg_binary,
    burn_subtitle_track,
    extract_audio,
    sample_video_edge_frames,
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
            "subtitle_tool.media._probe_duration_seconds", return_value=10.0
        ), patch(
            "subtitle_tool.media.run_process_streaming",
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
        self.assertGreater(run_process.call_args.kwargs["timeout_seconds"], 0)
        self.assertGreater(run_process.call_args.kwargs["inactivity_timeout_seconds"], 0)
        self.assertEqual(
            run_process.call_args.kwargs["operation_name"], "固定位置硬字幕烧录"
        )
        self.assertEqual(output.name, "result.mp4")

    def test_fast_hard_subtitle_reports_real_ffmpeg_progress(self):
        progress_updates = []

        def fake_stream(command, cancel_check=None, stdout_line_callback=None, **kwargs):
            for line in (
                "out_time_us=5000000",
                "speed=2.0x",
                "progress=continue",
            ):
                stdout_line_callback(line)
            return subprocess.CompletedProcess(command, 0, "", "")

        with tempfile.TemporaryDirectory() as tmpdir, patch(
            "subtitle_tool.media.ass_ffmpeg_binary",
            return_value="/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg",
        ), patch(
            "subtitle_tool.media._probe_duration_seconds", return_value=10.0
        ), patch(
            "subtitle_tool.media.run_process_streaming", side_effect=fake_stream
        ) as run:
            burn_subtitle_track(
                Path(tmpdir) / "video.mp4",
                Path(tmpdir) / "captions.ass",
                Path(tmpdir) / "result.mp4",
                encoding_profile="fast",
                progress_callback=progress_updates.append,
            )

        command = run.call_args.args[0]
        self.assertEqual(command[command.index("-c:v") + 1], "libx264")
        self.assertEqual(command[command.index("-preset") + 1], "veryfast")
        self.assertIn("-progress", command)
        self.assertIsInstance(progress_updates[-1], EncodingProgress)
        self.assertEqual(progress_updates[-1].percent, 50)
        self.assertEqual(progress_updates[-1].speed, 2.0)
        self.assertEqual(progress_updates[-1].eta_seconds, 2.5)

    def test_auto_hard_subtitle_uses_videotoolbox_and_falls_back_to_fast_cpu(self):
        commands = []
        statuses = []

        def fake_stream(command, cancel_check=None, stdout_line_callback=None, **kwargs):
            commands.append(command)
            return subprocess.CompletedProcess(
                command,
                1 if len(commands) == 1 else 0,
                "",
                "hardware failed" if len(commands) == 1 else "",
            )

        with tempfile.TemporaryDirectory() as tmpdir, patch(
            "subtitle_tool.media.ass_ffmpeg_binary",
            return_value="/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg",
        ), patch(
            "subtitle_tool.media._probe_duration_seconds", return_value=10.0
        ), patch(
            "subtitle_tool.media._ffmpeg_has_encoder", return_value=True
        ), patch(
            "subtitle_tool.media.run_process_streaming", side_effect=fake_stream
        ):
            burn_subtitle_track(
                Path(tmpdir) / "video.mp4",
                Path(tmpdir) / "captions.ass",
                Path(tmpdir) / "result.mp4",
                encoding_profile="auto",
                status_callback=statuses.append,
            )

        self.assertEqual(commands[0][commands[0].index("-c:v") + 1], "h264_videotoolbox")
        self.assertEqual(commands[1][commands[1].index("-c:v") + 1], "libx264")
        self.assertEqual(commands[1][commands[1].index("-preset") + 1], "veryfast")
        self.assertTrue(any("快速 CPU" in status for status in statuses))

    def test_ass_ffmpeg_binary_explains_how_to_install_missing_filter(self):
        with patch(
            "subtitle_tool.media._candidate_ffmpeg_binaries",
            return_value=["/usr/local/bin/ffmpeg"],
        ), patch("subtitle_tool.media._ffmpeg_has_filter", return_value=False):
            with self.assertRaises(DependencyError) as raised:
                ass_ffmpeg_binary()

        self.assertIn("brew install ffmpeg-full", str(raised.exception))

    def test_sample_video_edge_frames_uses_duration_and_cancellable_ffmpeg(self):
        cancel_check = lambda: False
        commands = []

        def fake_run(command, cancel_check=None):
            commands.append(command)
            if command[0] == "ffprobe":
                return subprocess.CompletedProcess(command, 0, "12.0\n", "")
            output_pattern = Path(command[-1])
            (output_pattern.parent / "frame-01.pgm").write_bytes(b"P5\n1 1\n255\n\0")
            return subprocess.CompletedProcess(command, 0, "", "")

        with tempfile.TemporaryDirectory() as tmpdir, patch(
            "subtitle_tool.media.ensure_ffmpeg"
        ), patch("subtitle_tool.media._run", side_effect=fake_run):
            frames = sample_video_edge_frames(
                Path(tmpdir) / "video.mp4",
                Path(tmpdir) / "frames",
                sample_count=6,
                cancel_check=cancel_check,
            )

        self.assertEqual(len(commands), 2)
        self.assertEqual(commands[0][0], "ffprobe")
        self.assertEqual(commands[1][0], "ffmpeg")
        self.assertIn("edgedetect", " ".join(commands[1]))
        self.assertEqual([path.name for path in frames], ["frame-01.pgm"])


if __name__ == "__main__":
    unittest.main()
