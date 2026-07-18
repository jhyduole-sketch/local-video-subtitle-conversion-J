from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from subtitle_tool.health import collect_health  # noqa: E402
from subtitle_tool.screen_ocr import OcrAvailability  # noqa: E402
from subtitle_tool.web import collect_health as web_collect_health  # noqa: E402


class HealthTests(unittest.TestCase):
    def test_web_reexports_health_collector(self):
        self.assertIs(web_collect_health, collect_health)

    def test_health_includes_optional_screen_ocr_engine(self):
        engine = Mock(engine_id="macos-vision", label="macOS Vision")
        with patch(
            "subtitle_tool.health.available_screen_ocr_engines",
            return_value=[(engine, OcrAvailability(True, "可用"))],
        ):
            health = collect_health(Path.cwd())

        matching = [
            check for check in health["checks"] if check["name"] == "画面字幕 OCR"
        ]
        self.assertEqual(len(matching), 1)
        self.assertTrue(matching[0]["ok"])
        self.assertTrue(matching[0]["optional"])
        self.assertIn("macOS Vision", matching[0]["detail"])


if __name__ == "__main__":
    unittest.main()
