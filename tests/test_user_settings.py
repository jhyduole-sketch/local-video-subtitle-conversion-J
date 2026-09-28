from pathlib import Path
from tempfile import TemporaryDirectory
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from subtitle_tool.user_settings import load_user_settings, save_user_settings


class UserSettingsTests(unittest.TestCase):
    def test_settings_persist_safe_defaults_and_drop_secrets(self):
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "settings.json"
            saved = save_user_settings(
                {"outputDir": "results", "cacheLimitGb": 4, "openaiApiKey": "secret"},
                path,
            )
            loaded = load_user_settings(path)

        self.assertEqual(saved["outputDir"], "results")
        self.assertEqual(loaded["cacheLimitGb"], 4)
        self.assertNotIn("openaiApiKey", loaded)


    def test_string_false_is_not_enabled(self):
        with TemporaryDirectory() as tmpdir:
            saved = save_user_settings({"whisperUseGpu": "false"}, Path(tmpdir) / "settings.json")
        self.assertIs(saved["whisperUseGpu"], False)

    def test_invalid_settings_are_rejected_without_overwriting(self):
        cases = [("whisperUseVad", "sometimes"), ("whisperUseGpu", []),
                 ("subtitleVideoMode", "broken"), ("subtitlePosition", "middle"),
                 ("subtitleEncodingProfile", "slow"), ("outputDir", None),
                 ("whisperModel", ["model"]), ("outputDir", "a\x00b"),
                 ("outputDir", " "), ("cacheLimitGb", 0), ("cacheLimitGb", 501),
                 ("cacheLimitGb", 1.5), ("cacheLimitGb", True)]
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "settings.json"
            save_user_settings({}, path)
            before = path.read_bytes()
            for key, value in cases:
                with self.subTest(key=key, value=value):
                    with self.assertRaisesRegex(ValueError, key):
                        save_user_settings({key: value}, path)
                    self.assertEqual(path.read_bytes(), before)

    def test_public_validation_helpers_match_saved_settings(self):
        from subtitle_tool.user_settings import parse_boolean, validate_setting_values
        self.assertFalse(parse_boolean("false", "enabled"))
        with self.assertRaisesRegex(ValueError, "enabled"):
            parse_boolean(1, "enabled")
        self.assertEqual(validate_setting_values({"subtitlePosition": "top", "apiKey": "secret"}), {"subtitlePosition": "top"})

    def test_invalid_saved_fields_recover_without_losing_valid_preferences(self):
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "settings.json"
            path.write_text('{"outputDir":"my-output","whisperUseGpu":"broken","cacheLimitGb":-9}')
            loaded = load_user_settings(path)
            self.assertEqual(loaded["outputDir"], "my-output")
            self.assertIs(loaded["whisperUseGpu"], True)
            self.assertEqual(loaded["cacheLimitGb"], 10)
            path.write_bytes(b"\xff")
            self.assertEqual(load_user_settings(path)["outputDir"], "output")
