from __future__ import annotations

from functools import lru_cache
import os
from pathlib import Path
from typing import Any

from .errors import DependencyError, SubtitleToolError
from .srt import SubtitleSegment


NLLB_MODEL_NAME = "facebook/nllb-200-distilled-600M"
DEFAULT_LOCAL_TRANSLATION_BATCH_SIZE = 8

NLLB_LANG_CODES = {
    "zh": "zho_Hans",
    "zh-CN": "zho_Hans",
    "zh-TW": "zho_Hant",
    "ja": "jpn_Jpan",
    "en": "eng_Latn",
    "ko": "kor_Hang",
    "fr": "fra_Latn",
    "de": "deu_Latn",
    "es": "spa_Latn",
    "pt": "por_Latn",
    "it": "ita_Latn",
    "ru": "rus_Cyrl",
    "ar": "arb_Arab",
    "th": "tha_Thai",
    "vi": "vie_Latn",
    "id": "ind_Latn",
}

LOCAL_TRANSLATION_MODELS = [
    {
        "label": "日语 -> 中文",
        "source": "ja",
        "target": "zh-CN",
        "model": "iryneko571/mt5-small-translation-ja_zh",
        "prefix": "",
    },
    {
        "label": "中文 -> 日语",
        "source": "zh",
        "target": "ja",
        "model": "K024/mt5-zh-ja-en-trimmed",
        "prefix": "zh2ja: ",
    },
    {
        "label": "日语 -> 英语",
        "source": "ja",
        "target": "en",
        "model": "Helsinki-NLP/opus-mt-ja-en",
        "prefix": "",
    },
    {
        "label": "中文 -> 英语",
        "source": "zh",
        "target": "en",
        "model": "Helsinki-NLP/opus-mt-zh-en",
        "prefix": "",
    },
    {
        "label": "英语 -> 中文",
        "source": "en",
        "target": "zh-CN",
        "model": "Helsinki-NLP/opus-mt-en-zh",
        "prefix": ">>cmn_Hans<< ",
    },
    {
        "label": "英语 -> 日语",
        "source": "en",
        "target": "ja",
        "model": "Helsinki-NLP/opus-mt-en-jap",
        "prefix": "",
    },
]

MODEL_BY_PAIR = {
    ("ja", "zh-CN"): ("iryneko571/mt5-small-translation-ja_zh", ""),
    ("ja", "zh"): ("iryneko571/mt5-small-translation-ja_zh", ""),
    ("ja", "en"): ("Helsinki-NLP/opus-mt-ja-en", ""),
    ("zh", "ja"): ("K024/mt5-zh-ja-en-trimmed", "zh2ja: "),
    ("zh-CN", "ja"): ("K024/mt5-zh-ja-en-trimmed", "zh2ja: "),
    ("zh", "en"): ("Helsinki-NLP/opus-mt-zh-en", ""),
    ("zh-CN", "en"): ("Helsinki-NLP/opus-mt-zh-en", ""),
    ("en", "zh-CN"): ("Helsinki-NLP/opus-mt-en-zh", ">>cmn_Hans<< "),
    ("en", "zh"): ("Helsinki-NLP/opus-mt-en-zh", ">>cmn_Hans<< "),
    ("en", "ja"): ("Helsinki-NLP/opus-mt-en-jap", ""),
}


def translate_segments_locally(
    segments: list[SubtitleSegment], source_lang: str | None, target_lang: str
) -> dict[int, str]:
    source = normalize_lang(source_lang)
    target = normalize_lang(target_lang)
    if source == "auto":
        source = _infer_source_lang_from_segments(segments, target)
    model_name, prompt_prefix = _resolve_model(source, target)
    tokenizer, model, torch = _load_model(model_name)

    translations: dict[int, str] = {}
    model.eval()
    with torch.no_grad():
        translations.update(
            _translate_batches(
                segments,
                tokenizer,
                model,
                torch,
                target,
                lambda text: f"{prompt_prefix}{text}",
                {"max_new_tokens": 128, "num_beams": 4},
            )
        )
    return translations


