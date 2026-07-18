from pathlib import Path
import sys
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from subtitle_tool.screen_ocr import (  # noqa: E402
    FrameOcrResult,
    OcrObservation,
    build_ocr_subtitle_segments,
    is_suspicious_transcript,
)
from subtitle_tool.srt import SubtitleSegment  # noqa: E402


def observation(
    text: str,
    *,
    confidence: float = 0.9,
    x: float = 0.2,
    y: float = 0.1,
    width: float = 0.6,
    height: float = 0.08,
) -> OcrObservation:
    return OcrObservation(
        text=text,
        confidence=confidence,
        x=x,
        y=y,
        width=width,
        height=height,
    )


class ScreenOcrQualityTests(unittest.TestCase):
    def test_repeated_whisper_output_is_suspicious(self):
        segments = [
            SubtitleSegment(index, index * 1_000, index * 1_000 + 900, "请上汤。")
            for index in range(1, 30)
        ]

        self.assertTrue(is_suspicious_transcript(segments))

    def test_short_or_varied_transcript_is_not_suspicious(self):
        short_segments = [
            SubtitleSegment(1, 0, 1_000, "hello"),
            SubtitleSegment(2, 1_000, 2_000, "hello"),
        ]
        varied_segments = [
            SubtitleSegment(index, index * 1_000, index * 1_000 + 900, text)
            for index, text in enumerate(
                [
                    "今天很热",
                    "我决定做饭",
                    "先准备食材",
                    "然后开始切菜",
                    "锅里加入清水",
                    "等水烧开",
                    "最后加入调味料",
                    "这道菜就完成了",
                ],
                start=1,
            )
        ]

        self.assertFalse(is_suspicious_transcript(short_segments))
        self.assertFalse(is_suspicious_transcript(varied_segments))


class ScreenOcrTimelineTests(unittest.TestCase):
    def test_extends_exact_text_across_consecutive_frames(self):
        frames = [
            FrameOcrResult(0, (observation("ただでさえ暑いのに"),)),
            FrameOcrResult(500, (observation("ただでさえ暑いのに"),)),
            FrameOcrResult(1_000, (observation("ただでさえ暑いのに"),)),
        ]

        segments = build_ocr_subtitle_segments(frames, sample_interval_ms=500)

        self.assertEqual(
            segments,
            [SubtitleSegment(1, 0, 1_500, "ただでさえ暑いのに")],
        )

    def test_keeps_segment_open_across_one_missing_frame(self):
        frames = [
            FrameOcrResult(0, (observation("料理で発散"),)),
            FrameOcrResult(500, ()),
            FrameOcrResult(1_000, (observation("料理で発散"),)),
        ]

        segments = build_ocr_subtitle_segments(frames, sample_interval_ms=500)

        self.assertEqual(
            segments,
            [SubtitleSegment(1, 0, 1_500, "料理で発散")],
        )

    def test_closes_previous_segment_when_text_changes(self):
        frames = [
            FrameOcrResult(0, (observation("ただでさえ暑いのに"),)),
            FrameOcrResult(500, (observation("ただでさえ暑いのに"),)),
            FrameOcrResult(1_000, (observation("料理で発散"),)),
            FrameOcrResult(1_500, (observation("料理で発散"),)),
        ]

        segments = build_ocr_subtitle_segments(frames, sample_interval_ms=500)

        self.assertEqual(
            segments,
            [
                SubtitleSegment(1, 0, 1_000, "ただでさえ暑いのに"),
                SubtitleSegment(2, 1_000, 2_000, "料理で発散"),
            ],
        )

    def test_merges_small_ocr_variations_and_keeps_more_complete_text(self):
        frames = [
            FrameOcrResult(0, (observation("ルシーなのに食べ応え抜群"),)),
            FrameOcrResult(500, (observation("ヘルシーなのに食べ応え抜群"),)),
            FrameOcrResult(1_000, (observation("ヘルシーなのに食べ応え抜群"),)),
        ]

        segments = build_ocr_subtitle_segments(frames, sample_interval_ms=500)

        self.assertEqual(
            segments,
            [SubtitleSegment(1, 0, 1_500, "ヘルシーなのに食べ応え抜群")],
        )

    def test_ignores_numeric_player_overlay(self):
        frames = [FrameOcrResult(0, (observation("23:30"),))]

        self.assertEqual(
            build_ocr_subtitle_segments(frames, sample_interval_ms=500), []
        )

    def test_ignores_low_confidence_and_edge_watermark_text(self):
        frames = [
            FrameOcrResult(
                0,
                (
                    observation("bilibili", x=0.85, y=0.85, width=0.12),
                    observation("不確かな文字", confidence=0.2),
                    observation("正しい字幕"),
                ),
            )
        ]

        segments = build_ocr_subtitle_segments(frames, sample_interval_ms=500)

        self.assertEqual(segments, [SubtitleSegment(1, 0, 500, "正しい字幕")])


if __name__ == "__main__":
    unittest.main()
