from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .process_control import CancelCheck


@dataclass(frozen=True)
class EdgeFrame:
    width: int
    height: int
    pixels: bytes


@dataclass(frozen=True)
class SubtitleRegionDetection:
    position: str
    confidence: float
    sampled_frames: int
    top_score: float
    bottom_score: float


def detect_video_subtitle_region(
    video_path: Path,
    work_dir: Path,
    cancel_check: CancelCheck | None = None,
) -> SubtitleRegionDetection:
    from .media import sample_video_edge_frames

    paths = sample_video_edge_frames(
        video_path, work_dir, sample_count=8, cancel_check=cancel_check
    )
    frames = [read_pgm(path) for path in paths]
    return detect_subtitle_region_from_frames(frames)


def detect_subtitle_region_from_frames(
    frames: list[EdgeFrame],
) -> SubtitleRegionDetection:
    if not frames:
        return SubtitleRegionDetection("unknown", 0.0, 0, 0.0, 0.0)

    top_scores = [_band_score(frame, 0.05, 0.4) for frame in frames]
    bottom_scores = [_band_score(frame, 0.55, 0.95) for frame in frames]
    return classify_band_scores(top_scores, bottom_scores)


def classify_band_scores(
    top_scores: list[float], bottom_scores: list[float]
) -> SubtitleRegionDetection:
    if not top_scores or len(top_scores) != len(bottom_scores):
        return SubtitleRegionDetection("unknown", 0.0, 0, 0.0, 0.0)
    threshold = 0.045
    top_hits = sum(score >= threshold for score in top_scores)
    bottom_hits = sum(score >= threshold for score in bottom_scores)
    top_score = sum(top_scores) / len(top_scores)
    bottom_score = sum(bottom_scores) / len(bottom_scores)
    sampled = len(top_scores)

    if top_hits == 0 and bottom_hits == 0:
        confidence = max(0.5, 1.0 - max(top_score, bottom_score) / threshold)
        return SubtitleRegionDetection(
            "none", round(min(confidence, 1.0), 3), sampled, top_score, bottom_score
        )

    hit_difference = abs(top_hits - bottom_hits)
    score_difference = abs(top_score - bottom_score)
    if hit_difference <= max(1, round(sampled * 0.2)) and score_difference < 0.08:
        return SubtitleRegionDetection(
            "unknown", 0.35, sampled, top_score, bottom_score
        )

    if (top_hits, top_score) > (bottom_hits, bottom_score):
        position = "top"
        winner_hits, winner_score, loser_score = top_hits, top_score, bottom_score
    else:
        position = "bottom"
        winner_hits, winner_score, loser_score = bottom_hits, bottom_score, top_score

    hit_ratio = winner_hits / sampled
    dominance = max(0.0, (winner_score - loser_score) / max(winner_score, 0.001))
    confidence = min(1.0, hit_ratio * 0.65 + dominance * 0.35)
    if confidence < 0.4:
        position = "unknown"
    return SubtitleRegionDetection(
        position,
        round(confidence, 3),
        sampled,
        round(top_score, 4),
        round(bottom_score, 4),
    )


def read_pgm(path: Path) -> EdgeFrame:
    data = path.read_bytes()
    tokens: list[bytes] = []
    index = 0
    while len(tokens) < 4:
        while index < len(data) and data[index] in b" \t\r\n":
            index += 1
        if index < len(data) and data[index] == ord("#"):
            while index < len(data) and data[index] not in b"\r\n":
                index += 1
            continue
        start = index
        while index < len(data) and data[index] not in b" \t\r\n":
            index += 1
        tokens.append(data[start:index])
    if tokens[0] != b"P5" or tokens[3] != b"255":
        raise ValueError(f"Unsupported PGM file: {path}")
    while index < len(data) and data[index] in b" \t\r\n":
        index += 1
    width, height = int(tokens[1]), int(tokens[2])
    pixels = data[index : index + width * height]
    if len(pixels) != width * height:
        raise ValueError(f"Incomplete PGM pixel data: {path}")
    return EdgeFrame(width=width, height=height, pixels=pixels)


def _band_score(frame: EdgeFrame, start_ratio: float, end_ratio: float) -> float:
    if frame.width <= 0 or frame.height <= 0:
        return 0.0
    start_y = max(0, int(frame.height * start_ratio))
    end_y = min(frame.height, max(start_y + 1, int(frame.height * end_ratio)))
    start_x = int(frame.width * 0.05)
    end_x = max(start_x + 1, int(frame.width * 0.95))
    usable_width = end_x - start_x
    row_scores: list[float] = []
    for y in range(start_y, end_y):
        row = frame.pixels[y * frame.width + start_x : y * frame.width + end_x]
        row_scores.append(sum(value >= 180 for value in row) / usable_width)
    window = min(8, len(row_scores))
    if window == 0:
        return 0.0
    return max(
        sum(row_scores[index : index + window]) / window
        for index in range(0, len(row_scores) - window + 1)
    )