def translate_segments_with_nllb(
    segments: list[SubtitleSegment], source_lang: str | None, target_lang: str
) -> dict[int, str]:
    source = normalize_lang(source_lang)
    target = normalize_lang(target_lang)
    if source == "auto":
        source = _infer_source_lang_from_segments(segments, target)
    source_code = _nllb_lang_code(source)
    target_code = _nllb_lang_code(target)
    tokenizer, model, torch = _load_model(NLLB_MODEL_NAME)

    translations: dict[int, str] = {}
    model.eval()
    tokenizer.src_lang = source_code
    forced_bos_token_id = tokenizer.convert_tokens_to_ids(target_code)
    if forced_bos_token_id is None or forced_bos_token_id < 0:
        raise SubtitleToolError(f"NLLB target language is not available: {target}.")
    with torch.no_grad():
        translations.update(
            _translate_batches(
                segments,
                tokenizer,
                model,
                torch,
                target,
                lambda text: text,
                {
                    "forced_bos_token_id": forced_bos_token_id,
                    "max_new_tokens": 160,
                    "num_beams": 4,
                },
            )
        )
    return translations


def _translate_batches(
    segments: list[SubtitleSegment],
    tokenizer: Any,
    model: Any,
    torch: Any,
    target_lang: str,
    prompt_builder: Any,
    generation_options: dict[str, Any],
) -> dict[int, str]:
    translations: dict[int, str] = {}
    batch_size = _local_translation_batch_size()
    for offset in range(0, len(segments), batch_size):
        batch = segments[offset : offset + batch_size]
        source_texts = [segment.text.replace("\n", " ").strip() for segment in batch]
        prompts = [prompt_builder(text) for text in source_texts]
        inputs = tokenizer(
            prompts,
            return_tensors="pt",
            padding=True,
            truncation=True,
            max_length=256,
        )
        outputs = _generate_local_batch(
            model, inputs, torch, generation_options
        )
        translated_texts = tokenizer.batch_decode(
            outputs, skip_special_tokens=True
        )
        if len(translated_texts) != len(batch):
            raise SubtitleToolError(
                "Local translation returned an unexpected number of subtitles."
            )
        for segment, source_text, translated in zip(
            batch, source_texts, translated_texts
        ):
            translated = translated.strip()
            _validate_local_translation(segment, translated, target_lang)
            translations[segment.index] = translated or source_text
    return translations


def _generate_local_batch(
    model: Any,
    inputs: dict[str, Any],
    torch: Any,
    generation_options: dict[str, Any],
) -> Any:
    requested_device = os.environ.get("LOCAL_TRANSLATION_DEVICE", "cpu").strip().lower()
    if requested_device != "mps":
        return model.generate(**inputs, **generation_options)

    mps_available = bool(
        getattr(getattr(torch, "backends", None), "mps", None)
        and torch.backends.mps.is_available()
    )
    if not mps_available:
        return model.generate(**inputs, **generation_options)

    try:
        model.to("mps")
        device_inputs = {
            name: value.to("mps") if hasattr(value, "to") else value
            for name, value in inputs.items()
        }
        return model.generate(**device_inputs, **generation_options)
    except Exception:
        model.to("cpu")
        return model.generate(**inputs, **generation_options)


def _local_translation_batch_size() -> int:
    value = os.environ.get("LOCAL_TRANSLATION_BATCH_SIZE", "").strip()
    try:
        return max(1, int(value)) if value else DEFAULT_LOCAL_TRANSLATION_BATCH_SIZE
    except ValueError:
        return DEFAULT_LOCAL_TRANSLATION_BATCH_SIZE


