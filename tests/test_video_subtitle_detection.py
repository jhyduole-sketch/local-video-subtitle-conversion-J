from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from subtitle_tool.video_subtitle_detection import (  # noqa: E402
    EdgeFrame,
    classify_band_scores,
    detect_subtitle_region_from_frames,
    read_pgm,
)


def edge_frame(region: str | None, width: int = 120, height: int = 80) -> EdgeFrame:
    pixels = bytearray(width * height)
    if region:
        start = 8 if region == "top" else 58
        for y in range(start, start + 8):
            for x in range(10, width - 10):
                if (x + y) % 3 != 0:
                    pixels[y * width + x] = 255
    return EdgeFrame(width=width, height=height, pixels=bytes(pixels))


class VideoSubtitleDetectionTests(unittest.TestCase):
    def test_detects_repeated_bottom_subtitle_edges(self):
        result = detect_subtitle_region_from_frames(
            [edge_frame("bottom") for _ in range(6)]
        )

        self.assertEqual(result.position, "bottom")
        self.assertGreaterEqual(result.confidence, 0.7)
        self.assertEqual(result.sampled_frames, 6)

    def test_detects_repeated_top_subtitle_edges(self):
        result = detect_subtitle_region_from_frames(
            [edge_frame("top") for _ in range(5)]
        )

        self.assertEqual(result.position, "top")
        self.assertGreaterEqual(result.confidence, 0.7)

    def test_reports_none_for_frames_without_text_edges(self):
        result = detect_subtitle_region_from_frames([edge_frame(None) for _ in range(4)])

        self.assertEqual(result.position, "none")
        self.assertGreaterEqual(result.confidence, 0.5)

    def test_reports_unknown_when_top_and_bottom_are_equally_likely(self):
        frames = [edge_frame("top") for _ in range(3)] + [
            edge_frame("bottom") for _ in range(3)
        ]

        result = detect_subtitle_region_from_frames(frames)

        self.assertEqual(result.position, "unknown")

    def test_reads_binary_pgm(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "frame.pgm"
            path.write_bytes(b"P5\n# generated\n3 2\n255\n" + bytes([0, 1, 2, 3, 4, 5]))
            frame = read_pgm(path)

        self.assertEqual((frame.width, frame.height), (3, 2))
        self.assertEqual(frame.pixels, bytes([0, 1, 2, 3, 4, 5]))

    def test_classifies_realistic_sparse_bottom_subtitle_hits(self):
        top_scores = [0.033, 0.026, 0.026, 0.026, 0.026, 0.027, 0.038, 0.026]
        bottom_scores = [0.122, 0.005, 0.052, 0.1, 0.0, 0.015, 0.087, 0.006]

        result = classify_band_scores(top_scores, bottom_scores)

        self.assertEqual(result.position, "bottom")
        self.assertGreaterEqual(result.confidence, 0.4)


if __name__ == "__main__":
    unittest.main()
