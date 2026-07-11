from __future__ import annotations

import shutil
from pathlib import Path

from .errors import SubtitleToolError
from .srt import (
    SubtitleSegment,
    format_timestamp,
    parse_timestamp,
    read_srt,
    render_srt,
)
from .subtitle_layout import layout_subtitles


MAX_EDIT_SEGMENTS = 3000


def load_subtitle_document(out_dir: Path, path: Path) -> dict[str, object]:
    safe_path = _safe_output_path(out_dir, path, ".srt")
    if not safe_path.exists():
        raise SubtitleToolError(f"Subtitle file does not exist: {safe_path}")
    segments = read_srt(safe_path)
    if len(segments) > MAX_EDIT_SEGMENTS:
        raise SubtitleToolError(
            f"Subtitle editor supports at most {MAX_EDIT_SEGMENTS} segments."
        )
    return {
        "path": str(safe_path),
        "segments": [
            {
                "index": index,
                "start": format_timestamp(segment.start_ms),
                "end": format_timestamp(segment.end_ms),
                "text": segment.text,
            }
            for index, segment in enumerate(segments, start=1)
        ],
    }


def save_subtitle_document(
    out_dir: Path, path: Path, items: list[object]
) -> dict[str, object]:
    safe_path = _safe_output_path(out_dir, path, ".srt")
    if not safe_path.exists():
        raise SubtitleToolError(f"Subtitle file does not exist: {safe_path}")
    if not isinstance(items, list) or not items:
        raise SubtitleToolError("字幕内容不能为空。")
    if len(items) > MAX_EDIT_SEGMENTS:
        raise SubtitleToolError(f"字幕最多允许 {MAX_EDIT_SEGMENTS} 条。")

    segments: list[SubtitleSegment] = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise SubtitleToolError(f"第 {index} 条字幕格式无效。")
        try:
            start_ms = parse_timestamp(str(item.get("start") or ""))
            end_ms = parse_timestamp(str(item.get("end") or ""))
        except (ValueError, TypeError) as exc:
            raise SubtitleToolError(f"第 {index} 条字幕时间格式无效。") from exc
        if end_ms <= start_ms:
            raise SubtitleToolError(f"第 {index} 条字幕结束时间必须晚于开始时间。")
        text = str(item.get("text") or "").strip()
        if not text:
            raise SubtitleToolError(f"第 {index} 条字幕文字不能为空。")
        segments.append(SubtitleSegment(index, start_ms, end_ms, text))

    laid_out = layout_subtitles(segments)
    backup_path = safe_path.with_name(f"{safe_path.stem}.backup.srt")
    if not backup_path.exists():
        shutil.copy2(safe_path, backup_path)
    temporary_path = safe_path.with_name(f".{safe_path.name}.editing")
    temporary_path.write_text(render_srt(laid_out), encoding="utf-8")
    temporary_path.replace(safe_path)
    return {
        "path": str(safe_path),
        "backupPath": str(backup_path),
        "count": len(laid_out),
    }


def safe_output_path(out_dir: Path, path: Path, suffix: str) -> Path:
    return _safe_output_path(out_dir, path, suffix)


def _safe_output_path(out_dir: Path, path: Path, suffix: str) -> Path:
    root = out_dir.expanduser().resolve()
    resolved = path.expanduser().resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise SubtitleToolError("文件路径不在输出目录内。") from exc
    if resolved.suffix.lower() != suffix:
        raise SubtitleToolError(f"只允许访问 {suffix} 文件。")
    return resolved
