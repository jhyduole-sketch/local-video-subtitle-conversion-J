from __future__ import annotations

import argparse
import cgi
import json
import mimetypes
import os
import shutil
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import util
from importlib import resources
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from .env import load_dotenv
from .asset_cache import AssetCache
from .errors import CancellationError, SubtitleToolError
from .local_translate import (
    NLLB_MODEL_NAME,
    NLLB_QUALITY_MODEL_NAME,
    local_translation_model_statuses,
    nllb_model_status,
)
from .job_store import JobStore
from .local_whisper import DEFAULT_VAD_MODEL_PATH
from .runtime_paths import cache_root, state_database_path
from .media import ass_ffmpeg_binary, videotoolbox_available
from .media_preview import build_media_response
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


class ActiveJobError(SubtitleToolError):
    def __init__(self, job: JobState):
        self.job = job
        super().__init__(f"已有任务正在运行: {job.id}")


JOBS: dict[str, JobState] = {}
JOB_LOCK = threading.Lock()
JOB_STORE: JobStore | None = None
ACTIVE_JOB_STATUSES = frozenset({"queued", "running", "canceling"})


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
        existing = _active_job_unlocked()
        if existing:
            raise ActiveJobError(existing)
        job = JobState(
            id=uuid.uuid4().hex[:12],
            payload=payload,
            resumed_from=resumed_from,
            logs=list(logs or []),
        )
        JOBS[job.id] = job
        _persist_job(job)
        return job


def create_pipeline_job(
    payload: dict[str, object], options: PipelineOptions
) -> JobState:
    job = _reserve_job(dict(payload))
    JOB_EXECUTOR.submit(_run_job, job.id, options)
    return job


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
    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv(Path.cwd() / ".env")
    args = build_parser().parse_args(argv)
    project_root = Path.cwd()
    state_path = state_database_path(project_root, project_root / "output")
    configure_job_store(state_path)
    server = ThreadingHTTPServer((args.host, args.port), SubtitleToolHandler)
    print(f"Subtitle tool web UI: http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping subtitle tool web UI.")
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
    embed_subtitles = bool(payload.get("embedSubtitles"))
    avoid_subtitle_overlap = bool(payload.get("avoidSubtitleOverlap"))
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
        force_download=bool(payload.get("forceDownload")),
        download_only=bool(payload.get("downloadOnly")),
        transcriber=str(payload.get("transcriber") or "local-whisper"),
        whisper_model=Path(whisper_model_value).expanduser().resolve()
        if whisper_model_value
        else None,
        whisper_use_gpu=bool(payload.get("whisperUseGpu", True)),
        whisper_use_vad=bool(payload.get("whisperUseVad", True)),
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


def collect_health(project_root: Path | None = None) -> dict[str, object]:
    root = project_root or Path.cwd()
    checks = [
        _tool_check("ffmpeg"),
        _tool_check("ffprobe"),
        _ass_ffmpeg_check(),
        _videotoolbox_check(),
        _tool_check("yt-dlp"),
        _tool_check("whisper-cli"),
        _whisper_models_check(root),
        _whisper_vad_model_check(root),
        _python_module_check("openai"),
        _python_module_check("transformers"),
        _python_module_check("torch"),
        {
            "name": "ZAI_API_KEY",
            "ok": bool(os.environ.get("ZAI_API_KEY")),
            "optional": True,
            "detail": "已配置" if os.environ.get("ZAI_API_KEY") else "未配置",
        },
    ]
    checks.extend(_local_translation_model_checks())
    checks.append(
        _nllb_model_check(
            NLLB_MODEL_NAME,
            "本地多语言 NLLB",
        )
    )
    checks.append(
        _nllb_model_check(
            NLLB_QUALITY_MODEL_NAME,
            "本地多语言 NLLB 1.3B（质量）",
        )
    )
    return {
        "checks": checks,
        "ok": all(check["ok"] for check in checks if not check.get("optional")),
    }


def _ass_ffmpeg_check() -> dict[str, object]:
    try:
        binary = ass_ffmpeg_binary()
    except SubtitleToolError:
        return {
            "name": "固定位置硬字幕",
            "ok": False,
            "optional": True,
            "detail": "未安装；运行 brew install ffmpeg-full",
        }
    return {
        "name": "固定位置硬字幕",
        "ok": True,
        "optional": True,
        "detail": binary,
    }


