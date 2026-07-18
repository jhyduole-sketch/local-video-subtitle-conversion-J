from pathlib import Path
import sys
import threading
import time
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import subtitle_tool.web as web  # noqa: E402
from subtitle_tool.pipeline import PipelineResult  # noqa: E402
from subtitle_tool.errors import SubtitleToolError, actionable_error_message  # noqa: E402
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
    clear_finished_jobs,
    create_job_executor,
    create_subtitle_render_job,
    options_from_payload,
    request_job_cancel,
    resume_job,
    result_to_dict,
    safe_upload_filename,
    subtitle_document_payload,
    save_subtitle_payload,
)


class WebTests(unittest.TestCase):
    def test_web_source_selector_includes_screen_ocr(self):
        html = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "subtitle_tool"
            / "web_assets"
            / "index.html"
        ).read_text(encoding="utf-8")

        self.assertIn('<option value="screen-ocr">画面字幕 OCR</option>', html)

    def test_actionable_error_explains_empty_transcription_recovery(self):
        message = actionable_error_message(
            SubtitleToolError("Local Whisper returned no subtitle segments.")
        )

        self.assertIn("没有识别到有效语音", message)
        self.assertIn("关闭 VAD", message)
        self.assertIn("技术信息", message)

    def test_actionable_error_explains_provider_timeout(self):
        message = actionable_error_message(
            SubtitleToolError("OpenAI translation failed: Request timed out")
        )

        self.assertIn("在线模型请求超时", message)
        self.assertIn("稍后重试", message)

    def test_web_ui_has_confirmed_history_and_cache_clear_actions(self):
        assets = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "subtitle_tool"
            / "web_assets"
        )
        html = (assets / "index.html").read_text(encoding="utf-8")
        script = (assets / "app.js").read_text(encoding="utf-8")

        for element_id in (
            "clearHistoryButton",
            "clearAllCacheButton",
            "confirmationDialog",
        ):
            self.assertIn(f'id="{element_id}"', html)
        self.assertIn("openConfirmationDialog", script)
        self.assertIn('fetch("/api/jobs/clear"', script)

    def test_web_ui_only_offers_nllb_1_3b(self):
        assets = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "subtitle_tool"
            / "web_assets"
        )
        html = (assets / "index.html").read_text(encoding="utf-8")

        self.assertNotIn("NLLB 600M", html)
        self.assertIn("本地多语言 NLLB 1.3B", html)

    def test_web_ui_separates_language_catalog_and_advanced_settings(self):
        assets = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "subtitle_tool"
            / "web_assets"
        )
        html = (assets / "index.html").read_text(encoding="utf-8")
        script = (assets / "app.js").read_text(encoding="utf-8")
        catalog = assets / "language_catalog.js"

        self.assertTrue(catalog.exists())
        self.assertIn('id="advancedSettings"', html)
        self.assertIn("高级设置", html)
        self.assertLess(html.index("/language_catalog.js"), html.index("/app.js"))
        self.assertNotIn("const cloudLanguages", script)

    def test_clear_finished_jobs_keeps_active_memory_records(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            previous_store = web.JOB_STORE
            store = web.JobStore(Path(tmpdir) / "jobs.sqlite3")
            active = JobState(id="active-job", status="running")
            finished = JobState(id="finished-job", status="failed")
            for job in (active, finished):
                store.save(web._job_record(job))
            with JOB_LOCK:
                JOBS.update({job.id: job for job in (active, finished)})
            web.JOB_STORE = store
            try:
                result = clear_finished_jobs()
                with JOB_LOCK:
                    remaining = set(JOBS)
            finally:
                web.JOB_STORE = previous_store
                with JOB_LOCK:
                    JOBS.pop(active.id, None)
                    JOBS.pop(finished.id, None)

        self.assertEqual(result["deleted"], 1)
        self.assertEqual(result["retainedActive"], 1)
        self.assertIn(active.id, remaining)
        self.assertNotIn(finished.id, remaining)

    def test_web_ui_locks_submit_and_restores_active_job(self):
        script = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "subtitle_tool"
            / "web_assets"
            / "app.js"
        ).read_text(encoding="utf-8")

        self.assertIn("let submitInFlight = false;", script)
        self.assertIn("if (submitInFlight || runButton.disabled) return;", script)
        self.assertIn("adoptActiveJob(data.activeJob);", script)
        self.assertIn(
            'runButton.textContent = isRunning ? "任务进行中" : "开始任务";',
            script,
        )

    def test_active_job_returns_newest_inflight_job(self):
        older = JobState(id="older-active", status="running", created_at=10.0)
        newer = JobState(id="newer-active", status="queued", created_at=20.0)
        finished = JobState(id="finished", status="succeeded", created_at=30.0)
        with JOB_LOCK:
            JOBS.update({job.id: job for job in (older, newer, finished)})
        try:
            active_job = getattr(web, "active_job", lambda: None)
            self.assertIs(active_job(), newer)
        finally:
            with JOB_LOCK:
                for job in (older, newer, finished):
                    JOBS.pop(job.id, None)

    def test_create_pipeline_job_rejects_when_another_job_is_active(self):
        running = JobState(id="already-running", status="running")
        with JOB_LOCK:
            JOBS[running.id] = running
        create_pipeline_job = getattr(web, "create_pipeline_job", lambda *_: None)
        try:
            with self.assertRaises(SubtitleToolError):
                create_pipeline_job(
                    {"input": "video.mp4"},
                    options_from_payload({"input": "video.mp4"}),
                )
        finally:
            with JOB_LOCK:
                JOBS.pop(running.id, None)

    def test_jobs_payload_exposes_active_job_for_page_refresh(self):
        running = JobState(id="refresh-running", status="running")
        with JOB_LOCK:
            JOBS[running.id] = running
        jobs_payload = getattr(web, "jobs_payload", lambda: {"jobs": []})
        try:
            payload = jobs_payload()
        finally:
            with JOB_LOCK:
                JOBS.pop(running.id, None)

        self.assertEqual((payload.get("activeJob") or {}).get("id"), running.id)

    def test_subtitle_api_helpers_load_and_save_document(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir) / "output"
            path = out_dir / "task" / "subtitles.en.srt"
            path.parent.mkdir(parents=True)
            path.write_text(
                "1\n00:00:00,000 --> 00:00:01,000\nHello\n", encoding="utf-8"
            )

            loaded = subtitle_document_payload(str(out_dir), str(path))
            saved = save_subtitle_payload(
                {
                    "outDir": str(out_dir),
                    "path": str(path),
                    "segments": [
                        {
                            "start": "00:00:00,100",
                            "end": "00:00:01,200",
                            "text": "Edited",
                        }
                    ],
                }
            )

        self.assertEqual(len(loaded["segments"]), 1)
        self.assertEqual(saved["count"], 1)

    def test_create_subtitle_render_job_queues_linked_render(self):
        payload = {
            "outDir": "/tmp/output",
            "videoPath": "/tmp/output/task/video.mp4",
            "subtitlePath": "/tmp/output/task/subtitle.en.srt",
            "mode": "hard",
            "position": "above-bottom",
        }
        with patch("subtitle_tool.web.JOB_EXECUTOR.submit") as submit:
            job = create_subtitle_render_job(payload)
        try:
            self.assertEqual(job.status, "queued")
            self.assertEqual(job.payload["operation"], "render-edited-subtitles")
            submit.assert_called_once()
        finally:
            with JOB_LOCK:
                JOBS.pop(job.id, None)
    def test_cache_helpers_report_and_clear_selected_category(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir) / "output"
            cached = Path(tmpdir) / ".subtitle-tool-cache" / "audio" / "audio.mp3"
            cached.parent.mkdir(parents=True)
            cached.write_bytes(b"audio")

            summary = cache_summary(out_dir)
            cleared = clear_cache(out_dir, ["audio"])

        self.assertEqual(summary["categories"]["audio"]["files"], 1)
        self.assertEqual(summary["root"], str(Path(tmpdir) / ".subtitle-tool-cache"))
        self.assertEqual(cleared["cleared"], ["audio"])

    def test_cache_helper_clears_all_categories_without_touching_outputs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir) / "output"
            output_file = out_dir / "task" / "finished.mp4"
            output_file.parent.mkdir(parents=True)
            output_file.write_bytes(b"finished")
            cache = Path(tmpdir) / ".subtitle-tool-cache"
            for directory in web.AssetCache.CATEGORY_DIRS.values():
                path = cache / directory / "cached.dat"
                path.parent.mkdir(parents=True)
                path.write_bytes(b"cache")

            cleared = clear_cache(
                out_dir, list(web.AssetCache.CATEGORY_DIRS)
            )

            output_still_exists = output_file.exists()

        self.assertEqual(
            set(cleared["cleared"]), set(web.AssetCache.CATEGORY_DIRS)
        )
        self.assertEqual(cleared["totalFiles"], 0)
        self.assertTrue(output_still_exists)
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

    def test_resume_render_job_uses_render_worker(self):
        original = JobState(
            id="failed-render",
            status="failed",
            payload={
                "operation": "render-edited-subtitles",
                "outDir": "/tmp/output",
                "videoPath": "/tmp/output/video.mp4",
                "subtitlePath": "/tmp/output/subtitle.srt",
            },
        )
        with JOB_LOCK:
            JOBS[original.id] = original
        try:
            with patch("subtitle_tool.web.JOB_EXECUTOR.submit") as submit:
                resumed = resume_job(original.id)
            self.assertIsNotNone(resumed)
            self.assertIs(submit.call_args.args[0], __import__("subtitle_tool.web", fromlist=["_run_subtitle_render_job"])._run_subtitle_render_job)
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
        self.assertEqual(options.subtitle_video_mode, "hard")
        self.assertEqual(options.subtitle_position, "auto")
        self.assertTrue(options.whisper_use_gpu)
        self.assertTrue(options.whisper_use_vad)
        self.assertEqual(options.subtitle_encoding_profile, "auto")

    def test_options_from_payload_accepts_whisper_acceleration_settings(self):
        options = options_from_payload(
            {
                "input": "input.mp4",
                "whisperUseGpu": False,
                "whisperUseVad": False,
                "whisperVadModel": "models/custom-vad.bin",
            }
        )

        self.assertFalse(options.whisper_use_gpu)
        self.assertFalse(options.whisper_use_vad)
        self.assertEqual(options.whisper_vad_model.name, "custom-vad.bin")

    def test_options_from_payload_accepts_hard_subtitle_layout(self):
        options = options_from_payload(
            {
                "input": "input.mp4",
                "targetLangs": ["en"],
                "embedSubtitles": True,
                "subtitleVideoMode": "hard",
                "subtitlePosition": "above-bottom",
                "subtitleEncodingProfile": "quality",
            }
        )

        self.assertEqual(options.subtitle_video_mode, "hard")
        self.assertEqual(options.subtitle_position, "above-bottom")
        self.assertEqual(options.subtitle_encoding_profile, "quality")

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
            "subtitle_tool.health.ass_ffmpeg_binary",
            return_value="/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg",
        ):
            health = collect_health(Path.cwd())

        matching = [
            check for check in health["checks"] if check["name"] == "固定位置硬字幕"
        ]
        self.assertEqual(len(matching), 1)
        self.assertTrue(matching[0]["ok"])
        self.assertIn("ffmpeg-full", matching[0]["detail"])

    def test_collect_health_reports_videotoolbox_encoder(self):
        with patch("subtitle_tool.health.videotoolbox_available", return_value=True):
            health = collect_health(Path.cwd())

        matching = [
            check for check in health["checks"] if check["name"] == "Apple 硬件编码"
        ]
        self.assertEqual(len(matching), 1)
        self.assertTrue(matching[0]["ok"])

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

        with patch(
            "subtitle_tool.health.local_translation_model_statuses",
            return_value=statuses,
        ):
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
            "label": "NLLB 1.3B",
            "model": "facebook/nllb-200-distilled-1.3B",
            "installed": False,
            "downloadCommand": "python3 -c \"download nllb\"",
        }

        with patch(
            "subtitle_tool.health.nllb_model_status", return_value=status
        ) as model_status:
            health = collect_health(Path.cwd())

        matching = [
            check
            for check in health["checks"]
            if check["name"] == "本地多语言 NLLB 1.3B"
        ]
        self.assertEqual(len(matching), 1)
        self.assertFalse(matching[0]["ok"])
        self.assertTrue(matching[0]["optional"])
        self.assertIn("模型较大", matching[0]["detail"])
        model_status.assert_called_once_with(
            model_name="facebook/nllb-200-distilled-1.3B"
        )

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
