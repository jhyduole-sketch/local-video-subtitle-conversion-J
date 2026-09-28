"""集中校验请求来源、会话、路径范围及请求体大小。
Centralize request-origin, session, path-containment, and body-size checks.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from http.cookies import SimpleCookie
import hmac
import ipaddress
from pathlib import Path
import secrets
import threading
import time
from urllib.parse import urlparse

from .errors import SubtitleToolError


class RequestError(SubtitleToolError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def is_loopback(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@dataclass
class AccessPolicy:
    output_roots: tuple[Path, ...]
    input_roots: tuple[Path, ...]
    token: str | None = None
    max_json_bytes: int = 1024 * 1024
    max_upload_bytes: int = 2 * 1024 ** 3
    request_timeout: int = 60
    _sessions: dict[str, float] = field(default_factory=dict, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def validate_request(self, headers, server_address) -> None:
        host = headers.get("Host", "")
        try:
            authority = urlparse("//" + host)
            hostname = authority.hostname or ""
            port = authority.port or 80
            if authority.username or authority.password or authority.path or authority.query or authority.fragment:
                raise ValueError
            if not is_loopback(hostname):
                ipaddress.ip_address(hostname)
            bound_host, bound_port = server_address[:2]
            if port != bound_port or (is_loopback(bound_host) and not is_loopback(hostname)):
                raise ValueError
        except ValueError:
            raise RequestError("请求 Host 不在允许范围内。请使用服务启动时显示的地址。", 403)
        origin = headers.get("Origin")
        if origin:
            parsed = urlparse(origin)
            if parsed.scheme != "http" or parsed.netloc.lower() != host.lower() or parsed.path not in {"", "/"}:
                raise RequestError("拒绝来自其他网站的请求。", 403)
        if headers.get("Sec-Fetch-Site") == "cross-site":
            raise RequestError("拒绝跨站请求。", 403)

    def authenticated(self, headers) -> bool:
        if not self.token:
            return True
        authorization = headers.get("Authorization", "")
        if authorization.startswith("Bearer ") and hmac.compare_digest(
            authorization[7:].encode(), self.token.encode()
        ):
            return True
        cookies = SimpleCookie()
        try:
            cookies.load(headers.get("Cookie", ""))
        except Exception:
            return False
        cookie = cookies.get("subtitle_session")
        with self._lock:
            return bool(cookie and self._sessions.get(cookie.value, 0) > time.time())

    def create_session(self, token: object) -> str:
        if not self.token or not isinstance(token, str) or not hmac.compare_digest(token.encode(), self.token.encode()):
            raise RequestError("访问口令不正确。", 401)
        session = secrets.token_urlsafe(32)
        now = time.time()
        with self._lock:
            self._sessions = {key: expiry for key, expiry in self._sessions.items() if expiry > now}
            if len(self._sessions) >= 64:
                self._sessions.pop(next(iter(self._sessions)))
            self._sessions[session] = now + 12 * 60 * 60
        return f"subtitle_session={session}; HttpOnly; SameSite=Strict; Path=/; Max-Age=43200"

    def output_directory(self, value: object) -> Path:
        return self._allowed_path(value or "output", self.output_roots, "输出目录")

    def input_path(self, value: object, upload_root: Path) -> Path:
        return self._allowed_path(value, (*self.input_roots, upload_root), "本地输入")

    def artifact(self, out_dir: object, value: object, suffixes: set[str]) -> Path:
        root = self.output_directory(out_dir)
        path = self._allowed_path(value, (root,), "任务文件")
        if path.suffix.lower() not in suffixes:
            raise RequestError("文件类型不受支持。", 403)
        return path

    @staticmethod
    def _allowed_path(value: object, roots: tuple[Path, ...], label: str) -> Path:
        if not isinstance(value, (str, Path)) or not str(value).strip():
            raise RequestError(f"{label}不能为空。")
        # 先解析符号链接，再判断目录归属，防止链接绕过允许范围。
        # Resolve symlinks before checking containment so links cannot escape the allowed roots.
        path = Path(value).expanduser().resolve()
        for root in roots:
            try:
                path.relative_to(root)
                return path
            except ValueError:
                continue
        raise RequestError(f"{label}不在服务端允许的目录内。请上传视频，或在启动服务时配置允许目录。", 403)


def content_length(headers, maximum: int, *, required: bool = True) -> int:
    # 只接受单一且有界的请求长度，避免不同正文分帧方式产生歧义。
    # Require a single bounded request length to avoid ambiguous body framing.
    if headers.get("Transfer-Encoding"):
        raise RequestError("请求必须使用 Content-Length。", 411)
    lengths = headers.get_all("Content-Length", []) if hasattr(headers, "get_all") else [headers.get("Content-Length")]
    if len(lengths) > 1:
        raise RequestError("重复的 Content-Length。")
    value = headers.get("Content-Length")
    if value is None and not required:
        return 0
    if value is None or not value.isascii() or not value.isdigit():
        raise RequestError("请求缺少有效 Content-Length。", 411)
    length = int(value)
    if length > maximum:
        raise RequestError(f"请求超过大小限制（{maximum // (1024 * 1024)} MB）。", 413)
    return length
