from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .errors import DependencyError, MediaError
from .process_control import (
    CancelCheck,
    run_process,
    run_process_streaming,
    timeout_seconds_from_env,
)


@dataclass(frozen=True)
class SubtitleStream:
    index: int
    codec_name: str | None
    language: str | None
    title: str | None


@dataclass(frozen=True)
class EncodingProgress:
    processed_seconds: float
    duration_seconds: float
    percent: int
    speed: float | None
    eta_seconds: float | None


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


def videotoolbox_available() -> bool:
    try:
        binary = ass_ffmpeg_binary()
    except DependencyError:
        return False
    return _ffmpeg_has_encoder(binary, "h264_videotoolbox")


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


def _ffmpeg_has_encoder(binary: str, encoder_name: str) -> bool:
    completed = subprocess.run(
        [binary, "-hide_banner", "-encoders"],
        capture_output=True,
        text=True,
        check=False,
    )
    output = f"{completed.stdout}\n{completed.stderr}"
    pattern = rf"^\s*V\S*\s+{re.escape(encoder_name)}\s"
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
    encoding_profile: str = "quality",
    progress_callback: Callable[[EncodingProgress], None] | None = None,
    status_callback: Callable[[str], None] | None = None,
) -> Path:
    if encoding_profile not in {"auto", "hardware", "fast", "quality"}:
        raise MediaError(f"Unknown hard subtitle encoding profile: {encoding_profile}")
    ffmpeg_binary = ass_ffmpeg_binary()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ass_filter_path = _escape_filter_path(ass_path)
    duration = _probe_duration_seconds(video_path, cancel_check)
    selected_profile = encoding_profile
    if encoding_profile in {"auto", "hardware"}:
        if _ffmpeg_has_encoder(ffmpeg_binary, "h264_videotoolbox"):
            selected_profile = "hardware"
            if status_callback:
                status_callback("使用 Apple VideoToolbox 硬件编码")
        else:
            selected_profile = "fast"
            if status_callback:
                status_callback("VideoToolbox 不可用，已切换快速 CPU 编码")

    completed = _run_burn_command(
        _burn_command(
            ffmpeg_binary,
            video_path,
            ass_filter_path,
            output_path,
            selected_profile,
        ),
        duration,
        cancel_check,
        progress_callback,
        status_callback,
    )
    if completed.returncode != 0 and selected_profile == "hardware":
        output_path.unlink(missing_ok=True)
        if status_callback:
            detail = _short_error(completed.stderr or completed.stdout)
            status_callback(
                f"VideoToolbox 编码失败（{detail}），已切换快速 CPU 编码重试"
            )
        completed = _run_burn_command(
            _burn_command(
                ffmpeg_binary,
                video_path,
                ass_filter_path,
                output_path,
                "fast",
            ),
            duration,
            cancel_check,
            progress_callback,
            status_callback,
        )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise MediaError(f"{ffmpeg_binary} failed: {detail}")
    return output_path


def _probe_duration_seconds(
    video_path: Path, cancel_check: CancelCheck | None = None
) -> float:
    completed = _run(
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
        return max(float(completed.stdout.strip()), 0.001)
    except ValueError as exc:
        raise MediaError("Unable to read video duration for subtitle encoding.") from exc


def _burn_command(
    ffmpeg_binary: str,
    video_path: Path,
    ass_filter_path: str,
    output_path: Path,
    encoding_profile: str,
) -> list[str]:
    command = [
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
    ]
    if encoding_profile == "hardware":
        command.extend(
            [
                "-c:v",
                "h264_videotoolbox",
                "-profile:v",
                "high",
                "-b:v",
                "20M",
                "-maxrate",
                "30M",
                "-bufsize",
                "40M",
                "-allow_sw",
                "1",
            ]
        )
    elif encoding_profile == "fast":
        command.extend(["-c:v", "libx264", "-preset", "veryfast", "-crf", "20"])
    else:
        command.extend(["-c:v", "libx264", "-preset", "medium", "-crf", "18"])
    command.extend(
        [
            "-c:a",
            "copy",
            "-movflags",
            "+faststart",
            "-progress",
            "pipe:1",
            "-nostats",
            str(output_path),
        ]
    )
    return command


def _run_burn_command(
    command: list[str],
    duration_seconds: float,
    cancel_check: CancelCheck | None,
    progress_callback: Callable[[EncodingProgress], None] | None,
    status_callback: Callable[[str], None] | None,
) -> subprocess.CompletedProcess[str]:
    values: dict[str, str] = {}
    last_percent = -1

    def handle_line(line: str) -> None:
        nonlocal last_percent
        key, separator, value = line.partition("=")
        if not separator:
            return
        values[key] = value
        if key != "progress" or progress_callback is None:
            return
        try:
            processed = max(float(values.get("out_time_us", "0")) / 1_000_000, 0.0)
        except ValueError:
            processed = 0.0
        speed_text = values.get("speed", "").rstrip("x")
        try:
            speed = float(speed_text) if speed_text else None
        except ValueError:
            speed = None
        percent = min(100, max(0, round(processed * 100 / duration_seconds)))
        if percent == last_percent:
            return
        last_percent = percent
        eta = None
        if speed and speed > 0:
            eta = max(duration_seconds - processed, 0.0) / speed
        progress_callback(
            EncodingProgress(processed, duration_seconds, percent, speed, eta)
        )

    def heartbeat(elapsed_seconds: float) -> None:
        if status_callback is not None:
            status_callback(
                f"编码仍在运行，已用时 {_format_runtime(elapsed_seconds)}；"
                "若 5 分钟没有任何进度将自动停止"
            )

    return run_process_streaming(
        command,
        cancel_check=cancel_check,
        stdout_line_callback=handle_line,
        timeout_seconds=timeout_seconds_from_env(
            "SUBTITLE_TOOL_BURN_TIMEOUT_SECONDS", 43200.0
        ),
        inactivity_timeout_seconds=timeout_seconds_from_env(
            "SUBTITLE_TOOL_BURN_INACTIVITY_TIMEOUT_SECONDS", 300.0
        ),
        heartbeat_interval_seconds=30.0,
        heartbeat_callback=heartbeat,
        operation_name="固定位置硬字幕烧录",
    )


def _format_runtime(seconds: float) -> str:
    total = max(0, round(seconds))
    minutes, secs = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _short_error(output: str) -> str:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    for line in reversed(lines):
        if "error" in line.lower() or "cannot" in line.lower():
            return line[:180]
    return (lines[-1][:180] if lines else "未知错误")


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
