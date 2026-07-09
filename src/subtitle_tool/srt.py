from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


TIMESTAMP_RE = re.compile(
    r"(?P<start>\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(?P<end>\d{2}:\d{2}:\d{2},\d{3})"
)


@dataclass(frozen=True)
class SubtitleSegment:
    index: int
    start_ms: int
    end_ms: int
    text: str


def parse_timestamp(value: str) -> int:
    hours, minutes, rest = value.split(":")
    seconds, millis = rest.split(",")
    return (
        int(hours) * 3_600_000
        + int(minutes) * 60_000
        + int(seconds) * 1_000
        + int(millis)
    )


def format_timestamp(ms: int) -> str:
    if ms < 0:
        ms = 0
    hours, remainder = divmod(ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1_000)
    return f"{hours:02}:{minutes:02}:{seconds:02},{millis:03}"


def parse_srt(content: str) -> list[SubtitleSegment]:
    normalized = content.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return []

    segments: list[SubtitleSegment] = []
    blocks = re.split(r"\n{2,}", normalized)
    fallback_index = 1

    for block in blocks:
        lines = [line.strip("\ufeff") for line in block.split("\n")]
        if not lines:
            continue

        first_line_is_index = lines[0].strip().isdigit()
        time_line_position = 1 if first_line_is_index and len(lines) > 1 else 0
        if time_line_position >= len(lines):
            continue

        match = TIMESTAMP_RE.search(lines[time_line_position])
        if not match:
            continue

        index = int(lines[0].strip()) if first_line_is_index else fallback_index
        text_lines = lines[time_line_position + 1 :]
        text = "\n".join(line.rstrip() for line in text_lines).strip()
        segments.append(
            SubtitleSegment(
                index=index,
                start_ms=parse_timestamp(match.group("start")),
                end_ms=parse_timestamp(match.group("end")),
                text=text,
            )
        )
        fallback_index = index + 1

    return segments


def read_srt(path: Path) -> list[SubtitleSegment]:
    return parse_srt(path.read_text(encoding="utf-8-sig"))


def render_srt(segments: list[SubtitleSegment]) -> str:
    blocks = []
    for output_index, segment in enumerate(segments, start=1):
        text = segment.text.strip()
        blocks.append(
            "\n".join(
                [
                    str(output_index),
                    f"{format_timestamp(segment.start_ms)} --> {format_timestamp(segment.end_ms)}",
                    text,
                ]
            )
        )
    return "\n\n".join(blocks) + "\n"


def write_srt(path: Path, segments: list[SubtitleSegment]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_srt(segments), encoding="utf-8")


def replace_text(
    source_segments: list[SubtitleSegment], translated_text_by_index: dict[int, str]
) -> list[SubtitleSegment]:
    translated_segments: list[SubtitleSegment] = []
    for segment in source_segments:
        translated_segments.append(
            SubtitleSegment(
                index=segment.index,
                start_ms=segment.start_ms,
                end_ms=segment.end_ms,
                text=translated_text_by_index.get(segment.index, segment.text),
            )
        )
    return translated_segments

