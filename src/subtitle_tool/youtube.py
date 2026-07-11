from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .errors import DependencyError, SubtitleToolError


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
    value: str, out_dir: Path, force: bool = False, timestamp_suffix: str | None = None
) -> YouTubeVideo:
    downloaded = _download_with_ytdlp(
        value=value,
        out_dir=out_dir,
        force=force,
        timestamp_suffix=timestamp_suffix,
        video_id=extract_youtube_id(value),
        clean_value=clean_youtube_url(value),
        label="YouTube",
    )
    return YouTubeVideo(video_id=downloaded.video_id, path=downloaded.path)


def download_bilibili_video(
    value: str, out_dir: Path, force: bool = False, timestamp_suffix: str | None = None
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
) -> DownloadedVideo:
    yt_dlp = shutil.which("yt-dlp")
    if yt_dlp is None:
        raise DependencyError("yt-dlp is not installed. Install it with: brew install yt-dlp")

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
        clean_value,
    ]
    completed = subprocess.run(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise SubtitleToolError(f"{label} download failed: {detail}")
    if not output_path.exists() or output_path.stat().st_size == 0:
        raise SubtitleToolError(f"{label} download did not produce an MP4 file.")
    return DownloadedVideo(video_id=video_id, path=output_path)


def clean_youtube_url(value: str) -> str:
    return clean_video_url(value)


def clean_video_url(value: str) -> str:
    return value.strip().rstrip(TRAILING_URL_PUNCTUATION)
