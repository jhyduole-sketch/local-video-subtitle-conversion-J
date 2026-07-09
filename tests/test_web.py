from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from subtitle_tool.web import collect_health, options_from_payload  # noqa: E402


class WebTests(unittest.TestCase):
    def test_options_from_payload_uses_local_defaults(self):
        options = options_from_payload(
            {
                "input": "input.mp4",
                "sourceLang": "zh",
                "targetLangs": ["ja", ""],
                "embedSubtitles": True,
            }
        )

        self.assertEqual(options.input_value, "input.mp4")
        self.assertEqual(options.source_lang, "zh")
        self.assertEqual(options.target_langs, ["ja"])
        self.assertEqual(options.transcriber, "local-whisper")
        self.assertEqual(options.translator, "local-transformer")
        self.assertTrue(options.embed_subtitles)

    def test_options_from_payload_accepts_comma_targets(self):
        options = options_from_payload(
            {
                "input": "input.mp4",
                "targetLangs": "zh-CN, ja",
                "downloadOnly": True,
                "translator": "z-ai",
            }
        )

        self.assertEqual(options.target_langs, ["zh-CN", "ja"])
        self.assertEqual(options.translator, "z-ai")
        self.assertTrue(options.download_only)

    def test_collect_health_returns_checks(self):
        health = collect_health(Path.cwd())

        self.assertIn("checks", health)
        self.assertTrue(health["checks"])


if __name__ == "__main__":
    unittest.main()
