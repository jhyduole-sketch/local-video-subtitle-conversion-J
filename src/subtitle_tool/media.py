from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .errors import DependencyError, MediaError
from .process_control import CancelCheck, run_process


@dataclass(frozen=True)
class SubtitleStream:
    index: int
    codec_name: str | None
    language: str | None
    title: str | None


def ensure_ffmpeg() -> None:
    missing = [name for name in ("ffmpeg", "ffprobe") if shutil.which(name) is None]
    if missing:
        joined = ", ".join(missing)
        raise DependencyError(
            f"Missing required video tools: {joined}. Install ffmpeg first, for example: brew install ffmpeg"
        )


def _run(
    command: list[str], cancel_check: CancelCheck | None = None
) -> subprocess.CompletedProcess[str]:
    completed = run_process(command, cancel_check=cancel_check)
    if completed.returncode != 0:
        command_name = command[0]
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise MediaError(f"{command_name} failed: {detail}")
    return completed


def find_subtitle_streams(
    video_path: Path, cancel_check: CancelCheck | None = None
) -> list[SubtitleStream]:
    ensure_ffmpeg()
    completed = _run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "s",
            "-show_entries",
            "stream=index,codec_name:stream_tags=language,title",
            "-of",
            "json",
            str(video_path),
        ],
        cancel_check,
    )
    payload = json.loads(completed.stdout or "{}")
    streams = []
    for stream in payload.get("streams", []):
        tags = stream.get("tags", {}) or {}
        streams.append(
            SubtitleStream(
                index=int(stream["index"]),
                codec_name=stream.get("codec_name"),
                language=tags.get("language"),
                title=tags.get("title"),
            )
        )
    return streams


def extract_first_subtitle(
    video_path: Path,
    output_path: Path,
    cancel_check: CancelCheck | None = None,
) -> Path:
    ensure_ffmpeg()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-i",
            str(video_path),
            "-map",
            "0:s:0",
            str(output_path),
        ],
        cancel_check,
    )
    return output_path


def extract_audio(
    video_path: Path,
    output_path: Path,
    cancel_check: CancelCheck | None = None,
) -> Path:
    ensure_ffmpeg()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-i",
            str(video_path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-b:a",
            "64k",
            str(output_path),
        ],
        cancel_check,
    )
    return output_path


def mux_subtitle_track(
    video_path: Path,
    subtitle_path: Path,
    output_path: Path,
    language: str,
    title: str,
    cancel_check: CancelCheck | None = None,
) -> Path:
    ensure_ffmpeg()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-i",
            str(subtitle_path),
            "-map",
            "0:v",
            "-map",
            "0:a?",
            "-map",
            "1:0",
            "-c:v",
            "copy",
            "-c:a",
            "copy",
            "-c:s",
            "mov_text",
            "-metadata:s:s:0",
            f"language={language}",
            "-metadata:s:s:0",
            f"title={title}",
            "-disposition:s:0",
            "default",
            str(output_path),
        ],
        cancel_check,
    )
    return output_path
