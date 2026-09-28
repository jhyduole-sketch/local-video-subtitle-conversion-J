from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from subtitle_tool.download_capabilities import classify_download_error


class DownloadCapabilityTests(unittest.TestCase):
    def test_drm_error_is_explicitly_classified(self):
        result = classify_download_error("ERROR: This video is DRM protected")

        self.assertEqual(result.kind, "drm")
        self.assertIn("DRM", result.user_message)

    def test_login_error_explains_cookie_is_user_supplied(self):
        result = classify_download_error("Sign in to confirm you're not a bot")

        self.assertEqual(result.kind, "login")
        self.assertIn("登录", result.user_message)
        self.assertIn("Cookie", result.user_message)