def normalize_lang(value: str | None) -> str:
    if not value:
        return "auto"
    lowered = value.lower()
    if lowered in {"zh-cn", "zh_hans", "zh-hans", "cn"}:
        return "zh-CN"
    if lowered in {"zh-tw", "zh_hant", "zh-hant"}:
        return "zh-TW"
    if lowered.startswith("zh"):
        return "zh"
    if lowered.startswith("ja") or lowered.startswith("jp"):
        return "ja"
    if lowered.startswith("en") or lowered == "eng":
        return "en"
    if lowered.startswith("ko"):
        return "ko"
    if lowered.startswith("fr"):
        return "fr"
    if lowered.startswith("de"):
        return "de"
    if lowered.startswith("es"):
        return "es"
    if lowered.startswith("pt"):
        return "pt"
    if lowered.startswith("it"):
        return "it"
    if lowered.startswith("ru"):
        return "ru"
    if lowered.startswith("ar"):
        return "ar"
    if lowered.startswith("th"):
        return "th"
    if lowered.startswith("vi"):
        return "vi"
    if lowered in {"id", "id-id", "ind"}:
        return "id"
    return value


def _resolve_model(source_lang: str, target_lang: str) -> tuple[str, str]:
    if source_lang == "auto":
        source_lang = _infer_local_source_lang(target_lang)
    key = (source_lang, target_lang)
    if key in MODEL_BY_PAIR:
        return MODEL_BY_PAIR[key]
    raise SubtitleToolError(
        f"Local translation does not support {source_lang} -> {target_lang}. "
        "Currently supported: zh/ja/en local translation pairs."
    )


def _infer_local_source_lang(target_lang: str) -> str:
    if target_lang == "ja":
        return "zh"
    if target_lang in {"zh", "zh-CN"}:
        return "ja"
    if target_lang == "en":
        return "zh"
    return "auto"


def _infer_source_lang_from_segments(
    segments: list[SubtitleSegment], target_lang: str
) -> str:
    sample = " ".join(segment.text for segment in segments[:20])
    kana_count = sum(1 for char in sample if "\u3040" <= char <= "\u30ff")
    hangul_count = sum(1 for char in sample if "\uac00" <= char <= "\ud7af")
    cjk_count = sum(1 for char in sample if "\u4e00" <= char <= "\u9fff")
    cyrillic_count = sum(1 for char in sample if "\u0400" <= char <= "\u04ff")
    arabic_count = sum(1 for char in sample if "\u0600" <= char <= "\u06ff")
    thai_count = sum(1 for char in sample if "\u0e00" <= char <= "\u0e7f")
    latin_count = sum(1 for char in sample if "a" <= char.lower() <= "z")

    if kana_count:
        return "ja"
    if hangul_count:
        return "ko"
    if cjk_count:
        return "zh"
    if cyrillic_count:
        return "ru"
    if arabic_count:
        return "ar"
    if thai_count:
        return "th"
    if latin_count:
        return "en"
    return _infer_local_source_lang(target_lang)


def _validate_local_translation(
    segment: SubtitleSegment, translated: str, target_lang: str
) -> None:
    text = translated.strip()
    if not text:
        raise SubtitleToolError(
            f"Local translation produced empty text at subtitle index {segment.index}."
        )

    invalid_control = any(
        ord(character) < 32 and character not in {"\n", "\r", "\t"}
        for character in text
    )
    if "\ufffd" in text or invalid_control:
        raise SubtitleToolError(
            "Local translation output contains invalid characters at subtitle index "
            f"{segment.index}. Try OpenAI or improve the local model."
        )

    source_text = segment.text.replace("\n", " ").strip()
    if _looks_unreasonably_long(source_text, text):
        raise SubtitleToolError(
            "Local translation output looks too long at subtitle index "
            f"{segment.index}. Try z.ai/OpenAI or a better source transcript."
        )

    repeated_unit = _repeated_unit(text)
    if repeated_unit:
        raise SubtitleToolError(
            "Local translation output looks repetitive at subtitle index "
            f"{segment.index}: {repeated_unit!r}. Try z.ai/OpenAI or improve transcription."
        )

    if target_lang == "ja" and _mostly_cjk_without_japanese(text):
        raise SubtitleToolError(
            "Local translation output does not look like Japanese at subtitle index "
            f"{segment.index}. Try z.ai/OpenAI or improve transcription."
        )


