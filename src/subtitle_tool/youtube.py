from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .errors import DependencyError, SubtitleToolError


@dataclass(frozen=True)
class YouTubeVideo:
    video_id: str
    path: Path


def is_youtube_url(value: str) -> bool:
    parsed = urlparse(value)
    host = parsed.netloc.lower()
    return parsed.scheme in {"http", "https"} and (
        host in {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}
    )


def extract_youtube_id(value: str) -> str:
    parsed = urlparse(value)
    host = parsed.netloc.lower()
    if host == "youtu.be":
        video_id = parsed.path.strip("/").split("/")[0]
    else:
        video_id = parse_qs(parsed.query).get("v", [""])[0]
    if not video_id:
        raise SubtitleToolError("Invalid YouTube URL: missing video id.")
    return video_id


def download_youtube_video(value: str, out_dir: Path, force: bool = False) -> YouTubeVideo:
    yt_dlp = shutil.which("yt-dlp")
    if yt_dlp is None:
        raise DependencyError("yt-dlp is not installed. Install it with: brew install yt-dlp")

    video_id = extract_youtube_id(value)
    downloads_dir = out_dir / "youtube"
    downloads_dir.mkdir(parents=True, exist_ok=True)
    output_path = downloads_dir / f"{video_id}.mp4"
    if output_path.exists() and output_path.stat().st_size > 0 and not force:
        return YouTubeVideo(video_id=video_id, path=output_path)

    output_template = str(downloads_dir / "%(id)s.%(ext)s")
    command = [
        yt_dlp,
        "-f",
        "18/b[ext=mp4]/b",
        "--merge-output-format",
        "mp4",
        "-o",
        output_template,
        value,
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
        raise SubtitleToolError(f"YouTube download failed: {detail}")
    if not output_path.exists() or output_path.stat().st_size == 0:
        raise SubtitleToolError("YouTube download did not produce an MP4 file.")
    return YouTubeVideo(video_id=video_id, path=output_path)

