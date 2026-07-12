from pathlib import Path
import sys
import unittest
from contextlib import nullcontext
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from subtitle_tool.errors import SubtitleToolError  # noqa: E402
from subtitle_tool.local_translate import (  # noqa: E402
    NLLB_MODEL_NAME,
    NLLB_QUALITY_MODEL_NAME,
    _download_command,
    _is_model_cached,
    _infer_source_lang_from_segments,
    _looks_unreasonably_long,
    _nllb_lang_code,
    local_translation_model_statuses,
    nllb_model_status,
    nllb_model_statuses,
    normalize_lang,
    _resolve_model,
    _repeated_unit,
    _validate_local_translation,
    translate_segments_locally,
    translate_segments_with_nllb,
)
from subtitle_tool.srt import SubtitleSegment  # noqa: E402


class LocalTranslateQualityTests(unittest.TestCase):
    def test_nllb_retries_only_invalid_subtitle_with_safe_options(self):
        class FakeTokenizer:
            src_lang = ""

            def __call__(self, texts, **kwargs):
                return {"input_ids": texts}

            def convert_tokens_to_ids(self, value):
                return 42

            def batch_decode(self, outputs, **kwargs):
                return outputs

        class FakeModel:
            def __init__(self):
                self.calls = []

            def eval(self):
                return None

            def generate(self, input_ids, **kwargs):
                self.calls.append((list(input_ids), kwargs))
                if len(input_ids) == 2:
                    return ["你好。", "，等" * 12]
                return ["等等。"]

        class FakeTorch:
            @staticmethod
            def no_grad():
                return nullcontext()

        model = FakeModel()
        progress = []
        segments = [
            SubtitleSegment(index=20, start_ms=0, end_ms=1000, text="こんにちは。"),
            SubtitleSegment(index=21, start_ms=1000, end_ms=2000, text="え、待って。"),
        ]
        with patch(
            "subtitle_tool.local_translate._load_model",
            return_value=(FakeTokenizer(), model, FakeTorch()),
        ) as load_model:
            translations = translate_segments_with_nllb(
                segments,
                "ja",
                "zh-CN",
                model_name=NLLB_QUALITY_MODEL_NAME,
                progress_callback=progress.append,
            )

        load_model.assert_called_once_with(NLLB_QUALITY_MODEL_NAME)
        self.assertEqual(translations, {20: "你好。", 21: "等等。"})
        self.assertEqual(len(model.calls), 2)
        self.assertEqual(model.calls[1][0], ["え、待って。"])
        self.assertEqual(model.calls[1][1]["no_repeat_ngram_size"], 3)
        self.assertTrue(any("第 21 条" in message for message in progress))
        self.assertTrue(any("重试成功" in message for message in progress))

    def test_local_translation_batches_multiple_segments_per_tokenizer_call(self):
        class FakeTokenizer:
            def __init__(self):
                self.calls = []

            def __call__(self, texts, **kwargs):
                self.calls.append(texts)
                return {"input_ids": texts}

            def decode(self, output, **kwargs):
                return output

            def batch_decode(self, outputs, **kwargs):
                return outputs

        class FakeModel:
            def eval(self):
                return None

            def generate(self, input_ids, **kwargs):
                count = len(input_ids) if isinstance(input_ids, list) else 1
                return ["こんにちは"] * count

        class FakeTorch:
            @staticmethod
            def no_grad():
                return nullcontext()

        tokenizer = FakeTokenizer()
        segments = [
            SubtitleSegment(index=index, start_ms=0, end_ms=1000, text=f"句子 {index}")
            for index in range(1, 4)
        ]

        with patch(
            "subtitle_tool.local_translate._load_model",
            return_value=(tokenizer, FakeModel(), FakeTorch()),
        ):
            translations = translate_segments_locally(segments, "zh", "ja")

        self.assertEqual(len(tokenizer.calls), 1)
        self.assertIsInstance(tokenizer.calls[0], list)
        self.assertEqual(translations, {1: "こんにちは", 2: "こんにちは", 3: "こんにちは"})

    def test_detects_repeated_phrase(self):
        self.assertEqual(_repeated_unit("密かに" * 12), "密かに")

    def test_infers_auto_source_for_local_zh_to_ja(self):
        model_name, prompt_prefix = _resolve_model("auto", "ja")

        self.assertEqual(model_name, "K024/mt5-zh-ja-en-trimmed")
        self.assertEqual(prompt_prefix, "zh2ja: ")

    def test_infers_auto_source_for_local_ja_to_zh(self):
        model_name, prompt_prefix = _resolve_model("auto", "zh-CN")

        self.assertEqual(model_name, "iryneko571/mt5-small-translation-ja_zh")
        self.assertEqual(prompt_prefix, "")

    def test_normalizes_english_language_codes(self):
        self.assertEqual(normalize_lang("en-US"), "en")
        self.assertEqual(normalize_lang("eng"), "en")

    def test_normalizes_common_multilingual_codes(self):
        self.assertEqual(normalize_lang("ko-KR"), "ko")
        self.assertEqual(normalize_lang("fr-FR"), "fr")
        self.assertEqual(normalize_lang("zh-TW"), "zh-TW")

    def test_resolves_local_zh_en_models(self):
        self.assertEqual(_resolve_model("zh", "en"), ("Helsinki-NLP/opus-mt-zh-en", ""))
        self.assertEqual(
            _resolve_model("en", "zh-CN"),
            ("Helsinki-NLP/opus-mt-en-zh", ">>cmn_Hans<< "),
        )

    def test_resolves_local_ja_en_models(self):
        self.assertEqual(_resolve_model("ja", "en"), ("Helsinki-NLP/opus-mt-ja-en", ""))
        self.assertEqual(_resolve_model("en", "ja"), ("Helsinki-NLP/opus-mt-en-jap", ""))

    def test_infers_auto_source_from_subtitle_text_for_english_target(self):
        chinese_segments = [
            SubtitleSegment(index=1, start_ms=0, end_ms=1000, text="我一定会找到你"),
        ]
        japanese_segments = [
            SubtitleSegment(index=1, start_ms=0, end_ms=1000, text="あなたを探しています"),
        ]

        self.assertEqual(_infer_source_lang_from_segments(chinese_segments, "en"), "zh")
        self.assertEqual(_infer_source_lang_from_segments(japanese_segments, "en"), "ja")

    def test_infers_source_from_additional_scripts(self):
        korean_segments = [
            SubtitleSegment(index=1, start_ms=0, end_ms=1000, text="안녕하세요"),
        ]
        russian_segments = [
            SubtitleSegment(index=1, start_ms=0, end_ms=1000, text="Привет"),
        ]

        self.assertEqual(_infer_source_lang_from_segments(korean_segments, "en"), "ko")
        self.assertEqual(_infer_source_lang_from_segments(russian_segments, "en"), "ru")

    def test_nllb_language_codes_cover_common_targets(self):
        self.assertEqual(_nllb_lang_code("zh-CN"), "zho_Hans")
        self.assertEqual(_nllb_lang_code("ja"), "jpn_Jpan")
        self.assertEqual(_nllb_lang_code("en"), "eng_Latn")
        self.assertEqual(_nllb_lang_code("vi"), "vie_Latn")

    def test_nllb_language_code_rejects_unknown_language(self):
        with self.assertRaisesRegex(SubtitleToolError, "does not support"):
            _nllb_lang_code("xx")

    def test_download_command_mentions_requested_model(self):
        command = _download_command("Helsinki-NLP/opus-mt-zh-en")

        self.assertIn("Helsinki-NLP/opus-mt-zh-en", command)
        self.assertIn("AutoModelForSeq2SeqLM", command)

    def test_allows_normal_japanese_translation(self):
        segment = SubtitleSegment(index=1, start_ms=0, end_ms=1000, text="我会找到你")

        _validate_local_translation(segment, "あなたを見つけます", "ja")

    def test_allows_moderately_long_local_translation(self):
        segment = SubtitleSegment(index=1, start_ms=0, end_ms=1000, text="我会找到你")
        translation = "これは字幕として少し長い翻訳ですが、モデルの異常出力ではありません。" * 4

        _validate_local_translation(segment, translation, "ja")

    def test_rejects_repetitive_translation(self):
        segment = SubtitleSegment(index=1, start_ms=0, end_ms=1000, text="我会找到你")

        with self.assertRaisesRegex(SubtitleToolError, "repetitive"):
            _validate_local_translation(segment, "密かに" * 20, "ja")

    def test_rejects_overlong_translation(self):
        segment = SubtitleSegment(index=2, start_ms=0, end_ms=1000, text="你好")

        with self.assertRaisesRegex(SubtitleToolError, "too long"):
            _validate_local_translation(segment, "これはとても長いです" * 80, "ja")

    def test_rejects_unicode_replacement_character(self):
        segment = SubtitleSegment(index=3, start_ms=0, end_ms=1000, text="hello")

        with self.assertRaisesRegex(SubtitleToolError, "invalid characters"):
            _validate_local_translation(segment, "hel\ufffdlo", "en")

    def test_length_guard_only_flags_extreme_outputs(self):
        self.assertFalse(_looks_unreasonably_long("你好", "これは自然な長さです" * 12))
        self.assertTrue(_looks_unreasonably_long("你好", "これは異常に長いです" * 80))

    def test_model_status_reports_download_command(self):
        statuses = local_translation_model_statuses()

        zh_en = next(item for item in statuses if item["model"] == "Helsinki-NLP/opus-mt-zh-en")
        self.assertEqual(zh_en["label"], "中文 -> 英语")
        self.assertIn("python3 -c", str(zh_en["downloadCommand"]))

    def test_nllb_model_status_reports_download_command(self):
        status = nllb_model_status()

        self.assertEqual(status["model"], NLLB_MODEL_NAME)
        self.assertIn(NLLB_MODEL_NAME, str(status["downloadCommand"]))

    def test_nllb_model_statuses_include_fast_and_quality_models(self):
        statuses = nllb_model_statuses()

        self.assertEqual(
            [status["model"] for status in statuses],
            [NLLB_MODEL_NAME, NLLB_QUALITY_MODEL_NAME],
        )

    def test_model_cache_detection_uses_huggingface_layout(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            snapshot = (
                cache
                / "models--Helsinki-NLP--opus-mt-zh-en"
                / "snapshots"
                / "abc123"
            )
            snapshot.mkdir(parents=True)
            (snapshot / "config.json").write_text("{}", encoding="utf-8")
            (snapshot / "model.safetensors").write_text("weights", encoding="utf-8")

            self.assertTrue(_is_model_cached("Helsinki-NLP/opus-mt-zh-en", cache))


if __name__ == "__main__":
    unittest.main()
