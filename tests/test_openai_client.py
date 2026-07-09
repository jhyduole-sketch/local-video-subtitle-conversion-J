from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from subtitle_tool.openai_client import _parse_translation_json  # noqa: E402
from subtitle_tool.srt import SubtitleSegment  # noqa: E402


class OpenAIClientTests(unittest.TestCase):
    def test_parse_translation_json_returns_indexed_text(self):
        segments = [
            SubtitleSegment(index=1, start_ms=0, end_ms=1000, text="你好"),
            SubtitleSegment(index=2, start_ms=1000, end_ms=2000, text="世界"),
        ]

        translations = _parse_translation_json(
            '{"items":[{"index":1,"text":"こんにちは"},{"index":2,"text":"世界"}]}',
            "ja",
            segments,
            "z.ai",
        )

        self.assertEqual(translations, {1: "こんにちは", 2: "世界"})


if __name__ == "__main__":
    unittest.main()
