from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from .env import load_dotenv
from .asset_cache import AssetCache
from .errors import CancellationError, SubtitleToolError, actionable_error_message
from .health import collect_health
from .job_store import JobStore, MissingJobError
from .log_sanitizer import sanitize_diagnostic_text, sanitize_result_diagnostics
from .runtime_paths import cache_root, state_database_path
from .user_settings import default_settings_path, load_user_settings, save_user_settings
from .user_settings import parse_boolean
from .media_preview import build_media_response, VIDEO_SUFFIXES
from .web_security import AccessPolicy, RequestError, content_length, is_loopback
from .upload_store import UploadStore
from .retained_inputs import retained_inputs, paths_in_record
from .onboarding import first_run_guidance
from .pipeline import (
    PipelineOptions,
    PipelineResult,
    render_edited_subtitle_video,
    run_pipeline,
)
from .subtitle_editor import (
    load_subtitle_document,
    safe_output_path,
    save_subtitle_document,
)


@dataclass
class JobState:
    id: str
    status: str = "queued"
    logs: list[str] = field(default_factory=list)
    result: dict[str, object] | None = None
    error: str | None = None
    progress: int = 0
    progress_message: str = "等待开始"
    cancel_requested: bool = False
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)
    payload: dict[str, object] = field(default_factory=dict)
    resumed_from: str | None = None
    persisted_log_count: int = field(default=0, repr=False)
    log_base: int = field(default=0, repr=False)
    persistence_ok: bool = field(default=False, repr=False)


class ActiveJobError(SubtitleToolError):
    def __init__(self, job: JobState):
        self.job = job
        super().__init__(f"已有任务正在运行: {job.id}")


MAX_JOB_LOG_CHARACTERS = 1024 * 1024
MAX_JOB_LOG_LINES = 1000
MAX_FINISHED_JOBS_IN_MEMORY = 20
JOBS: dict[str, JobState] = {}
JOB_LOCK = threading.Lock()
SERVICE_STOPPING = threading.Event()
JOB_STORE: JobStore | None = None
ACTIVE_JOB_STATUSES = frozenset({"queued", "running", "canceling"})
UPLOADS = UploadStore(Path.cwd() / ".subtitle-tool-state" / "uploads")


def default_access_policy() -> AccessPolicy:
    root = Path.cwd().resolve()
    return AccessPolicy(((root / "output").resolve(),), (root,))


def _active_job_unlocked() -> JobState | None:
    active = (job for job in JOBS.values() if job.status in ACTIVE_JOB_STATUSES)
    return max(active, key=lambda job: job.created_at, default=None)


def active_job() -> JobState | None:
    with JOB_LOCK:
        return _active_job_unlocked()


def _reserve_job(
    payload: dict[str, object],
    *,
    resumed_from: str | None = None,
    logs: list[str] | None = None,
) -> JobState:
    with JOB_LOCK:
        if SERVICE_STOPPING.is_set():
            raise SubtitleToolError("服务正在停止，请重启后再提交任务。")
        existing = _active_job_unlocked()
        if existing:
            raise ActiveJobError(existing)
        if JOB_STORE:
            finished = sorted((item for item in JOBS.values()
                               if item.status not in ACTIVE_JOB_STATUSES and item.persistence_ok),
                              key=lambda item: item.updated_at, reverse=True)
            for old in finished[MAX_FINISHED_JOBS_IN_MEMORY - 1:]:
                JOBS.pop(old.id, None)
        job = JobState(
            id=uuid.uuid4().hex[:12],
            payload=payload,
            resumed_from=resumed_from,
            logs=list(logs or []),
        )
        # 持久化成功后才发布任务，避免留下无人执行的占用。
        # Publish only after persistence succeeds to avoid a reservation without a worker.
        _persist_job(job)
        JOBS[job.id] = job
        return job


def create_pipeline_job(
    payload: dict[str, object], options: PipelineOptions
) -> JobState:
    input_path = Path(options.input_value)
    managed_upload = UPLOADS.owns(input_path)
    if managed_upload:
        UPLOADS.claim(input_path)
    try:
        job = _reserve_job(dict(payload))
        _submit_job(job, _run_job, options)
    except Exception:
        if managed_upload:
            # 任务冲突或提交失败时仅解除占用，保留上传供重试。
            # On a job conflict or submission failure, release the claim but keep the upload for retry.
            UPLOADS.release(input_path, delete=False)
        raise
    return job


