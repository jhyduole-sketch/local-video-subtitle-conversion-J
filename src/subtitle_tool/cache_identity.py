"""为处理配置生成缓存身份，不保存密钥。 Build cache identities without persisting API keys."""
from __future__ import annotations

import os
from pathlib import Path

from .openai_client import (
    DEFAULT_TRANSLATE_MODEL, DEFAULT_TRANSCRIBE_MODEL,
    DEFAULT_ZAI_BASE_URL, DEFAULT_ZAI_TRANSLATE_MODEL,
)
from .local_whisper import DEFAULT_MODEL_PATH
from .translation_engines import canonical_translator_id, NLLB_MODEL_NAME

# 修改提示词、推理参数或回退策略时递增版本。
# Bump when prompts, inference parameters or fallback policies change.
TRANSLATION_REVISION = 2
TRANSCRIPTION_REVISION = 2


def model_file_identity(path: Path) -> dict[str, object]:
    resolved = path.expanduser().resolve()
    try:
        info = resolved.stat()
    except FileNotFoundError:
        return {"path": str(resolved), "missing": True}
    # ctime 和 inode 可识别保留大小/mtime 的常见替换，无需每次读取大型模型。
    # ctime and inode detect ordinary size/mtime-preserving replacements without rereading large models.
    return {"path": str(resolved), "size": info.st_size, "mtime": info.st_mtime_ns,
            "ctime": info.st_ctime_ns, "inode": info.st_ino}


def translation_identity(provider: str) -> dict[str, object]:
    from .local_translate import MODEL_BY_PAIR
    provider = canonical_translator_id(provider)
    value: dict[str, object] = {"revision": TRANSLATION_REVISION, "provider": provider}
    if provider == "openai":
        value.update(model=os.environ.get("SUBTITLE_TOOL_TRANSLATE_MODEL", DEFAULT_TRANSLATE_MODEL),
                     endpoint=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"))
    else:
        # 非 OpenAI 策略可能回退到 z.ai/NLLB；同时记录这些有效配置。
        # Non-OpenAI strategies can fall back to z.ai/NLLB; identify their effective configuration too.
        value.update(model=os.environ.get("ZAI_MODEL", DEFAULT_ZAI_TRANSLATE_MODEL),
                     endpoint=os.environ.get("ZAI_API_BASE", DEFAULT_ZAI_BASE_URL),
                     nllb=NLLB_MODEL_NAME,
                     local_models=sorted((list(pair), list(model)) for pair, model in MODEL_BY_PAIR.items()))
    return value


def transcription_identity(transcriber: str, model: Path | None, profile: str | None) -> dict[str, object]:
    value: dict[str, object] = {"revision": TRANSCRIPTION_REVISION}
    if transcriber == "local-whisper":
        value["model"] = model_file_identity(model or DEFAULT_MODEL_PATH)
        if profile and profile.startswith("vad:"):
            value["vad"] = model_file_identity(Path(profile[4:]))
    else:
        value.update(model=os.environ.get("SUBTITLE_TOOL_TRANSCRIBE_MODEL", DEFAULT_TRANSCRIBE_MODEL),
                     endpoint=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"))
    return value
