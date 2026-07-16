from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, urlparse

from .errors import DependencyError, SubtitleToolError
from .process_control import CancelCheck, run_process, timeout_seconds_from_env


TRAILING_URL_PUNCTUATION = "。．.，,、；;：:！!？?）)]}＞>」』”’\"'"


@dataclass(frozen=True)
class YouTubeVideo:
    video_id: str
    path: Path


@dataclass(frozen=True)
class DownloadedVideo:
    video_id: str
    path: Path


def is_youtube_url(value: str) -> bool:
    parsed = urlparse(clean_youtube_url(value))
    host = parsed.netloc.lower()
    return parsed.scheme in {"http", "https"} and (
        host in {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}
    )


def is_bilibili_url(value: str) -> bool:
    parsed = urlparse(clean_video_url(value))
    host = parsed.netloc.lower()
    return parsed.scheme in {"http", "https"} and (
        host in {"bilibili.com", "www.bilibili.com", "m.bilibili.com", "b23.tv"}
    )


def extract_youtube_id(value: str) -> str:
    parsed = urlparse(clean_youtube_url(value))
    host = parsed.netloc.lower()
    if host == "youtu.be":
        video_id = parsed.path.strip("/").split("/")[0]
    else:
        video_id = parse_qs(parsed.query).get("v", [""])[0]
    if not video_id:
        raise SubtitleToolError("Invalid YouTube URL: missing video id.")
    return video_id


def extract_bilibili_id(value: str) -> str:
    parsed = urlparse(clean_video_url(value))
    parts = [part for part in parsed.path.split("/") if part]
    for part in parts:
        if part.startswith(("BV", "av")):
            return part
    if parsed.netloc.lower() == "b23.tv" and parts:
        return parts[0]
    raise SubtitleToolError("Invalid Bilibili URL: missing BV/av video id.")


def download_youtube_video(
    value: str,
    out_dir: Path,
    force: bool = False,
    timestamp_suffix: str | None = None,
    cancel_check: CancelCheck | None = None,
    progress_callback: Callable[[str], None] | None = None,
) -> YouTubeVideo:
    downloaded = _download_with_ytdlp(
        value=value,
        out_dir=out_dir,
        force=force,
        timestamp_suffix=timestamp_suffix,
        video_id=extract_youtube_id(value),
        clean_value=clean_youtube_url(value),
        label="YouTube",
        cancel_check=cancel_check,
        progress_callback=progress_callback,
    )
    return YouTubeVideo(video_id=downloaded.video_id, path=downloaded.path)


def download_bilibili_video(
    value: str,
    out_dir: Path,
    force: bool = False,
    timestamp_suffix: str | None = None,
    cancel_check: CancelCheck | None = None,
    progress_callback: Callable[[str], None] | None = None,
) -> DownloadedVideo:
    clean_value = clean_video_url(value)
    return _download_with_ytdlp(
        value=value,
        out_dir=out_dir,
        force=force,
        timestamp_suffix=timestamp_suffix,
        video_id=extract_bilibili_id(clean_value),
        clean_value=clean_value,
        label="Bilibili",
        cancel_check=cancel_check,
        progress_callback=progress_callback,
    )


