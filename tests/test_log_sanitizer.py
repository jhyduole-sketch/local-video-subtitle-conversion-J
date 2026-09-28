from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from subtitle_tool.log_sanitizer import sanitize_diagnostic_text


class LogSanitizerTests(unittest.TestCase):
    def test_multiple_cookie_values_are_all_hidden(self):
        result = sanitize_diagnostic_text("Cookie: sid=first; session=second; csrf=third\nnext line")
        for secret in ("first", "second", "third"):
            self.assertNotIn(secret, result)
        self.assertIn("next line", result)

    def test_sanitize_hides_secrets_and_home_directory(self):
        text = (
            "Authorization: Bearer abc123 OPENAI_API_KEY=secret "
            "Cookie: sid=one /Users/name/video.mp4?Signature=very-secret"
        )

        result = sanitize_diagnostic_text(text, Path("/Users/name"))

        self.assertNotIn("abc123", result)
        self.assertNotIn("secret", result)
        self.assertNotIn("sid=one", result)
        self.assertIn("~/video.mp4", result)
