from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from subtitle_tool.web import (  # noqa: E402
    JOBS,
    JOB_LOCK,
    JobState,
    _format_log_line,
    _job_to_dict,
    collect_health,
    options_from_payload,
    request_job_cancel,
    safe_upload_filename,
)


class WebTests(unittest.TestCase):
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
