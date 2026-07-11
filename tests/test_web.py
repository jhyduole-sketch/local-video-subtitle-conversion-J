from pathlib import Path
import sys
import threading
import time
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from subtitle_tool.pipeline import PipelineResult  # noqa: E402
from subtitle_tool.web import (  # noqa: E402
    JOBS,
    JOB_LOCK,
    JobState,
    _format_log_line,
    _job_to_dict,
    _update_job,
    collect_health,
    cache_summary,
    clear_cache,
    create_job_executor,
    options_from_payload,
    request_job_cancel,
    resume_job,
    result_to_dict,
    safe_upload_filename,
)


class WebTests(unittest.TestCase):
    def test_cache_helpers_report_and_clear_selected_category(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)
            cached = out_dir / ".subtitle-tool-cache" / "audio" / "audio.mp3"
            cached.parent.mkdir(parents=True)
            cached.write_bytes(b"audio")

            summary = cache_summary(out_dir)
            cleared = clear_cache(out_dir, ["audio"])

        self.assertEqual(summary["categories"]["audio"]["files"], 1)
        self.assertEqual(cleared["cleared"], ["audio"])
    def test_resume_job_creates_linked_queued_job(self):
        original = JobState(
            id="failed-job",
            status="failed",
            payload={"input": "video.mp4", "targetLangs": ["ja"]},
        )
        with JOB_LOCK:
            JOBS[original.id] = original
        try:
            with patch("subtitle_tool.web.JOB_EXECUTOR.submit") as submit:
                resumed = resume_job(original.id)
            self.assertIsNotNone(resumed)
            self.assertEqual(resumed.status, "queued")
            self.assertEqual(resumed.resumed_from, original.id)
            self.assertEqual(resumed.payload, original.payload)
            submit.assert_called_once()
        finally:
            with JOB_LOCK:
                JOBS.pop(original.id, None)
                if 'resumed' in locals() and resumed:
                    JOBS.pop(resumed.id, None)

    def test_job_executor_runs_only_one_job_at_a_time(self):
        executor = create_job_executor()
        first_started = threading.Event()
        release_first = threading.Event()
        second_started = threading.Event()

        def first_job():
            first_started.set()
            release_first.wait(timeout=2)

        def second_job():
            second_started.set()

        try:
            first_future = executor.submit(first_job)
            second_future = executor.submit(second_job)
            self.assertTrue(first_started.wait(timeout=1))
            time.sleep(0.05)
            self.assertFalse(second_started.is_set())
            release_first.set()
            first_future.result(timeout=1)
            second_future.result(timeout=1)
        finally:
            release_first.set()
            executor.shutdown(wait=True)

        self.assertTrue(second_started.is_set())

    def test_job_progress_never_moves_backward(self):
        job = JobState(id="monotonic-progress")
        with JOB_LOCK:
            JOBS[job.id] = job
        try:
            _update_job(job.id, progress=80, progress_message="翻译")
            _update_job(job.id, progress=20, progress_message="缓存")
            payload = _job_to_dict(job)
        finally:
            with JOB_LOCK:
                JOBS.pop(job.id, None)

        self.assertEqual(payload["progress"], 80)

    def test_result_payload_includes_translation_engines(self):
        result = PipelineResult(
            source_subtitle_path=Path("/tmp/source.srt"),
            translated_paths={"ja": Path("/tmp/ja.srt")},
            failed_languages={},
            source_kind="audio-local-whisper",
            translation_engines={"ja": "本地模型"},
        )

        payload = result_to_dict(result)

        self.assertEqual(payload["translationEngines"], {"ja": "本地模型"})

    def test_options_from_payload_uses_local_defaults(self):
        options = options_from_payload(
            {
                "input": "input.mp4",
                "sourceLang": "zh",
                "targetLangs": ["ja", ""],
                "embedSubtitles": True,
                "avoidSubtitleOverlap": True,
            }
        )

        self.assertEqual(options.input_value, "input.mp4")
        self.assertEqual(options.source_lang, "zh")
        self.assertEqual(options.target_langs, ["ja"])
        self.assertEqual(options.transcriber, "local-whisper")
        self.assertEqual(options.translator, "z-ai")
        self.assertTrue(options.embed_subtitles)
        self.assertTrue(options.avoid_subtitle_overlap)
        self.assertEqual(options.subtitle_video_mode, "soft")
        self.assertEqual(options.subtitle_position, "auto")

    def test_options_from_payload_accepts_hard_subtitle_layout(self):
        options = options_from_payload(
            {
                "input": "input.mp4",
                "targetLangs": ["en"],
                "embedSubtitles": True,
                "subtitleVideoMode": "hard",
                "subtitlePosition": "above-bottom",
            }
        )

        self.assertEqual(options.subtitle_video_mode, "hard")
        self.assertEqual(options.subtitle_position, "above-bottom")

    def test_options_from_payload_accepts_comma_targets(self):
        options = options_from_payload(
            {
                "input": "input.mp4",
                "targetLangs": "zh-CN, ja",
                "downloadOnly": True,
                "translator": "z-ai",
            }
        )

        self.assertEqual(options.target_langs, ["zh-CN", "ja"])
        self.assertEqual(options.translator, "z-ai")
        self.assertTrue(options.download_only)

    def test_collect_health_returns_checks(self):
        health = collect_health(Path.cwd())

        self.assertIn("checks", health)
        self.assertTrue(health["checks"])

    def test_collect_health_reports_fixed_subtitle_ffmpeg(self):
        with patch(
            "subtitle_tool.web.ass_ffmpeg_binary",
            return_value="/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg",
        ):
            health = collect_health(Path.cwd())

        matching = [
            check for check in health["checks"] if check["name"] == "固定位置硬字幕"
        ]
        self.assertEqual(len(matching), 1)
        self.assertTrue(matching[0]["ok"])
        self.assertIn("ffmpeg-full", matching[0]["detail"])

    def test_collect_health_includes_local_translation_models(self):
        statuses = [
            {
                "label": "中文 -> 英语",
                "source": "zh",
                "target": "en",
                "model": "Helsinki-NLP/opus-mt-zh-en",
                "installed": False,
                "downloadCommand": "python3 -c \"download\"",
            }
        ]

        with patch("subtitle_tool.web.local_translation_model_statuses", return_value=statuses):
            health = collect_health(Path.cwd())

        matching = [
            check
            for check in health["checks"]
            if check["name"] == "本地翻译 中文 -> 英语"
        ]
        self.assertEqual(len(matching), 1)
        self.assertFalse(matching[0]["ok"])
        self.assertTrue(matching[0]["optional"])
        self.assertIn("下载命令", matching[0]["detail"])

    def test_collect_health_includes_nllb_model(self):
        status = {
            "label": "NLLB 本地多语言",
            "model": "facebook/nllb-200-distilled-600M",
            "installed": False,
            "downloadCommand": "python3 -c \"download nllb\"",
        }

        with patch("subtitle_tool.web.nllb_model_status", return_value=status):
            health = collect_health(Path.cwd())

        matching = [
            check for check in health["checks"] if check["name"] == "本地多语言 NLLB"
        ]
        self.assertEqual(len(matching), 1)
        self.assertFalse(matching[0]["ok"])
        self.assertTrue(matching[0]["optional"])
        self.assertIn("模型较大", matching[0]["detail"])

    def test_log_line_includes_clock_and_elapsed_time(self):
        job = JobState(id="abc", created_at=100.0)

        with patch("subtitle_tool.web.time.time", return_value=165.0), patch(
            "subtitle_tool.web.datetime"
        ) as datetime:
            datetime.fromtimestamp.return_value.strftime.return_value = "15:23:08"
            line = _format_log_line(job, "正在抽取音频")

        self.assertEqual(line, "[15:23:08 +01:05] 正在抽取音频")

    def test_safe_upload_filename_uses_basename(self):
        self.assertEqual(safe_upload_filename("../movie.mp4"), "movie.mp4")
        self.assertEqual(safe_upload_filename(""), "uploaded-video.mp4")

    def test_request_job_cancel_marks_running_job(self):
        job = JobState(id="cancel-me", status="running")
        with JOB_LOCK:
            JOBS[job.id] = job
        try:
            self.assertTrue(request_job_cancel(job.id))
            payload = _job_to_dict(job)
        finally:
            with JOB_LOCK:
                JOBS.pop(job.id, None)

        self.assertEqual(job.status, "canceling")
        self.assertTrue(job.cancel_requested)
        self.assertTrue(job.cancel_event.is_set())
        self.assertTrue(payload["cancelRequested"])
        self.assertEqual(payload["progressMessage"], "正在停止")

    def test_request_job_cancel_ignores_finished_job(self):
        job = JobState(id="done-job", status="succeeded")
        with JOB_LOCK:
            JOBS[job.id] = job
        try:
            self.assertFalse(request_job_cancel(job.id))
        finally:
            with JOB_LOCK:
                JOBS.pop(job.id, None)

        self.assertEqual(job.status, "succeeded")
        self.assertFalse(job.cancel_requested)


if __name__ == "__main__":
    unittest.main()