def download_generic_video(
    value: str,
    out_dir: Path,
    force: bool = False,
    timestamp_suffix: str | None = None,
    cancel_check: CancelCheck | None = None,
    progress_callback: Callable[[str], None] | None = None,
) -> DownloadedVideo:
    clean_value = clean_video_url(value)
    parsed = urlparse(clean_value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise SubtitleToolError("通用下载只支持有效的 HTTP/HTTPS 视频网址。")

    yt_dlp = _find_ytdlp()
    probe = run_process(
        [
            yt_dlp,
            "--dump-single-json",
            "--skip-download",
            "--flat-playlist",
            "--no-warnings",
            clean_value,
        ],
        cancel_check=cancel_check,
        timeout_seconds=timeout_seconds_from_env(
            "SUBTITLE_TOOL_DOWNLOAD_PROBE_TIMEOUT_SECONDS", 120.0
        ),
        heartbeat_interval_seconds=15.0,
        heartbeat_callback=_download_heartbeat(progress_callback, "正在解析视频网址"),
        operation_name="公开视频网址解析",
    )
    if probe.returncode != 0:
        detail = probe.stderr.strip() or probe.stdout.strip()
        raise _generic_download_error(detail, "解析")

    try:
        metadata = json.loads(probe.stdout)
    except (TypeError, json.JSONDecodeError) as exc:
        raise SubtitleToolError("通用解析失败：网站没有返回有效的视频信息。") from exc
    if not isinstance(metadata, dict):
        raise SubtitleToolError("通用解析失败：网站返回了无法识别的视频信息。")
    if metadata.get("_type") in {"playlist", "multi_video"} or metadata.get("entries"):
        raise SubtitleToolError("检测到播放列表或多集视频；当前版本只支持单个视频网址。")
    if metadata.get("is_live") or metadata.get("live_status") in {"is_live", "is_upcoming"}:
        raise SubtitleToolError("检测到直播或待开播内容；当前版本只支持普通点播视频。")

    video_id = _safe_video_id(str(metadata.get("id") or "video"))
    return _download_with_ytdlp(
        value=value,
        out_dir=out_dir,
        force=force,
        timestamp_suffix=timestamp_suffix,
        video_id=video_id,
        clean_value=clean_value,
        label="通用网址",
        cancel_check=cancel_check,
        error_factory=lambda detail: _generic_download_error(detail, "下载"),
        remux_video=True,
        progress_callback=progress_callback,
    )


def _download_with_ytdlp(
    *,
    value: str,
    out_dir: Path,
    force: bool,
    timestamp_suffix: str | None,
    video_id: str,
    clean_value: str,
    label: str,
    cancel_check: CancelCheck | None = None,
    error_factory=None,
    remux_video: bool = False,
    progress_callback: Callable[[str], None] | None = None,
) -> DownloadedVideo:
    yt_dlp = _find_ytdlp()

    downloads_dir = out_dir
    downloads_dir.mkdir(parents=True, exist_ok=True)
    file_stem = f"{video_id}.{timestamp_suffix}" if timestamp_suffix else video_id
    output_path = downloads_dir / f"{file_stem}.mp4"
    if output_path.exists() and output_path.stat().st_size > 0 and not force:
        return DownloadedVideo(video_id=video_id, path=output_path)

    output_template = str(downloads_dir / f"{file_stem}.%(ext)s")
    command = [
        yt_dlp,
        "-f",
        "bv*[ext=mp4]+ba[ext=m4a]/bv*+ba/b[ext=mp4]/b",
        "--merge-output-format",
        "mp4",
        "--no-playlist",
        "-o",
        output_template,
    ]
    if remux_video:
        command.extend(["--remux-video", "mp4"])
    command.append(clean_value)
    completed = run_process(
        command,
        cancel_check=cancel_check,
        timeout_seconds=timeout_seconds_from_env(
            "SUBTITLE_TOOL_DOWNLOAD_TIMEOUT_SECONDS", 7200.0
        ),
        heartbeat_interval_seconds=30.0,
        heartbeat_callback=_download_heartbeat(progress_callback, f"{label} 下载仍在进行"),
        operation_name=f"{label} 视频下载",
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        if error_factory:
            raise error_factory(detail)
        raise SubtitleToolError(f"{label} download failed: {detail}")
    if not output_path.exists() or output_path.stat().st_size == 0:
        raise SubtitleToolError(f"{label} download did not produce an MP4 file.")
    return DownloadedVideo(video_id=video_id, path=output_path)


def _download_heartbeat(
    progress_callback: Callable[[str], None] | None, label: str
) -> Callable[[float], None]:
    def heartbeat(elapsed_seconds: float) -> None:
        if progress_callback is not None:
            progress_callback(f"{label}，已用时 {_format_elapsed(elapsed_seconds)}")

    return heartbeat


def _format_elapsed(seconds: float) -> str:
    total = max(0, round(seconds))
    minutes, secs = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _find_ytdlp() -> str:
    yt_dlp = shutil.which("yt-dlp")
    if yt_dlp is None:
        raise DependencyError("yt-dlp is not installed. Install it with: brew install yt-dlp")
    return yt_dlp


def _safe_video_id(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._-")
    return safe[:120] or "video"


def _generic_download_error(detail: str, stage: str) -> SubtitleToolError:
    normalized = detail.lower()
    if any(marker in normalized for marker in ("sign in", "login", "log in", "cookies")):
        message = "页面需要登录，当前通用下载不会自动读取浏览器登录信息。"
    elif "drm" in normalized:
        message = "视频受 DRM 保护，当前工具无法下载或绕过保护。"
    elif any(marker in normalized for marker in ("geo", "not available in your country", "region")):
        message = "视频存在地区限制，当前网络位置无法访问。"
    elif any(marker in normalized for marker in ("http error 429", "too many requests", "rate limit")):
        message = "网站触发访问限流（429），请稍后重试或上传本地视频。"
    elif any(marker in normalized for marker in ("http error 403", "forbidden")):
        message = "网站拒绝访问（403），可能存在防爬验证或访问限制。"
    elif any(marker in normalized for marker in ("unsupported url", "no suitable extractor")):
        message = "当前网站暂不受通用下载器支持，请上传本地视频。"
    elif any(marker in normalized for marker in ("timed out", "timeout", "temporary failure", "network")):
        message = "访问网站超时或网络异常，请检查网络后重试。"
    else:
        compact_detail = " ".join(detail.split())[:500]
        message = f"未能取得视频：{compact_detail}" if compact_detail else "未能取得视频。"
    return SubtitleToolError(f"通用网址{stage}失败：{message}")


def clean_youtube_url(value: str) -> str:
    return clean_video_url(value)


def clean_video_url(value: str) -> str:
    return value.strip().rstrip(TRAILING_URL_PUNCTUATION)