def _submit_job(job: JobState, worker, argument) -> None:
    try:
        future = JOB_EXECUTOR.submit(worker, job.id, argument)
    except Exception as exc:
        _worker_failed(job.id, exc)
        raise
    # 捕获线程最终异常，保证没有执行者的任务不会继续占用队列。
    # Observe final worker errors so a job without a worker cannot keep the queue occupied.
    def completed(result):
        if result.cancelled():
            _worker_failed(job.id, CancellationError("Task cancelled before execution"))
            return
        error = result.exception()
        if error is not None:
            _worker_failed(job.id, error)
    future.add_done_callback(completed)


def _worker_failed(job_id: str, error: BaseException) -> None:
    with JOB_LOCK:
        job = JOBS.get(job_id)
        if job is None:
            return
        canceled = job.cancel_requested or isinstance(error, CancellationError)
        job.status = "canceled" if canceled else "failed"
        job.error = None if canceled else actionable_error_message(error)
        job.progress_message = "已停止" if canceled else "任务失败"
        job.logs.append(_format_log_line(job, job.error or "任务已停止"))
        job.updated_at = time.time()
        try:
            _persist_job(job)
        except Exception as persist_error:
            # 存储仍不可用时至少释放内存中的活动状态，并保留可见的诊断。
            # If storage remains unavailable, release the active state and retain a visible diagnostic.
            job.logs.append(_format_log_line(job, f"任务状态保存失败: {persist_error}"))


def shutdown_jobs() -> None:
    SERVICE_STOPPING.set()
    with JOB_LOCK:
        jobs = [job for job in JOBS.values() if job.status in ACTIVE_JOB_STATUSES]
        for job in jobs:
            job.cancel_requested = True
            job.cancel_event.set()
            job.status = "canceling"
            job.progress_message = "服务正在停止，等待当前步骤结束"
            job.updated_at = time.time()
            try:
                _persist_job(job)
            except Exception as exc:
                job.logs.append(_format_log_line(job, f"停止状态保存失败: {exc}"))
    # 先通知取消，再等待线程收尾；已入队任务也运行取消检查以释放上传占用。
    # Signal cancellation before joining; queued workers run their cancellation cleanup too.
    JOB_EXECUTOR.shutdown(wait=True)


def create_job_executor() -> ThreadPoolExecutor:
    return ThreadPoolExecutor(max_workers=1, thread_name_prefix="subtitle-job")


JOB_EXECUTOR = create_job_executor()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="subtitle-tool-web",
        description="Run a local web UI for the subtitle tool.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind.")
    parser.add_argument("--port", type=int, default=7860, help="Port to bind.")
    parser.add_argument("--allow-output-dir", action="append", default=[], help="Additional allowed output directory.")
    parser.add_argument("--allow-input-dir", action="append", default=[], help="Additional allowed local video directory.")
    parser.add_argument("--max-upload-mb", type=int, default=2048, help="Maximum upload request size in MiB.")
    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv(Path.cwd() / ".env")
    parser = build_parser()
    args = parser.parse_args(argv)
    SERVICE_STOPPING.clear()
    project_root = Path.cwd()
    token = os.environ.get("SUBTITLE_TOOL_WEB_TOKEN") or None
    if not is_loopback(args.host) and (not token or len(token) < 24):
        parser.error("局域网模式需要在环境变量 SUBTITLE_TOOL_WEB_TOKEN 中设置至少 24 字符的访问口令。")
    if args.max_upload_mb < 1:
        parser.error("--max-upload-mb 必须大于零。")
    settings = load_user_settings(_settings_path())
    output_roots = tuple(Path(value).expanduser().resolve() for value in ["output", settings["outputDir"], *args.allow_output_dir])
    policy = AccessPolicy(
        output_roots, tuple(Path(value).expanduser().resolve() for value in [str(project_root), *args.allow_input_dir, *map(str, output_roots)]),
        token=token, max_upload_bytes=args.max_upload_mb * 1024 ** 2,
    )
    state_path = state_database_path(project_root, project_root / "output")
    configure_job_store(state_path)
    UPLOADS.cleanup()
    server = ThreadingHTTPServer((args.host, args.port), SubtitleToolHandler)
    server.access_policy = policy
    print(f"Subtitle tool web UI: http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping subtitle tool web UI.")
    finally:
        try:
            shutdown_jobs()
        finally:
            server.server_close()
    return 0


