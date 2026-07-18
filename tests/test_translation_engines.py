from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from subtitle_tool.translation_engines import (  # noqa: E402
    NLLB_MODEL_NAME,
    TRANSLATOR_IDS,
    canonical_translator_id,
    translation_cache_provider,
    translator_label,
)


class TranslationEngineTests(unittest.TestCase):
    def test_legacy_nllb_alias_uses_quality_engine(self):
        self.assertEqual(canonical_translator_id("local-nllb"), "local-nllb-quality")
        self.assertEqual(
            translation_cache_provider("local-nllb"),
            translation_cache_provider("local-nllb-quality"),
        )

    def test_nllb_catalog_only_points_to_1_3b(self):
        self.assertEqual(NLLB_MODEL_NAME, "facebook/nllb-200-distilled-1.3B")
        self.assertEqual(translator_label("local-nllb"), "本地 NLLB 1.3B")
        self.assertEqual(translator_label("local-nllb-quality"), "本地 NLLB 1.3B")

    def test_translator_ids_keep_legacy_cli_compatibility(self):
        self.assertIn("local-nllb", TRANSLATOR_IDS)
        self.assertIn("local-nllb-quality", TRANSLATOR_IDS)


if __name__ == "__main__":
    unittest.main()
