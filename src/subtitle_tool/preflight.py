from __future__ import annotations

import os
from pathlib import Path
import shutil

from .errors import MediaError


MIN_RESERVE_BYTES = 128 * 1024 * 1024


def estimate_required_bytes(
    input_size: int,
    embed_subtitles: bool,
    subtitle_video_mode: str,
    target_count: int,
) -> int:
    if not embed_subtitles:
        return MIN_RESERVE_BYTES
    if subtitle_video_mode == "soft":
        return input_size + MIN_RESERVE_BYTES
    language_count = max(1, target_count)
    return input_size * language_count * 2 + MIN_RESERVE_BYTES


def validate_processing_space(
    input_path: Path,
    output_dir: Path,
    embed_subtitles: bool,
    subtitle_video_mode: str,
    target_count: int,
    *,
    available_bytes: int | None = None,
) -> int:
    if not input_path.is_file():
        raise MediaError(f"输入视频不存在: {input_path}")
    input_size = input_path.stat().st_size
    if input_size <= 0:
        raise MediaError(f"输入视频为空，无法处理: {input_path}")

    output_dir.mkdir(parents=True, exist_ok=True)
    if not os.access(output_dir, os.W_OK):
        raise MediaError(f"输出目录不可写: {output_dir}")

    required = estimate_required_bytes(
        input_size, embed_subtitles, subtitle_video_mode, target_count
    )
    available = (
        available_bytes
        if available_bytes is not None
        else shutil.disk_usage(output_dir).free
    )
    if available < required:
        raise MediaError(
            "输出磁盘可用空间不足："
            f"预计至少需要 {_format_bytes(required)}，"
            f"当前可用 {_format_bytes(available)}。"
        )
    return required


def _format_bytes(value: int) -> str:
    if value >= 1024**3:
        return f"{value / 1024**3:.1f} GB"
    return f"{value / 1024**2:.1f} MB"
