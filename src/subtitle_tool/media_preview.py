from __future__ import annotations

import mimetypes
import re
from dataclasses import dataclass
from pathlib import Path

from .errors import SubtitleToolError


VIDEO_SUFFIXES = {".mp4", ".m4v", ".mov", ".webm", ".mkv"}
RANGE_PATTERN = re.compile(r"^bytes=(\d*)-(\d*)$")


@dataclass(frozen=True)
class MediaResponse:
    path: Path
    status: int
    start: int
    end: int
    total: int
    content_type: str

    @property
    def length(self) -> int:
        return self.end - self.start + 1

    @property
    def content_range(self) -> str | None:
        if self.status != 206:
            return None
        return f"bytes {self.start}-{self.end}/{self.total}"


def build_media_response(
    out_dir: Path, path: Path, range_header: str | None
) -> MediaResponse:
    safe_path = _safe_video_path(out_dir, path)
    if not safe_path.exists() or not safe_path.is_file():
        raise SubtitleToolError(f"视频文件不存在: {safe_path}")
    total = safe_path.stat().st_size
    if total <= 0:
        raise SubtitleToolError("视频文件为空。")
    content_type = mimetypes.guess_type(safe_path.name)[0] or "application/octet-stream"
    if not range_header:
        return MediaResponse(safe_path, 200, 0, total - 1, total, content_type)

    start, end = _parse_range(range_header.strip(), total)
    return MediaResponse(safe_path, 206, start, end, total, content_type)


def _safe_video_path(out_dir: Path, path: Path) -> Path:
    root = out_dir.expanduser().resolve()
    resolved = path.expanduser().resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise SubtitleToolError("视频文件路径不在输出目录内。") from exc
    if resolved.suffix.lower() not in VIDEO_SUFFIXES:
        raise SubtitleToolError("只允许预览视频文件。")
    return resolved


def _parse_range(value: str, total: int) -> tuple[int, int]:
    match = RANGE_PATTERN.fullmatch(value)
    if not match or (not match.group(1) and not match.group(2)):
        raise SubtitleToolError("无效的视频 Range 请求。")
    start_text, end_text = match.groups()
    if not start_text:
        suffix_length = int(end_text)
        if suffix_length <= 0:
            raise SubtitleToolError("无效的视频 Range 请求。")
        return max(0, total - suffix_length), total - 1

    start = int(start_text)
    end = int(end_text) if end_text else total - 1
    if start >= total or end < start:
        raise SubtitleToolError("视频 Range 超出文件范围。")
    return start, min(end, total - 1)