def options_from_payload(payload: dict[str, object]) -> PipelineOptions:
    input_value = str(payload.get("input") or "").strip()
    if not input_value:
        raise SubtitleToolError("Input video path or URL is required.")

    target_langs = _coerce_target_langs(payload.get("targetLangs"))
    out_dir = Path(str(payload.get("outDir") or "output")).expanduser().resolve()
    whisper_model_value = str(payload.get("whisperModel") or "").strip()
    whisper_vad_model_value = str(payload.get("whisperVadModel") or "").strip()
    source_lang = str(payload.get("sourceLang") or "").strip() or None
    embed_subtitles = parse_boolean(payload.get("embedSubtitles", False), "embedSubtitles")
    avoid_subtitle_overlap = parse_boolean(payload.get("avoidSubtitleOverlap", False), "avoidSubtitleOverlap")
    subtitle_video_mode = str(payload.get("subtitleVideoMode") or "soft")
    if embed_subtitles and avoid_subtitle_overlap:
        subtitle_video_mode = "hard"

    return PipelineOptions(
        input_value=input_value,
        target_langs=target_langs,
        source_lang=source_lang,
        out_dir=out_dir,
        source=str(payload.get("source") or "auto"),
        output_format="srt",
        force_regenerate=parse_boolean(payload.get("forceRegenerate", False), "forceRegenerate"),
        force_download=parse_boolean(payload.get("forceDownload", False), "forceDownload"),
        download_only=parse_boolean(payload.get("downloadOnly", False), "downloadOnly"),
        transcriber=str(payload.get("transcriber") or "local-whisper"),
        whisper_model=Path(whisper_model_value).expanduser().resolve()
        if whisper_model_value
        else None,
        whisper_use_gpu=parse_boolean(payload.get("whisperUseGpu", True), "whisperUseGpu"),
        whisper_use_vad=parse_boolean(payload.get("whisperUseVad", True), "whisperUseVad"),
        whisper_vad_model=Path(whisper_vad_model_value).expanduser().resolve()
        if whisper_vad_model_value
        else None,
        translator=str(payload.get("translator") or "z-ai"),
        embed_subtitles=embed_subtitles,
        avoid_subtitle_overlap=avoid_subtitle_overlap,
        subtitle_video_mode=subtitle_video_mode,
        subtitle_position=str(payload.get("subtitlePosition") or "auto"),
        subtitle_encoding_profile=str(
            payload.get("subtitleEncodingProfile") or "auto"
        ),
    )


def result_to_dict(result: PipelineResult) -> dict[str, object]:
    return {
        "sourceSubtitlePath": _path_or_none(result.source_subtitle_path),
        "translatedPaths": {
            language: str(path) for language, path in result.translated_paths.items()
        },
        "failedLanguages": result.failed_languages,
        "translationEngines": result.translation_engines or {},
        "sourceKind": result.source_kind,
        "downloadedVideoPath": _path_or_none(result.downloaded_video_path),
        "subtitledVideoPaths": {
            language: str(path)
            for language, path in (result.subtitled_video_paths or {}).items()
        },
        "inputVideoPath": _path_or_none(result.input_video_path),
        "stageDurations": result.stage_durations or {},
        "totalDurationSeconds": result.total_duration_seconds,
        "multilingualSubtitledVideoPath": _path_or_none(
            result.multilingual_subtitled_video_path
        ),
        "processingEstimateSeconds": result.processing_estimate_seconds,
        "processingEstimateFactors": result.processing_estimate_factors or [],
        "processingEstimateLowerSeconds": result.processing_estimate_lower_seconds,
        "processingEstimateUpperSeconds": result.processing_estimate_upper_seconds,
        "processingEstimateHistorySamples": result.processing_estimate_history_samples,
        "sourceQuality": result.source_quality or {},
        "translationAttempts": result.translation_attempts or {},
    }


def subtitle_document_payload(out_dir_value: str, path_value: str) -> dict[str, object]:
    return load_subtitle_document(
        Path(out_dir_value or "output"), Path(path_value)
    )


def save_subtitle_payload(payload: dict[str, object]) -> dict[str, object]:
    segments = payload.get("segments")
    if not isinstance(segments, list):
        raise SubtitleToolError("字幕内容格式无效。")
    return save_subtitle_document(
        Path(str(payload.get("outDir") or "output")),
        Path(str(payload.get("path") or "")),
        segments,
    )


