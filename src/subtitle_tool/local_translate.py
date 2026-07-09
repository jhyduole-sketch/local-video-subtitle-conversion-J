from __future__ import annotations

from functools import lru_cache
from typing import Any

from .errors import DependencyError, SubtitleToolError
from .srt import SubtitleSegment


MODEL_BY_PAIR = {
    ("ja", "zh-CN"): ("iryneko571/mt5-small-translation-ja_zh", ""),
    ("ja", "zh"): ("iryneko571/mt5-small-translation-ja_zh", ""),
    ("zh", "ja"): ("K024/mt5-zh-ja-en-trimmed", "zh2ja: "),
    ("zh-CN", "ja"): ("K024/mt5-zh-ja-en-trimmed", "zh2ja: "),
}


def translate_segments_locally(
    segments: list[SubtitleSegment], source_lang: str | None, target_lang: str
) -> dict[int, str]:
    source = normalize_lang(source_lang)
    target = normalize_lang(target_lang)
    model_name, prompt_prefix = _resolve_model(source, target)
    tokenizer, model, torch = _load_model(model_name)

    translations: dict[int, str] = {}
    model.eval()
    with torch.no_grad():
        for segment in segments:
            text = segment.text.replace("\n", " ").strip()
            prompt = f"{prompt_prefix}{text}"
            inputs = tokenizer(prompt, return_tensors="pt", truncation=True, max_length=256)
            outputs = model.generate(**inputs, max_new_tokens=128, num_beams=4)
            translated = tokenizer.decode(outputs[0], skip_special_tokens=True).strip()
            translations[segment.index] = translated or text
    return translations


def normalize_lang(value: str | None) -> str:
    if not value:
        return "auto"
    lowered = value.lower()
    if lowered in {"zh-cn", "zh_hans", "zh-hans", "cn"}:
        return "zh-CN"
    if lowered.startswith("zh"):
        return "zh"
    if lowered.startswith("ja") or lowered.startswith("jp"):
        return "ja"
    return value


def _resolve_model(source_lang: str, target_lang: str) -> tuple[str, str]:
    key = (source_lang, target_lang)
    if key in MODEL_BY_PAIR:
        return MODEL_BY_PAIR[key]
    raise SubtitleToolError(
        f"Local translation does not support {source_lang} -> {target_lang}. "
        "Currently supported: ja -> zh-CN and zh-CN/zh -> ja."
    )


@lru_cache(maxsize=2)
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
            f"Local translation model is not cached: {model_name}. Download it before running offline."
        ) from exc
    return tokenizer, model, torch

