"""本地字幕服务的 HTTP 路由和请求校验。
HTTP routing and request validation for the local subtitle service.
"""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler
from importlib import resources
import json
import mimetypes
import os
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

# 由 web.py 定义完服务函数后绑定，避免以 -m 启动时产生第二份模块状态。
# Bound by web.py after its service functions have been defined.
service = None
from .errors import SubtitleToolError
from .log_sanitizer import sanitize_diagnostic_text
from .media_preview import build_media_response, VIDEO_SUFFIXES
from .web_security import AccessPolicy, RequestError, content_length


class SubtitleToolHandler(BaseHTTPRequestHandler):
    server_version = "SubtitleToolWeb/0.1"

    @property
    def policy(self) -> AccessPolicy:
        return getattr(self.server, "access_policy", None) or service.default_access_policy()

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(self.policy.request_timeout)

    def _dispatch(self, handler) -> None:
        try:
            self.policy.validate_request(self.headers, self.server.server_address)
            parsed = urlparse(self.path)
            if self.command in {"POST", "PUT"}:
                maximum = self.policy.max_upload_bytes if parsed.path == "/api/upload" else self.policy.max_json_bytes
                content_length(self.headers, maximum)
            if parsed.path == "/api/session" and self.command == "POST":
                cookie = self.policy.create_session(self._read_json().get("token"))
                self._send_json({"ok": True}, headers={"Set-Cookie": cookie})
                return
            if not self.policy.authenticated(self.headers):
                if self.command == "GET" and parsed.path == "/":
                    self._serve_asset("login.html")
                    return
                if self.command == "GET" and parsed.path in {"/session.js", "/styles.css"}:
                    self._serve_asset(parsed.path[1:])
                    return
                raise RequestError("请输入服务的访问口令后继续。", 401)
            query = parse_qs(parsed.query)
            out_dir = query.get("outDir", ["output"])[0]
            if parsed.path in {"/api/media", "/api/subtitles"} and self.command in {"GET", "HEAD"}:
                suffixes = VIDEO_SUFFIXES if parsed.path == "/api/media" else {".srt"}
                self.policy.artifact(out_dir, query.get("path", [""])[0], suffixes)
            if parsed.path == "/api/cache":
                self._validate_cache_directory(out_dir)
            if parsed.path.endswith("/resume"):
                job_id = unquote(parsed.path.removeprefix("/api/jobs/").removesuffix("/resume"))
                with service.JOB_LOCK:
                    original = service._find_job_unlocked(job_id)
                    payload = dict(original.payload) if original else None
                if payload:
                    self._validate_payload(payload, render=payload.get("operation") == "render-edited-subtitles")
            handler()
        except RequestError as exc:
            self.close_connection = True
            self._send_json({"error": str(exc)}, status=exc.status)
        except (ValueError, OSError, SubtitleToolError) as exc:
            self.close_connection = True
            self._send_json({"error": sanitize_diagnostic_text(str(exc), Path.home())}, status=400)

    def _validate_cache_directory(self, value: object) -> Path:
        directory = self.policy.output_directory(value)
        configured = os.environ.get("SUBTITLE_TOOL_CACHE_DIR")
        if configured:
            root = Path(configured).expanduser().resolve()
        else:
            name = ".subtitle-tool-cache" if directory.name == "output" else f".{directory.name}.subtitle-tool-cache"
            root = directory.parent / name
            if root.resolve() != root or (directory / ".subtitle-tool-cache").is_symlink():
                raise RequestError("缓存目录不能指向允许范围外的符号链接。", 403)
        if any((root / name).is_symlink() for name in service.AssetCache.CATEGORY_DIRS.values()):
            raise RequestError("缓存分类目录不能是符号链接。", 403)
        return directory

    def _validate_payload(self, payload: dict, *, render: bool = False) -> None:
        root = self.policy.output_directory(payload.get("outDir") or "output")
        payload["outDir"] = str(root)
        if render:
            self.policy.artifact(root, payload.get("videoPath"), VIDEO_SUFFIXES)
            self.policy.artifact(root, payload.get("subtitlePath"), {".srt"})
        elif payload.get("input"):
            # 校验与执行必须使用同一个规范化值，避免空白字符造成路径检查差异。
            # Validate and execute the same normalized value to prevent whitespace-based path-check mismatches.
            value = str(payload["input"]).strip()
            if urlparse(value).scheme not in {"http", "https"}:
                value = str(self.policy.input_path(value, service.UPLOADS.root))
            payload["input"] = value

    def do_GET(self) -> None:
        self._dispatch(self._get)

    def _get(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._serve_asset("index.html")
            return
        if parsed.path == "/api/health":
            self._send_json(service.collect_health())
            return
        if parsed.path == "/api/settings":
            self._send_json({
                "settings": service.load_user_settings(service._settings_path()),
                "allowedOutputDirs": [str(path) for path in self.policy.output_roots],
                "maxUploadBytes": self.policy.max_upload_bytes,
            })
            return
        if parsed.path == "/api/first-run-guidance":
            self._send_json(service._first_run_guidance())
            return
        if parsed.path == "/api/jobs":
            query = parse_qs(parsed.query)
            limit = self._query_integer(query, "limit", 50, 1, 100)
            offset = self._query_integer(query, "offset", 0, 0, 1000000000)
            self._send_json(service.jobs_payload(limit=limit, offset=offset))
            return
        if parsed.path == "/api/cache":
            query = parse_qs(parsed.query)
            out_dir = Path(query.get("outDir", ["output"])[0]).expanduser().resolve()
            self._send_json(service.cache_summary(out_dir))
            return
        if parsed.path == "/api/subtitles":
            query = parse_qs(parsed.query)
            try:
                payload = service.subtitle_document_payload(
                    query.get("outDir", ["output"])[0],
                    query.get("path", [""])[0],
                )
                self._send_json(payload)
            except Exception as exc:
                self._send_json({"error": sanitize_diagnostic_text(str(exc), Path.home())}, status=getattr(exc, "status", 400))
            return
        if parsed.path == "/api/media":
            self._serve_media(parsed)
            return
        if parsed.path.startswith("/api/jobs/") and parsed.path.endswith("/logs"):
            self._download_job_logs(unquote(parsed.path.removeprefix("/api/jobs/").removesuffix("/logs")))
            return
        if parsed.path.startswith("/api/jobs/"):
            self._send_job(unquote(parsed.path.removeprefix("/api/jobs/")))
            return
        if parsed.path in {"/app.js", "/job_state.js", "/language_catalog.js", "/styles.css"}:
            self._serve_asset(parsed.path.lstrip("/"))
            return
        self.send_error(404, "Not found")

    def do_HEAD(self) -> None:
        self._dispatch(self._head)

    def _head(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/media":
            self._serve_media(parsed, include_body=False)
            return
        self.send_error(404, "Not found")

    def do_POST(self) -> None:
        self._dispatch(self._post)

    def _post(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/subtitles/render":
            try:
                job = service.create_subtitle_render_job(self._read_json())
                self._send_json({"jobId": job.id, "status": job.status}, status=202)
            except service.ActiveJobError as exc:
                self._send_active_job_conflict(exc.job)
            except Exception as exc:
                self._send_json({"error": sanitize_diagnostic_text(str(exc), Path.home())}, status=getattr(exc, "status", 400))
            return
        if path == "/api/upload":
            self._handle_upload()
            return
        if path == "/api/inputs/clear":
            payload = self._read_json()
            out_dir = self.policy.output_directory(payload.get("outDir") or "output")
            self._send_json(service.clear_retained_inputs(out_dir))
            return
        if path == "/api/cache/clear":
            try:
                payload = self._read_json()
                out_dir = Path(str(payload.get("outDir") or "output")).expanduser().resolve()
                categories = [str(item) for item in payload.get("categories", [])]
                self._send_json(service.clear_cache(out_dir, categories))
            except Exception as exc:
                self._send_json({"error": sanitize_diagnostic_text(str(exc), Path.home())}, status=getattr(exc, "status", 400))
            return
        if path == "/api/jobs/clear":
            try:
                self._send_json(service.clear_finished_jobs())
            except Exception as exc:
                self._send_json({"error": sanitize_diagnostic_text(str(exc), Path.home())}, status=getattr(exc, "status", 400))
            return
        if path.startswith("/api/jobs/") and path.endswith("/cancel"):
            job_id = unquote(path.removeprefix("/api/jobs/").removesuffix("/cancel"))
            self._cancel_job(job_id)
            return
        if path.startswith("/api/jobs/") and path.endswith("/resume"):
            job_id = unquote(path.removeprefix("/api/jobs/").removesuffix("/resume"))
            try:
                resumed = service.resume_job(job_id)
            except service.ActiveJobError as exc:
                self._send_active_job_conflict(exc.job)
                return
            except Exception as exc:
                self._send_json({"error": sanitize_diagnostic_text(str(exc), Path.home())}, status=getattr(exc, "status", 400))
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
            options = service.options_from_payload(payload)
        except Exception as exc:
            self._send_json({"error": sanitize_diagnostic_text(str(exc), Path.home())}, status=getattr(exc, "status", 400))
            return

        try:
            job = service.create_pipeline_job(payload, options)
        except service.ActiveJobError as exc:
            self._send_active_job_conflict(exc.job)
            return
        self._send_json({"jobId": job.id, "status": job.status}, status=202)

    def do_PUT(self) -> None:
        self._dispatch(self._put)

    def _put(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/settings":
            try:
                settings = service.save_user_settings(self._read_json(), service._settings_path())
                self._send_json({"settings": settings})
            except Exception as exc:
                self._send_json({"error": sanitize_diagnostic_text(str(exc), Path.home())}, status=getattr(exc, "status", 400))
            return
        if path != "/api/subtitles":
            self.send_error(404, "Not found")
            return
        try:
            payload = service.save_subtitle_payload(self._read_json())
            self._send_json(payload)
        except Exception as exc:
            self._send_json({"error": sanitize_diagnostic_text(str(exc), Path.home())}, status=getattr(exc, "status", 400))

    def _handle_upload(self) -> None:
        try:
            length = content_length(self.headers, self.policy.max_upload_bytes)
            service.UPLOADS.cleanup()
            content_type = self.headers.get("Content-Type", "")
            if content_type.startswith("multipart/form-data"):
                output_path = service.UPLOADS.receive_multipart(self.rfile, length, content_type)
            elif content_type.split(";", 1)[0] == "application/octet-stream":
                filename = unquote(self.headers.get("X-Filename", "uploaded-video.mp4"))
                output_path = service.UPLOADS.receive(self.rfile, length, filename)
            else:
                raise RequestError("上传请求需使用视频文件或 multipart/form-data。", 415)
        except Exception as exc:
            self.close_connection = True
            self._send_json({"error": str(exc)}, status=getattr(exc, "status", 400))
            return
        self._send_json(
            {
                "path": str(output_path),
                "filename": output_path.name,
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
            self._send_json({"error": sanitize_diagnostic_text(str(exc), Path.home())}, status=getattr(exc, "status", 400))
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

    def _download_job_logs(self, job_id: str) -> None:
        payload = service.job_payload(job_id, log_limit=200)
        if payload is None:
            self._send_json({"error": "Job not found."}, status=404)
            return
        total = payload["logTotal"]
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Disposition", 'attachment; filename="subtitle-job.log"')
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        try:
            if payload.get("logTruncated"):
                self.wfile.write("较早日志不可用，以下为保留日志。\n".encode())
            while payload:
                lines = payload["logs"][:max(0, total - payload["logOffset"])]
                if not lines:
                    break
                self.wfile.write(("\n".join(lines) + "\n").encode("utf-8"))
                offset = payload["nextLogOffset"]
                if offset >= total:
                    break
                payload = service.job_payload(job_id, log_offset=offset, log_limit=min(200, total - offset))
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _send_job(self, job_id: str) -> None:
        query = parse_qs(urlparse(self.path).query)
        offset = self._query_integer(query, "logOffset", 0, 0, 1000000000)
        limit = self._query_integer(query, "logLimit", 200, 1, 1000) if "logLimit" in query or "logOffset" in query else None
        payload = service.job_payload(job_id, log_offset=offset, log_limit=limit)
        if not payload:
            self._send_json({"error": "Job not found."}, status=404)
            return
        self._send_json(payload)

    def _cancel_job(self, job_id: str) -> None:
        cancelled = service.request_job_cancel(job_id)
        payload = service.job_payload(job_id, log_offset=0, log_limit=0)
        if not payload:
            self._send_json({"error": "Job not found."}, status=404)
            return
        self._send_json({"cancelled": cancelled, "job": payload})

    @staticmethod
    def _query_integer(query, key: str, default: int, minimum: int, maximum: int) -> int:
        values = query.get(key)
        if values is None:
            return default
        if len(values) != 1 or not values[0].isascii() or not values[0].isdigit():
            raise RequestError(f"{key} 必须是整数。")
        value = int(values[0])
        if not minimum <= value <= maximum:
            raise RequestError(f"{key} 超出允许范围。")
        return value

    def _read_json(self) -> dict[str, object]:
        length = content_length(self.headers, self.policy.max_json_bytes)
        if length and self.headers.get("Content-Type", "").split(";", 1)[0].strip() != "application/json":
            raise RequestError("请求需要 application/json。", 415)
        raw = self.rfile.read(length)
        if len(raw) != length:
            raise RequestError("请求正文未完整传输。")
        if not raw:
            return {}
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("JSON body must be an object.")
        path = urlparse(self.path).path
        if path in {"/api/run", "/api/subtitles/render"}:
            self._validate_payload(payload, render=path.endswith("/render"))
        elif path == "/api/subtitles":
            self.policy.artifact(payload.get("outDir") or "output", payload.get("path"), {".srt"})
        elif path == "/api/settings" and "outputDir" in payload:
            self.policy.output_directory(payload["outputDir"])
        elif path == "/api/inputs/clear":
            self.policy.output_directory(payload.get("outDir") or "output")
        elif path == "/api/cache/clear":
            self._validate_cache_directory(payload.get("outDir") or "output")
        return payload

    def _send_json(self, payload: dict[str, object], status: int = 200, headers: dict | None = None) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def _send_active_job_conflict(self, job: JobState) -> None:
        self._send_json(
            {
                "error": f"已有任务正在运行: {job.id}",
                "activeJob": service._job_to_dict(job),
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