def create_subtitle_render_job(payload: dict[str, object]) -> JobState:
    render_payload = dict(payload)
    render_payload["operation"] = "render-edited-subtitles"
    job = _reserve_job(render_payload)
    _submit_job(job, _run_subtitle_render_job, render_payload)
    return job



def _run_subtitle_render_job(job_id: str, payload: dict[str, object]) -> None:
    try:
        _update_job(job_id, status="running", log="字幕视频重新生成任务已启动", progress=5)
        out_dir = Path(str(payload.get("outDir") or "output"))
        video_path = safe_output_path(
            out_dir, Path(str(payload.get("videoPath") or "")), ".mp4"
        )
        subtitle_path = safe_output_path(
            out_dir, Path(str(payload.get("subtitlePath") or "")), ".srt"
        )
        mode = str(payload.get("mode") or "hard")
        position = str(payload.get("position") or "above-bottom")
        encoding_profile = str(payload.get("encodingProfile") or "auto")
        suffix = "fixed-sub" if mode == "hard" else "default-sub"
        output_path = subtitle_path.with_name(
            f"{subtitle_path.stem}.edited.{suffix}.mp4"
        )
        _update_job(job_id, log=f"读取已编辑字幕: {subtitle_path.name}", progress=20)
        result_path = render_edited_subtitle_video(
            video_path,
            subtitle_path,
            output_path,
            mode,
            position,
            JOBS[job_id].cancel_event.is_set,
            encoding_profile=encoding_profile,
            progress_callback=lambda progress: _update_job(
                job_id,
                log=(
                    f"烧录硬字幕: {progress.percent}% · 已处理 "
                    f"{_web_duration(progress.processed_seconds)}/"
                    f"{_web_duration(progress.duration_seconds)} · 速度 "
                    f"{progress.speed:.2f}x · 预计剩余 "
                    f"{_web_duration(progress.eta_seconds)}"
                    if progress.speed and progress.eta_seconds is not None
                    else f"烧录硬字幕: {progress.percent}% · 正在计算剩余时间"
                ),
                progress=min(99, 20 + round(progress.percent * 79 / 100)),
            ),
            status_callback=lambda message: _update_job(
                job_id, log=message, progress=21
            ),
        )
    except CancellationError:
        _update_job(job_id, status="canceled", log="任务已停止", progress_message="已停止")
        return
    except Exception as exc:
        message = actionable_error_message(exc)
        _update_job(
            job_id,
            status="failed",
            error=message,
            log=f"重新生成失败: {message}",
            progress_message="任务失败",
        )
        return
    _update_job(
        job_id,
        status="succeeded",
        result={
            "sourceSubtitlePath": str(subtitle_path),
            "translatedPaths": {},
            "failedLanguages": {},
            "translationEngines": {},
            "sourceKind": "edited",
            "downloadedVideoPath": None,
            "inputVideoPath": str(video_path),
            "subtitledVideoPaths": {"edited": str(result_path)},
        },
        log=f"编辑后字幕视频已输出: {result_path.name}",
        progress=100,
        progress_message="任务完成",
    )


def _web_duration(seconds: float | None) -> str:
    total = max(0, round(seconds or 0))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _run_job(job_id: str, options: PipelineOptions) -> None:
    uploaded_input = Path(options.input_value)
    input_retained = False
    try:
        _update_job(job_id, status="running", log="任务已启动", progress=1)
        if UPLOADS.owns(uploaded_input):
            # 先保留文件并持久化新路径，再允许清理原上传；失败后仍可重试。
            # Retain the file and persist its new path before deleting the upload so failures remain retryable.
            retained = UPLOADS.retain(uploaded_input, options.out_dir / ".inputs" / job_id, release_source=False)
            options = replace(options, input_value=str(retained))
            with JOB_LOCK:
                JOBS[job_id].payload["input"] = str(retained)
                _persist_job(JOBS[job_id])
            input_retained = True
        options = replace(
            options,
            cancel_check=JOBS[job_id].cancel_event.is_set,
            progress_callback=lambda message, percent: _update_job(
                job_id,
                log=message,
                progress=percent,
                progress_message=message,
            ),
        )
        _update_job(job_id, log=f"输入: {options.input_value}")
        if options.download_only:
            _update_job(job_id, log="只下载视频，不生成字幕")
        elif options.target_langs:
            _update_job(job_id, log=f"目标语言: {', '.join(options.target_langs)}")
        else:
            _update_job(job_id, log="未选择目标语言，将只输出源字幕")
        result = run_pipeline(options)
    except CancellationError:
        _update_job(
            job_id,
            status="canceled",
            log="任务已停止",
            progress_message="已停止",
        )
        return
    except Exception as exc:
        message = actionable_error_message(exc)
        _update_job(
            job_id,
            status="failed",
            error=message,
            log=f"失败: {message}",
            progress_message="任务失败",
        )
        return
    finally:
        UPLOADS.release(uploaded_input, delete=input_retained)
    _update_job(
        job_id,
        status="succeeded",
        result=result_to_dict(result),
        log="任务完成",
        progress=100,
        progress_message="任务完成",
    )


