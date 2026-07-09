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
from dataclasses import dataclass, field, replace
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import util
from importlib import resources
from pathlib import Path
from urllib.parse import unquote, urlparse

from .env import load_dotenv
from .errors import CancellationError, SubtitleToolError
from .pipeline import PipelineOptions, PipelineResult, run_pipeline


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


JOBS: dict[str, JobState] = {}
JOB_LOCK = threading.Lock()


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
    source_lang = str(payload.get("sourceLang") or "").strip() or None

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
        translator=str(payload.get("translator") or "local-transformer"),
        embed_subtitles=bool(payload.get("embedSubtitles")),
        avoid_subtitle_overlap=bool(payload.get("avoidSubtitleOverlap")),
    )


def collect_health(project_root: Path | None = None) -> dict[str, object]:
    root = project_root or Path.cwd()
    model_path = root / "models" / "ggml-base.bin"
    checks = [
        _tool_check("ffmpeg"),
        _tool_check("ffprobe"),
        _tool_check("yt-dlp"),
        _tool_check("whisper-cli"),
        {
            "name": "Whisper 模型",
            "ok": model_path.exists() and model_path.stat().st_size > 0,
            "detail": str(model_path),
        },
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
    return {
        "checks": checks,
        "ok": all(check["ok"] for check in checks if not check.get("optional")),
    }


def result_to_dict(result: PipelineResult) -> dict[str, object]:
    return {
        "sourceSubtitlePath": _path_or_none(result.source_subtitle_path),
        "translatedPaths": {
            language: str(path) for language, path in result.translated_paths.items()
        },
        "failedLanguages": result.failed_languages,
        "sourceKind": result.source_kind,
        "downloadedVideoPath": _path_or_none(result.downloaded_video_path),
        "subtitledVideoPaths": {
            language: str(path)
            for language, path in (result.subtitled_video_paths or {}).items()
        },
    }


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
        if parsed.path.startswith("/api/jobs/"):
            self._send_job(unquote(parsed.path.removeprefix("/api/jobs/")))
            return
        if parsed.path in {"/app.js", "/styles.css"}:
            self._serve_asset(parsed.path.lstrip("/"))
            return
        self.send_error(404, "Not found")

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/upload":
            self._handle_upload()
            return
        if path.startswith("/api/jobs/") and path.endswith("/cancel"):
            job_id = unquote(path.removeprefix("/api/jobs/").removesuffix("/cancel"))
            self._cancel_job(job_id)
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

        job = JobState(id=uuid.uuid4().hex[:12])
        with JOB_LOCK:
            JOBS[job.id] = job
        thread = threading.Thread(target=_run_job, args=(job.id, options), daemon=True)
        thread.start()
        self._send_json({"jobId": job.id, "status": job.status}, status=202)

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


def _run_job(job_id: str, options: PipelineOptions) -> None:
    _update_job(job_id, status="running", log="任务已启动", progress=1)
    try:
        options = replace(
            options,
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
            job.progress = max(0, min(100, progress))
        if progress_message is not None:
            job.progress_message = progress_message
        job.updated_at = time.time()


def request_job_cancel(job_id: str) -> bool:
    with JOB_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return False
        if job.status not in {"queued", "running", "canceling"}:
            return False
        if not job.cancel_requested:
            job.cancel_requested = True
            job.status = "canceling"
            job.progress_message = "正在停止"
            job.logs.append(_format_log_line(job, "收到停止请求，当前步骤结束后停止"))
            job.updated_at = time.time()
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
        "elapsedSeconds": max(0, round(job.updated_at - job.created_at)),
    }


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