def _videotoolbox_check() -> dict[str, object]:
    available = videotoolbox_available()
    return {
        "name": "Apple 硬件编码",
        "ok": available,
        "optional": True,
        "detail": "VideoToolbox 可用" if available else "不可用；自动模式将使用快速 CPU",
    }


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
    JOB_EXECUTOR.submit(_run_subtitle_render_job, job.id, render_payload)
    return job


class SubtitleToolHandler(BaseHTTPRequestHandler):
    server_version = "SubtitleToolWeb/0.1"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._serve_asset("index.html")
            return
        if parsed.path == "/api/health":
            self._send_json(collect_health())
            return
        if parsed.path == "/api/jobs":
            self._send_json(jobs_payload())
            return
        if parsed.path == "/api/cache":
            query = parse_qs(parsed.query)
            out_dir = Path(query.get("outDir", ["output"])[0]).expanduser().resolve()
            self._send_json(cache_summary(out_dir))
            return
        if parsed.path == "/api/subtitles":
            query = parse_qs(parsed.query)
            try:
                payload = subtitle_document_payload(
                    query.get("outDir", ["output"])[0],
                    query.get("path", [""])[0],
                )
                self._send_json(payload)
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=400)
            return
        if parsed.path == "/api/media":
            self._serve_media(parsed)
            return
        if parsed.path.startswith("/api/jobs/"):
            self._send_job(unquote(parsed.path.removeprefix("/api/jobs/")))
            return
        if parsed.path in {"/app.js", "/styles.css"}:
            self._serve_asset(parsed.path.lstrip("/"))
            return
        self.send_error(404, "Not found")

    def do_HEAD(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/media":
            self._serve_media(parsed, include_body=False)
            return
        self.send_error(404, "Not found")

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/subtitles/render":
            try:
                job = create_subtitle_render_job(self._read_json())
                self._send_json({"jobId": job.id, "status": job.status}, status=202)
            except ActiveJobError as exc:
                self._send_active_job_conflict(exc.job)
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=400)
            return
        if path == "/api/upload":
            self._handle_upload()
            return
        if path == "/api/cache/clear":
            try:
                payload = self._read_json()
                out_dir = Path(str(payload.get("outDir") or "output")).expanduser().resolve()
                categories = [str(item) for item in payload.get("categories", [])]
                self._send_json(clear_cache(out_dir, categories))
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=400)
            return
        if path.startswith("/api/jobs/") and path.endswith("/cancel"):
            job_id = unquote(path.removeprefix("/api/jobs/").removesuffix("/cancel"))
            self._cancel_job(job_id)
            return
        if path.startswith("/api/jobs/") and path.endswith("/resume"):
            job_id = unquote(path.removeprefix("/api/jobs/").removesuffix("/resume"))
            try:
                resumed = resume_job(job_id)
            except ActiveJobError as exc:
                self._send_active_job_conflict(exc.job)
                return
            if not resumed:
                self._send_json({"error": "Job cannot be resumed."}, status=409)
                return
            self._send_json({"jobId": resumed.id, "status": resumed.status}, status=202)
            return
        if path != "/api/run":
            self.send_error(404, "Not found")
            return
        try:
            payload = self._read_json()
            options = options_from_payload(payload)
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=400)
            return

        try:
            job = create_pipeline_job(payload, options)
        except ActiveJobError as exc:
            self._send_active_job_conflict(exc.job)
            return
        self._send_json({"jobId": job.id, "status": job.status}, status=202)

    def do_PUT(self) -> None:
        path = urlparse(self.path).path
        if path != "/api/subtitles":
            self.send_error(404, "Not found")
            return
        try:
            payload = save_subtitle_payload(self._read_json())
            self._send_json(payload)
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=400)

    def _handle_upload(self) -> None:
        try:
            field = self._read_upload_file()
            filename = safe_upload_filename(field.filename or "uploaded-video.mp4")
            upload_dir = Path(tempfile.gettempdir()) / "subtitle-tool-uploads" / uuid.uuid4().hex
            upload_dir.mkdir(parents=True, exist_ok=True)
            output_path = upload_dir / filename
            with output_path.open("wb") as handle:
                shutil.copyfileobj(field.file, handle)
            if output_path.stat().st_size == 0:
                raise SubtitleToolError("Uploaded video is empty.")
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=400)
            return
        self._send_json(
            {
                "path": str(output_path),
                "filename": filename,
                "size": output_path.stat().st_size,
            }
        )

    def _serve_media(self, parsed, include_body: bool = True) -> None:
        query = parse_qs(parsed.query)
        try:
            out_dir = Path(query.get("outDir", ["output"])[0]).expanduser().resolve()
            path = Path(query.get("path", [""])[0])
            response = build_media_response(out_dir, path, self.headers.get("Range"))
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=400)
            return

        self.send_response(response.status)
        self.send_header("Content-Type", response.content_type)
        self.send_header("Content-Length", str(response.length))
        self.send_header("Accept-Ranges", "bytes")
        if response.content_range:
            self.send_header("Content-Range", response.content_range)
        self.end_headers()
        if not include_body:
            return
        try:
            with response.path.open("rb") as handle:
                handle.seek(response.start)
                remaining = response.length
                while remaining > 0:
                    chunk = handle.read(min(256 * 1024, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, format: str, *args: object) -> None:
        print(f"[web] {self.address_string()} - {format % args}")

    def _send_job(self, job_id: str) -> None:
        with JOB_LOCK:
            job = JOBS.get(job_id)
            payload = _job_to_dict(job) if job else None
        if not payload:
            self._send_json({"error": "Job not found."}, status=404)
            return
        self._send_json(payload)

    def _cancel_job(self, job_id: str) -> None:
        cancelled = request_job_cancel(job_id)
        with JOB_LOCK:
            job = JOBS.get(job_id)
            payload = _job_to_dict(job) if job else None
        if not payload:
            self._send_json({"error": "Job not found."}, status=404)
            return
        self._send_json({"cancelled": cancelled, "job": payload})

    def _read_json(self) -> dict[str, object]:
        length = int(self.headers.get("Content-Length") or "0")
        raw = self.rfile.read(length)
        if not raw:
            return {}
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("JSON body must be an object.")
        return payload

    def _read_upload_file(self) -> cgi.FieldStorage:
        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            raise SubtitleToolError("Upload request must use multipart/form-data.")
        form = cgi.FieldStorage(
            fp=self.rfile,
            headers=self.headers,
            environ={
                "REQUEST_METHOD": "POST",
                "CONTENT_TYPE": content_type,
                "CONTENT_LENGTH": self.headers.get("Content-Length", "0"),
            },
        )
        field = form["video"] if "video" in form else None
        if isinstance(field, list):
            field = field[0] if field else None
        if field is None or not getattr(field, "filename", None):
            raise SubtitleToolError("Upload request is missing a video file.")
        return field

    def _send_json(self, payload: dict[str, object], status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_active_job_conflict(self, job: JobState) -> None:
        self._send_json(
            {
                "error": f"已有任务正在运行: {job.id}",
                "activeJob": _job_to_dict(job),
            },
            status=409,
        )

    def _serve_asset(self, name: str) -> None:
        try:
            asset = resources.files("subtitle_tool").joinpath("web_assets").joinpath(name)
            data = asset.read_bytes()
        except FileNotFoundError:
            self.send_error(404, "Not found")
            return
        content_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
        if name.endswith(".html"):
            content_type = "text/html; charset=utf-8"
        elif name.endswith(".css"):
            content_type = "text/css; charset=utf-8"
        elif name.endswith(".js"):
            content_type = "application/javascript; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


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
        _update_job(
            job_id,
            status="failed",
            error=str(exc),
            log=f"重新生成失败: {exc}",
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
    try:
        _update_job(job_id, status="running", log="任务已启动", progress=1)
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
        _update_job(
            job_id,
            status="failed",
            error=str(exc),
            log=f"失败: {exc}",
            progress_message="任务失败",
        )
        return
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


def _job_to_dict(job: JobState | None) -> dict[str, object] | None:
    if not job:
        return None
    return {
        "id": job.id,
        "status": job.status,
        "logs": job.logs,
        "progress": job.progress,
        "progressMessage": job.progress_message,
        "cancelRequested": job.cancel_requested,
        "result": job.result,
        "error": job.error,
        "createdAt": job.created_at,
        "updatedAt": job.updated_at,
        "resumedFrom": job.resumed_from,
        "elapsedSeconds": max(0, round(job.updated_at - job.created_at)),
    }


def configure_job_store(path: Path) -> JobStore:
    global JOB_STORE
    store = JobStore(path)
    store.mark_inflight_interrupted()
    restored = [_job_from_record(record) for record in store.list()]
    with JOB_LOCK:
        JOBS.clear()
        JOBS.update({job.id: job for job in restored})
    JOB_STORE = store
    return store


def list_job_payloads(limit: int = 50) -> list[dict[str, object]]:
    with JOB_LOCK:
        jobs = sorted(JOBS.values(), key=lambda item: item.created_at, reverse=True)
        return [_job_to_dict(job) for job in jobs[:limit] if job is not None]


def jobs_payload(limit: int = 50) -> dict[str, object]:
    with JOB_LOCK:
        jobs = sorted(JOBS.values(), key=lambda item: item.created_at, reverse=True)
        current = _active_job_unlocked()
        return {
            "jobs": [_job_to_dict(job) for job in jobs[:limit] if job is not None],
            "activeJob": _job_to_dict(current),
        }


def cache_summary(out_dir: Path) -> dict[str, object]:
    return AssetCache(cache_root(out_dir)).summary()


def clear_cache(out_dir: Path, categories: list[str]) -> dict[str, object]:
    return AssetCache(cache_root(out_dir)).clear(categories)


def resume_job(job_id: str) -> JobState | None:
    with JOB_LOCK:
        original = JOBS.get(job_id)
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
        JOB_EXECUTOR.submit(_run_subtitle_render_job, resumed.id, payload)
    else:
        JOB_EXECUTOR.submit(_run_job, resumed.id, options)
    return resumed


def _persist_job(job: JobState) -> None:
    if JOB_STORE:
        JOB_STORE.save(_job_record(job))


def _job_record(job: JobState) -> dict[str, object]:
    return {
        "id": job.id,
        "status": job.status,
        "logs": list(job.logs),
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


def _tool_check(name: str) -> dict[str, object]:
    path = shutil.which(name)
    return {"name": name, "ok": path is not None, "detail": path or "未找到"}


def _python_module_check(name: str) -> dict[str, object]:
    spec = util.find_spec(name)
    return {
        "name": f"Python: {name}",
        "ok": spec is not None,
        "detail": "可用" if spec is not None else "未安装",
    }


def _whisper_models_check(root: Path) -> dict[str, object]:
    model_names = ["base", "small", "medium"]
    statuses = []
    has_any_model = False
    for name in model_names:
        path = root / "models" / f"ggml-{name}.bin"
        installed = path.exists() and path.stat().st_size > 0
        has_any_model = has_any_model or installed
        statuses.append(f"{name}: {'已安装' if installed else '未安装'}")
    return {
        "name": "Whisper 模型",
        "ok": has_any_model,
        "detail": "；".join(statuses),
    }


def _whisper_vad_model_check(root: Path) -> dict[str, object]:
    path = root / DEFAULT_VAD_MODEL_PATH
    installed = path.exists() and path.stat().st_size > 0
    return {
        "name": "Whisper VAD 模型",
        "ok": installed,
        "optional": True,
        "detail": str(path) if installed else "未安装；将自动使用标准语音转写",
    }


def _local_translation_model_checks() -> list[dict[str, object]]:
    checks = []
    for status in local_translation_model_statuses():
        installed = bool(status["installed"])
        detail = "已安装"
        if not installed:
            detail = f"未安装；下载命令：{status['downloadCommand']}"
        checks.append(
            {
                "name": f"本地翻译 {status['label']}",
                "ok": installed,
                "optional": True,
                "detail": detail,
            }
        )
    return checks


def _nllb_model_check(model_name: str, display_name: str) -> dict[str, object]:
    status = nllb_model_status(model_name=model_name)
    installed = bool(status["installed"])
    detail = "已安装"
    if not installed:
        detail = (
            "未安装；模型较大，首次下载较慢；下载命令："
            f"{status['downloadCommand']}"
        )
    return {
        "name": display_name,
        "ok": installed,
        "optional": True,
        "detail": detail,
    }


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


if __name__ == "__main__":
    raise SystemExit(main())
