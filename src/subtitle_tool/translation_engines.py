from __future__ import annotations


NLLB_MODEL_NAME = "facebook/nllb-200-distilled-1.3B"
NLLB_TRANSLATOR_ID = "local-nllb-quality"

TRANSLATOR_IDS = (
    "openai",
    "z-ai",
    "local-transformer",
    "local-nllb",
    NLLB_TRANSLATOR_ID,
)

_ALIASES = {
    "local-nllb": NLLB_TRANSLATOR_ID,
}

_LABELS = {
    "openai": "OpenAI",
    "z-ai": "z.ai",
    "local-transformer": "本地快速模型",
    NLLB_TRANSLATOR_ID: "本地 NLLB 1.3B",
}


def canonical_translator_id(value: str) -> str:
    return _ALIASES.get(value, value)


def translation_cache_provider(value: str) -> str:
    return canonical_translator_id(value)


def translator_label(value: str) -> str:
    canonical = canonical_translator_id(value)
    return _LABELS.get(canonical, value)