def _repeated_unit(text: str) -> str | None:
    compact = "".join(text.split())
    if len(compact) < 12:
        return None
    for unit_size in range(1, min(12, len(compact) // 4) + 1):
        unit = compact[:unit_size]
        if len(set(unit)) == 1 and unit_size > 1:
            continue
        repeat_count = 0
        position = 0
        while compact.startswith(unit, position):
            repeat_count += 1
            position += unit_size
        coverage = position / len(compact)
        if repeat_count >= 5 and coverage >= 0.7:
            return unit
    return None


def _looks_unreasonably_long(source_text: str, translated: str) -> bool:
    if len(translated) <= 240:
        return False
    source_length = max(1, len(source_text))
    return len(translated) > max(360, source_length * 16)


def _mostly_cjk_without_japanese(text: str) -> bool:
    cjk_count = sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
    kana_count = sum(1 for char in text if "\u3040" <= char <= "\u30ff")
    return cjk_count >= 10 and kana_count == 0


def local_translation_model_statuses(
    cache_root: Path | None = None,
) -> list[dict[str, object]]:
    return [
        {
            "label": item["label"],
            "source": item["source"],
            "target": item["target"],
            "model": item["model"],
            "installed": _is_model_cached(str(item["model"]), cache_root),
            "downloadCommand": _download_command(str(item["model"])),
        }
        for item in LOCAL_TRANSLATION_MODELS
    ]


def nllb_model_status(cache_root: Path | None = None) -> dict[str, object]:
    return {
        "label": "NLLB 本地多语言",
        "model": NLLB_MODEL_NAME,
        "installed": _is_model_cached(NLLB_MODEL_NAME, cache_root),
        "downloadCommand": _download_command(NLLB_MODEL_NAME),
    }


def _nllb_lang_code(language: str) -> str:
    normalized = normalize_lang(language)
    if normalized in NLLB_LANG_CODES:
        return NLLB_LANG_CODES[normalized]
    raise SubtitleToolError(
        f"NLLB local translation does not support language: {language}. "
        "Supported common languages: zh-CN, zh-TW, ja, en, ko, fr, de, es, pt, "
        "it, ru, ar, th, vi, id."
    )


def _is_model_cached(model_name: str, cache_root: Path | None = None) -> bool:
    root = cache_root or Path.home() / ".cache" / "huggingface" / "hub"
    model_dir = root / f"models--{model_name.replace('/', '--')}"
    snapshots_dir = model_dir / "snapshots"
    if not snapshots_dir.exists():
        return False
    required_files = {"config.json"}
    weight_suffixes = (".safetensors", ".bin")
    for snapshot in snapshots_dir.iterdir():
        if not snapshot.is_dir():
            continue
        filenames = {path.name for path in snapshot.iterdir() if path.is_file()}
        has_config = required_files.issubset(filenames)
        has_weights = any(path.name.endswith(weight_suffixes) for path in snapshot.iterdir())
        if has_config and has_weights:
            return True
    return False


@lru_cache(maxsize=6)
def _load_model(model_name: str) -> tuple[Any, Any, Any]:
    try:
        import torch
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
    except ImportError as exc:
        raise DependencyError(
            "Local translation dependencies are missing. Install transformers, torch, and sentencepiece."
        ) from exc

    try:
        tokenizer = AutoTokenizer.from_pretrained(
            model_name, use_fast=False, local_files_only=True
        )
        model = AutoModelForSeq2SeqLM.from_pretrained(model_name, local_files_only=True)
    except Exception as exc:
        raise DependencyError(
            f"Local translation model is not cached: {model_name}. "
            f"Download it before running offline: {_download_command(model_name)}"
        ) from exc
    return tokenizer, model, torch


def _download_command(model_name: str) -> str:
    return (
        "python3 -c \"from transformers import AutoTokenizer, "
        "AutoModelForSeq2SeqLM; "
        f"AutoTokenizer.from_pretrained('{model_name}', use_fast=False); "
        f"AutoModelForSeq2SeqLM.from_pretrained('{model_name}')\""
    )