def _update_job(
    job_id: str,
    status: str | None = None,
    log: str | None = None,
    result: dict[str, object] | None = None,
    error: str | None = None,
    progress: int | None = None,
    progress_message: str | None = None,
) -> None:
    with JOB_LOCK:
        job = JOBS[job_id]
        if job.cancel_requested and status != "canceled":
            if status in {"succeeded", "failed"}:
                # 终态与取消在同一锁内裁决，完成瞬间的取消也必须落入终态。
                # Resolve completion and cancellation under one lock so late cancellation is terminal.
                status, log, progress_message = "canceled", "任务已停止", "已停止"
                result, error, progress = None, None, None
            else:
                raise CancellationError("Task was cancelled by user.")
        if status:
            job.status = status
        if log:
            job.logs.append(_format_log_line(job, log))
        if result is not None:
            job.result = result
        if error is not None:
            job.error = error
        if progress is not None:
            job.progress = max(job.progress, max(0, min(100, progress)))
        if progress_message is not None:
            job.progress_message = progress_message
        job.updated_at = time.time()
        _persist_job(job)


def request_job_cancel(job_id: str) -> bool:
    with JOB_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return False
        if job.status not in {"queued", "running", "canceling"}:
            return False
        if not job.cancel_requested:
            job.cancel_requested = True
            job.cancel_event.set()
            job.status = "canceling"
            job.progress_message = "正在停止"
            job.logs.append(_format_log_line(job, "收到停止请求，当前步骤结束后停止"))
            job.updated_at = time.time()
            _persist_job(job)
        return True


def _job_to_dict(job: JobState | None, *, include_logs: bool = True) -> dict[str, object] | None:
    if not job:
        return None
    return {
        "id": job.id,
        "status": job.status,
        "logs": [sanitize_diagnostic_text(item, Path.home()) for item in job.logs] if include_logs else [],
        "logsIncluded": include_logs,
        "progress": job.progress,
        "progressMessage": sanitize_diagnostic_text(job.progress_message, Path.home()),
        "cancelRequested": job.cancel_requested,
        "result": sanitize_result_diagnostics(job.result),
        "error": sanitize_diagnostic_text(job.error, Path.home()) if job.error else None,
        "createdAt": job.created_at,
        "updatedAt": job.updated_at,
        "resumedFrom": job.resumed_from,
        "elapsedSeconds": max(0, round(job.updated_at - job.created_at)),
    }


def configure_job_store(path: Path) -> JobStore:
    global JOB_STORE
    store = JobStore(path)
    store.mark_inflight_interrupted()
    with JOB_LOCK:
        JOBS.clear()
    JOB_STORE = store
    return store


def _find_job_unlocked(job_id: str) -> JobState | None:
    job = JOBS.get(job_id)
    if job is None and JOB_STORE:
        record = JOB_STORE.get(job_id, include_logs=False)
        job = _job_from_record(record) if record else None
    return job


