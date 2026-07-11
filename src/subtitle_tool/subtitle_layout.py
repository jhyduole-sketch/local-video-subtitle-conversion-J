from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from .srt import SubtitleSegment


MIN_SPLIT_DURATION_MS = 250
MIN_CUE_DURATION_MS = 120

ASS_POSITIONS = {
    "bottom": (2, 70),
    "above-bottom": (2, 190),
    "top": (8, 70),
}


def display_width(text: str) -> int:
    return sum(
        2 if unicodedata.east_asian_width(character) in {"W", "F"} else 1
        for character in text
    )


def layout_subtitles(
    segments: list[SubtitleSegment],
    max_width: int = 42,
    max_lines: int = 2,
    min_gap_ms: int = 40,
) -> list[SubtitleSegment]:
    laid_out: list[SubtitleSegment] = []
    for segment in segments:
        text = re.sub(r"\s+", " ", segment.text).strip()
        if not text:
            continue
        lines = _wrap_text(text, max_width)
        groups = [lines[index : index + max_lines] for index in range(0, len(lines), max_lines)]
        duration = max(segment.end_ms - segment.start_ms, MIN_CUE_DURATION_MS)
        if len(groups) > 1 and duration < len(groups) * MIN_SPLIT_DURATION_MS:
            groups = [lines]

        weights = [max(sum(display_width(line) for line in group), 1) for group in groups]
        total_weight = sum(weights)
        consumed_weight = 0
        for group_index, (group, weight) in enumerate(zip(groups, weights)):
            start_ms = segment.start_ms + round(duration * consumed_weight / total_weight)
            consumed_weight += weight
            end_ms = (
                segment.end_ms
                if group_index == len(groups) - 1
                else segment.start_ms + round(duration * consumed_weight / total_weight)
            )
            if end_ms <= start_ms:
                end_ms = start_ms + MIN_CUE_DURATION_MS
            laid_out.append(
                SubtitleSegment(
                    index=len(laid_out) + 1,
                    start_ms=start_ms,
                    end_ms=end_ms,
                    text="\n".join(group),
                )
            )

    return _repair_timing(laid_out, min_gap_ms)


def write_ass(
    path: Path, segments: list[SubtitleSegment], position: str
) -> None:
    if position not in ASS_POSITIONS:
        raise ValueError(f"Unsupported ASS subtitle position: {position}")
    alignment, margin_v = ASS_POSITIONS[position]
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: 1920",
        "PlayResY: 1080",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
        f"; Alignment={alignment}",
        f"; MarginV={margin_v}",
        "Style: Default,Arial Unicode MS,52,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,"
        f"0,0,0,0,100,100,0,0,1,4,1,{alignment},70,70,{margin_v},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for segment in segments:
        text = _escape_ass_text(segment.text)
        lines.append(
            "Dialogue: 0,"
            f"{_format_ass_timestamp(segment.start_ms)},"
            f"{_format_ass_timestamp(segment.end_ms)},"
            f"Default,,0,0,0,,{text}"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _wrap_text(text: str, max_width: int) -> list[str]:
    if max_width < 1:
        raise ValueError("max_width must be positive")
    units = _text_units(text)
    lines: list[str] = []
    current = ""
    for unit, needs_space in units:
        candidate = f"{current} {unit}" if current and needs_space else f"{current}{unit}"
        if current and display_width(candidate) > max_width:
            lines.append(current)
            current = unit
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines or [text]


def _text_units(text: str) -> list[tuple[str, bool]]:
    units: list[tuple[str, bool]] = []
    for word_index, word in enumerate(text.split(" ")):
        if not word:
            continue
        buffer = ""
        for character in word:
            is_wide = unicodedata.east_asian_width(character) in {"W", "F"}
            if is_wide:
                if buffer:
                    units.extend(_split_narrow_token(buffer, word_index > 0 and not units))
                    buffer = ""
                units.append((character, False))
            else:
                buffer += character
        if buffer:
            units.extend(_split_narrow_token(buffer, word_index > 0 or bool(units)))
    return units


def _split_narrow_token(token: str, needs_space: bool) -> list[tuple[str, bool]]:
    return [(token, needs_space)]


def _repair_timing(
    segments: list[SubtitleSegment], min_gap_ms: int
) -> list[SubtitleSegment]:
    repaired: list[SubtitleSegment] = []
    for segment in segments:
        current = segment
        if repaired and repaired[-1].end_ms + min_gap_ms > current.start_ms:
            previous = repaired[-1]
            shortened_end = current.start_ms - min_gap_ms
            if shortened_end - previous.start_ms >= MIN_CUE_DURATION_MS:
                repaired[-1] = SubtitleSegment(
                    index=previous.index,
                    start_ms=previous.start_ms,
                    end_ms=shortened_end,
                    text=previous.text,
                )
            else:
                shifted_start = previous.end_ms + min_gap_ms
                current = SubtitleSegment(
                    index=current.index,
                    start_ms=shifted_start,
                    end_ms=max(current.end_ms, shifted_start + MIN_CUE_DURATION_MS),
                    text=current.text,
                )
        repaired.append(current)

    return [
        SubtitleSegment(
            index=index,
            start_ms=segment.start_ms,
            end_ms=segment.end_ms,
            text=segment.text,
        )
        for index, segment in enumerate(repaired, start=1)
    ]


def _format_ass_timestamp(ms: int) -> str:
    centiseconds = max(ms, 0) // 10
    hours, remainder = divmod(centiseconds, 360_000)
    minutes, remainder = divmod(remainder, 6_000)
    seconds, centiseconds = divmod(remainder, 100)
    return f"{hours}:{minutes:02}:{seconds:02}.{centiseconds:02}"


def _escape_ass_text(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace("{", "\\{")
        .replace("}", "\\}")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\n", "\\N")
    )
