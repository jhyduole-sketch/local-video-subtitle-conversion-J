from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Callable, Protocol

from .process_control import CancelCheck
from .srt import SubtitleSegment


@dataclass(frozen=True)
class OcrAvailability:
    available: bool
    detail: str


@dataclass(frozen=True)
class OcrObservation:
    text: str
    confidence: float
    x: float
    y: float
    width: float
    height: float


@dataclass(frozen=True)
class FrameOcrResult:
    timestamp_ms: int
    observations: tuple[OcrObservation, ...]


class ScreenOcrEngine(Protocol):
    engine_id: str
    label: str

    def availability(self) -> OcrAvailability:
        ...

    def recognize_video(
        self,
        video_path: Path,
        source_lang: str | None,
        *,
        cancel_check: CancelCheck | None = None,
        progress_callback=None,
    ) -> list[SubtitleSegment]:
        ...


ScreenOcrEngineFactory = Callable[[Path], ScreenOcrEngine]
_engine_factories: dict[str, ScreenOcrEngineFactory] = {}


def register_screen_ocr_engine(
    engine_id: str, factory: ScreenOcrEngineFactory
) -> None:
    _engine_factories[engine_id] = factory


def available_screen_ocr_engines(
    cache_root: Path,
) -> list[tuple[ScreenOcrEngine, OcrAvailability]]:
    _register_default_engines()
    return [
        (engine, engine.availability())
        for engine in (factory(cache_root) for factory in _engine_factories.values())
    ]


def get_screen_ocr_engine(
    cache_root: Path, preferred_engine_id: str | None = None
) -> ScreenOcrEngine | None:
    engines = available_screen_ocr_engines(cache_root)
    for engine, availability in engines:
        if preferred_engine_id and engine.engine_id != preferred_engine_id:
            continue
        if availability.available:
            return engine
    return None


def _register_default_engines() -> None:
    if "macos-vision" not in _engine_factories:
        from .macos_vision_ocr import MacVisionOcrEngine

        register_screen_ocr_engine("macos-vision", MacVisionOcrEngine)


def is_suspicious_transcript(segments: list[SubtitleSegment]) -> bool:
    if len(segments) < 8:
        return False

    normalized = [_normalize_text(segment.text) for segment in segments]
    normalized = [text for text in normalized if text]
    if len(normalized) < 8:
        return True

    frequencies = Counter(normalized)
    dominant_ratio = max(frequencies.values()) / len(normalized)
    unique_ratio = len(frequencies) / len(normalized)
    return dominant_ratio >= 0.6 or unique_ratio <= 0.25


def build_ocr_subtitle_segments(
    frames: list[FrameOcrResult],
    *,
    sample_interval_ms: int,
) -> list[SubtitleSegment]:
    if sample_interval_ms <= 0:
        raise ValueError("sample_interval_ms must be positive")

    output: list[SubtitleSegment] = []
    current_text: str | None = None
    current_start_ms = 0
    last_seen_ms = 0
    missing_frames = 0

    def close_current(end_ms: int) -> None:
        nonlocal current_text
        if current_text is None:
            return
        output.append(
            SubtitleSegment(
                index=len(output) + 1,
                start_ms=current_start_ms,
                end_ms=max(current_start_ms + 1, end_ms),
                text=current_text,
            )
        )
        current_text = None

    for frame in sorted(frames, key=lambda item: item.timestamp_ms):
        text = _select_frame_text(frame.observations)
        if not text:
            if current_text is not None:
                missing_frames += 1
                if missing_frames > 1:
                    close_current(last_seen_ms + sample_interval_ms)
                    missing_frames = 0
            continue

        if current_text is None:
            current_text = text
            current_start_ms = frame.timestamp_ms
            last_seen_ms = frame.timestamp_ms
            missing_frames = 0
            continue

        if _texts_match(text, current_text):
            if len(_normalize_text(text)) > len(_normalize_text(current_text)):
                current_text = text
            last_seen_ms = frame.timestamp_ms
            missing_frames = 0
            continue

        close_current(frame.timestamp_ms)
        current_text = text
        current_start_ms = frame.timestamp_ms
        last_seen_ms = frame.timestamp_ms
        missing_frames = 0

    if current_text is not None:
        close_current(last_seen_ms + sample_interval_ms)
    return output


def _select_frame_text(observations: tuple[OcrObservation, ...]) -> str | None:
    candidates: list[tuple[float, str]] = []
    for observation in observations:
        text = " ".join(observation.text.split()).strip()
        center_x = observation.x + observation.width / 2
        if (
            observation.confidence < 0.45
            or len(_normalize_text(text)) < 2
            or not any(character.isalpha() for character in text)
            or not 0.12 <= center_x <= 0.88
            or not 0.04 <= observation.y <= 0.75
            or observation.width < 0.05
            or observation.height < 0.012
        ):
            continue
        center_score = 1 - min(1.0, abs(center_x - 0.5) * 2)
        score = observation.confidence * 2 + observation.width + center_score * 0.25
        candidates.append((score, text))
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


def _normalize_text(text: str) -> str:
    return re.sub(r"[^\w\u3040-\u30ff\u3400-\u9fff]+", "", text).casefold()


def _texts_match(left: str, right: str) -> bool:
    normalized_left = _normalize_text(left)
    normalized_right = _normalize_text(right)
    if normalized_left == normalized_right:
        return True
    shorter = min(len(normalized_left), len(normalized_right))
    if shorter >= 4 and (
        normalized_left in normalized_right or normalized_right in normalized_left
    ):
        return True
    return SequenceMatcher(None, normalized_left, normalized_right).ratio() >= 0.82