def job_payload(job_id: str, *, log_offset: int = 0, log_limit: int | None = None) -> dict[str, object] | None:
    with JOB_LOCK:
        job = _find_job_unlocked(job_id)
        if job is None:
            return None
        payload = _job_to_dict(job, include_logs=False)
        durable_available = JOB_STORE and (job_id not in JOBS or job.persistence_ok)
        if durable_available and job_id in JOBS and JOB_STORE.get(job_id, include_logs=False) is None:
            # 已完成任务不会再次保存；数据库丢失时仍展示保留窗口。
            # Completed jobs never save again; retain their memory window if the database disappears.
            durable_available = False
            job.persistence_ok = False
        if durable_available:
            if log_limit is None:
                record = JOB_STORE.get(job_id)
                all_logs = record["logs"] if record else []
                total = len(all_logs)
                lines = all_logs[log_offset:]
            else:
                lines, total = JOB_STORE.read_logs(job_id, start=log_offset, limit=log_limit)
            start = min(log_offset, total)
            truncated = False
        else:
            total = job.log_base + len(job.logs)
            start = max(job.log_base, min(log_offset, total))
            local_start = start - job.log_base
            lines = job.logs[local_start:] if log_limit is None else job.logs[local_start:local_start + log_limit]
            truncated = log_offset < job.log_base
        payload.update(logs=[sanitize_diagnostic_text(line, Path.home()) for line in lines],
                       logsIncluded=True, logOffset=start, logTruncated=truncated, nextLogOffset=start + len(lines),
                       logTotal=total, hasMoreLogs=start + len(lines) < total)
        return payload


def list_job_payloads(limit: int = 50) -> list[dict[str, object]]:
    return jobs_payload(limit)["jobs"]


def jobs_payload(limit: int = 50, offset: int = 0) -> dict[str, object]:
    with JOB_LOCK:
        if JOB_STORE:
            records = JOB_STORE.list(limit=limit, offset=offset, include_logs=False)
            jobs = [JOBS.get(str(record["id"])) or _job_from_record(record) for record in records]
            total = JOB_STORE.count()
        else:
            ordered = sorted(JOBS.values(), key=lambda item: (item.created_at, item.id), reverse=True)
            jobs = ordered[offset:offset + limit]
            total = len(ordered)
        return {
            "jobs": [_job_to_dict(job, include_logs=False) for job in jobs],
            "activeJob": _job_to_dict(_active_job_unlocked(), include_logs=False),
            "offset": offset, "limit": limit, "total": total,
            "hasMore": offset + len(jobs) < total,
        }


def _input_references_unlocked() -> set[Path]:
    references: set[Path] = set()
    if JOB_STORE:
        offset = 0
        while True:
            records = JOB_STORE.list(limit=100, offset=offset, include_logs=False)
            for record in records:
                references.update(paths_in_record(record.get("payload")))
                references.update(paths_in_record(record.get("result")))
            if len(records) < 100:
                break
            offset += len(records)
    for job in JOBS.values():
        references.update(paths_in_record(job.payload))
        references.update(paths_in_record(job.result))
    return references


def cache_summary(out_dir: Path) -> dict[str, object]:
    result = AssetCache(cache_root(out_dir)).summary()
    with JOB_LOCK:
        result["retainedInputs"] = retained_inputs(out_dir, _input_references_unlocked())
    return result


def clear_retained_inputs(out_dir: Path) -> dict[str, object]:
    with JOB_LOCK:
        if _active_job_unlocked():
            raise RequestError("任务正在运行，请在任务结束后清理原视频。", 409)
        result = retained_inputs(out_dir, _input_references_unlocked(), clear=True)
    return {**cache_summary(out_dir), "removedFiles": result["removedFiles"], "removedBytes": result["removedBytes"]}


def _settings_path() -> Path:
    return default_settings_path(Path.cwd())


def _first_run_guidance() -> dict[str, object]:
    return first_run_guidance(collect_health(), _settings_path())


def clear_cache(out_dir: Path, categories: list[str]) -> dict[str, object]:
    with JOB_LOCK:
        if _active_job_unlocked():
            raise RequestError("任务正在使用缓存，请在任务结束后清理。", 409)
        result = AssetCache(cache_root(out_dir)).clear(categories)
        result["retainedInputs"] = retained_inputs(out_dir, _input_references_unlocked())
        return result


def clear_finished_jobs() -> dict[str, int]:
    with JOB_LOCK:
        finished_ids = [
            job_id
            for job_id, job in JOBS.items()
            if job.status not in ACTIVE_JOB_STATUSES
        ]
        retained_active = len(JOBS) - len(finished_ids)
        deleted = JOB_STORE.clear_finished() if JOB_STORE else len(finished_ids)
        for job_id in finished_ids:
            JOBS.pop(job_id, None)
    return {"deleted": deleted, "retainedActive": retained_active}


