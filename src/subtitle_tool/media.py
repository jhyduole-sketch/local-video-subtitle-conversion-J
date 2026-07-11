from __future__ import annotations

import json
import os
import re
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


def ass_ffmpeg_binary() -> str:
    for binary in _candidate_ffmpeg_binaries():
        if _ffmpeg_has_filter(binary, "ass"):
            return binary
    raise DependencyError(
        "Stable hard subtitles require an FFmpeg build with the libass filter. "
        "Install it with: brew install ffmpeg-full. The tool will automatically "
        "use /opt/homebrew/opt/ffmpeg-full/bin/ffmpeg after installation."
    )


def _candidate_ffmpeg_binaries() -> list[str]:
    values = [
        os.environ.get("FFMPEG_FULL_BIN", "").strip(),
        "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg",
        "/usr/local/opt/ffmpeg-full/bin/ffmpeg",
        shutil.which("ffmpeg") or "",
    ]
    candidates: list[str] = []
    for value in values:
        if value and value not in candidates and Path(value).is_file():
            candidates.append(value)
    return candidates


def _ffmpeg_has_filter(binary: str, filter_name: str) -> bool:
    completed = subprocess.run(
        [binary, "-hide_banner", "-filters"],
        capture_output=True,
        text=True,
        check=False,
    )
    output = f"{completed.stdout}\n{completed.stderr}"
    pattern = rf"^\s*[TSC\.]+\s+{re.escape(filter_name)}\s"
    return completed.returncode == 0 and re.search(pattern, output, re.MULTILINE) is not None


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


def sample_video_edge_frames(
    video_path: Path,
    output_dir: Path,
    sample_count: int = 8,
    cancel_check: CancelCheck | None = None,
) -> list[Path]:
    ensure_ffmpeg()
    duration_result = _run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(video_path),
        ],
        cancel_check,
    )
    try:
        duration = max(float(duration_result.stdout.strip()), 0.1)
    except ValueError as exc:
        raise MediaError("Unable to read video duration for subtitle detection.") from exc
    output_dir.mkdir(parents=True, exist_ok=True)
    for existing in output_dir.glob("frame-*.pgm"):
        existing.unlink()
    interval = max(duration / max(sample_count, 1), 0.25)
    output_pattern = output_dir / "frame-%02d.pgm"
    _run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-i",
            str(video_path),
            "-vf",
            f"fps=1/{interval:.3f},scale=640:-2,format=gray,"
            "edgedetect=low=0.08:high=0.2",
            "-frames:v",
            str(sample_count),
            str(output_pattern),
        ],
        cancel_check,
    )
    return sorted(output_dir.glob("frame-*.pgm"))


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


def burn_subtitle_track(
    video_path: Path,
    ass_path: Path,
    output_path: Path,
    cancel_check: CancelCheck | None = None,
) -> Path:
    ffmpeg_binary = ass_ffmpeg_binary()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ass_filter_path = _escape_filter_path(ass_path)
    _run(
        [
            ffmpeg_binary,
            "-y",
            "-i",
            str(video_path),
            "-vf",
            f"ass=filename='{ass_filter_path}'",
            "-map",
            "0:v:0",
            "-map",
            "0:a?",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-c:a",
            "copy",
            "-movflags",
            "+faststart",
            str(output_path),
        ],
        cancel_check,
    )
    return output_path


def _escape_filter_path(path: Path) -> str:
    return (
        str(path)
        .replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "\\'")
        .replace(",", "\\,")
        .replace("[", "\\[")
        .replace("]", "\\]")
    )
