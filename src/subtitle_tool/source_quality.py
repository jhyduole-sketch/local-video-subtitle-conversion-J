"""评估时间轴、文本重复与语言匹配，避免仅凭短句判断质量。
Score timing, repetition, and language compatibility without rejecting captions solely for brevity.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import math
import re
import unicodedata
from typing import Iterable

from .srt import SubtitleSegment


@dataclass(frozen=True)
class SourceQuality:
    score: int
    reasons: list[str]

    def to_dict(self) -> dict[str, object]:
        return {"score": self.score, "reasons": list(self.reasons)}


def score_source_segments(
    segments: Iterable[SubtitleSegment],
    expected_language: str | None,
    ocr_confidence: float | None = None,
) -> SourceQuality:
    values = list(segments)
    if not values:
        return SourceQuality(0, ["没有可用字幕片段"])
    texts = [" ".join(segment.text.split()) for segment in values]
    nonempty = [text for text in texts if text]
    if not nonempty:
        return SourceQuality(0, ["字幕文字为空"])

    # 字幕条数和长度无法区分短视频与低质量识别。
    # Caption count and length do not distinguish a short clip from bad recognition.
    score = 85
    reasons = [f"有效字幕 {len(nonempty)}/{len(values)} 条"]
    empty_ratio = 1 - len(nonempty) / len(values)
    if empty_ratio:
        score -= round(empty_ratio * 65)
        reasons.append(f"空白字幕 {round(empty_ratio * 100)}%")
    invalid = sum(
        not (math.isfinite(s.start_ms) and math.isfinite(s.end_ms)
             and 0 <= s.start_ms < s.end_ms)
        for s in values
    )
    if invalid:
        score -= round(invalid / len(values) * 85)
        reasons.append(f"无效时间轴 {invalid}/{len(values)} 条")
    counts = Counter(_normalized_text(text) for text in nonempty)
    repeated = sum(count for count in counts.values() if count > 1)
    # 两句重复感叹很常见；长篇重复转写才需要怀疑。
    # Two repeated exclamations are common; long repeated transcripts are suspect.
    repeat_ratio = repeated / len(nonempty) if len(nonempty) >= 4 else 0
    if repeat_ratio >= 0.65:
        score -= 60
        reasons.append("重复比例过高")
    elif repeat_ratio >= 0.35:
        score -= 25
        reasons.append("字幕重复较多")
    letters = [c for c in "".join(nonempty) if c.isalpha()]
    ratio = _script_match_ratio(letters, expected_language)
    if ratio is not None and letters:
        if ratio < 0.2:
            score -= 65
            reasons.append(f"文字脚本与 {expected_language} 不匹配")
        elif ratio < 0.5:
            score -= 30
            reasons.append(f"文字脚本与 {expected_language} 匹配较少")
    if not letters and not any(c.isdigit() for t in nonempty for c in t):
        score -= 65
        reasons.append("字幕缺少有效文字")
    if ocr_confidence is not None and math.isfinite(ocr_confidence):
        confidence = max(0.0, min(1.0, ocr_confidence))
        score += round(confidence * 10) - 5
        reasons.append(f"OCR 置信度 {round(confidence * 100)}%")
    return SourceQuality(max(0, min(100, score)), reasons)


def _script_match_ratio(letters: list[str], language: str | None) -> float | None:
    base = (language or "auto").lower().replace("_", "-").split("-")[0]
    scripts = {
        "zh": ("CJK", "IDEOGRAPH"), "zho": ("CJK", "IDEOGRAPH"),
        "ja": ("HIRAGANA", "KATAKANA", "CJK", "IDEOGRAPH"), "jpn": ("HIRAGANA", "KATAKANA", "CJK", "IDEOGRAPH"),
        "ko": ("HANGUL", "CJK"), "kor": ("HANGUL", "CJK"),
        "ru": ("CYRILLIC",), "uk": ("CYRILLIC",), "ar": ("ARABIC",),
        "he": ("HEBREW",), "hi": ("DEVANAGARI",), "th": ("THAI",),
    }
    if base in {"en", "eng", "de", "fr", "es", "it", "pt", "vi", "id", "ms", "nl", "pl", "tr"}:
        expected = ("LATIN",)
    else:
        expected = scripts.get(base)
    if not expected or not letters:
        return None
    return sum(any(script in unicodedata.name(c, "") for script in expected) for c in letters) / len(letters)


def _normalized_text(value: str) -> str:
    return re.sub(r"[\W_]+", "", value, flags=re.UNICODE).lower()