def resume_job(job_id: str) -> JobState | None:
    with JOB_LOCK:
        original = _find_job_unlocked(job_id)
        if not original or original.status not in {"failed", "canceled", "interrupted"}:
            return None
        payload = dict(original.payload)
    is_render_job = payload.get("operation") == "render-edited-subtitles"
    if not is_render_job:
        try:
            options = options_from_payload(payload)
        except Exception:
            return None
    resumed = _reserve_job(
        payload,
        resumed_from=original.id,
        logs=[f"继续任务: {original.id}"],
    )
    if is_render_job:
        _submit_job(resumed, _run_subtitle_render_job, payload)
    else:
        _submit_job(resumed, _run_job, options)
    return resumed


def _persist_job(job: JobState) -> None:
    job.persistence_ok = False
    if JOB_STORE:
        try:
            JOB_STORE.save(_job_record(job, log_start=job.persisted_log_count), log_start=job.persisted_log_count)
        except MissingJobError:
            # 数据库被外部删除后只能恢复内存窗口，明确记录较早日志已丢失。
            # After external database deletion only the memory window can be recovered; disclose the lost prefix.
            if job.log_base:
                job.logs.insert(0, "日志存储已重建，较早日志已丢失；以下为内存保留日志。")
            job.log_base = 0
            JOB_STORE.save(_job_record(job), log_start=0)
        job.persisted_log_count = job.log_base + len(job.logs)
        job.persistence_ok = True
    # 成功落盘后才淘汰旧行，绝对游标不随内存窗口移动。
    # Evict old lines only after successful persistence; absolute cursors do not move with the window.
    excess = max(0, len(job.logs) - MAX_JOB_LOG_LINES)
    if excess:
        del job.logs[:excess]
        job.log_base += excess
    if job.logs:
        if len(job.logs[-1]) > MAX_JOB_LOG_CHARACTERS:
            marker = "[单条日志过长，内存仅保留末尾；完整日志见下载] "
            job.logs[-1] = marker + job.logs[-1][-(MAX_JOB_LOG_CHARACTERS - len(marker)):]
        characters = sum(map(len, job.logs))
        remove = 0
        while characters > MAX_JOB_LOG_CHARACTERS and remove < len(job.logs) - 1:
            characters -= len(job.logs[remove])
            remove += 1
        if remove:
            del job.logs[:remove]
            job.log_base += remove


def _job_record(job: JobState, *, log_start: int = 0) -> dict[str, object]:
    return {
        "id": job.id,
        "status": job.status,
        "logs": job.logs[max(0, log_start - job.log_base):],
        "result": job.result,
        "error": job.error,
        "progress": job.progress,
        "progress_message": job.progress_message,
        "cancel_requested": job.cancel_requested,
        "payload": job.payload,
        "resumed_from": job.resumed_from,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }


def _job_from_record(record: dict[str, object]) -> JobState:
    return JobState(
        id=str(record["id"]),
        status=str(record["status"]),
        logs=list(record.get("logs") or []),
        result=record.get("result") if isinstance(record.get("result"), dict) else None,
        error=str(record["error"]) if record.get("error") is not None else None,
        progress=int(record.get("progress") or 0),
        progress_message=str(record.get("progress_message") or "等待开始"),
        cancel_requested=bool(record.get("cancel_requested")),
        created_at=float(record.get("created_at") or time.time()),
        updated_at=float(record.get("updated_at") or time.time()),
        payload=dict(record.get("payload") or {}),
        resumed_from=(
            str(record["resumed_from"])
            if record.get("resumed_from") is not None
            else None
        ),
    )


def _coerce_target_langs(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [
        item.strip()
        for item in str(value).replace("\n", ",").split(",")
        if item.strip()
    ]


def _path_or_none(path: Path | None) -> str | None:
    return str(path) if path else None


def safe_upload_filename(filename: str) -> str:
    name = Path(filename).name.strip()
    return name or "uploaded-video.mp4"


def _format_log_line(job: JobState, message: str) -> str:
    now = time.time()
    clock = datetime.fromtimestamp(now).strftime("%H:%M:%S")
    elapsed = _format_elapsed(now - job.created_at)
    return f"[{clock} +{elapsed}] {message}"


def _format_elapsed(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


from . import web_http
# 绑定当前服务实例，兼容导入与 python -m 启动共用同一任务状态。
# Bind the active service instance so imports and python -m use the same job state.
web_http.service = sys.modules[__name__]
SubtitleToolHandler = web_http.SubtitleToolHandler


if __name__ == "__main__":
    raise SystemExit(main())
