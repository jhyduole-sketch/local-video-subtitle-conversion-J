from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable

from .errors import OpenAIConfigError, ProviderRateLimitError, SubtitleToolError
from .srt import SubtitleSegment


DEFAULT_TRANSCRIBE_MODEL = "whisper-1"
DEFAULT_TRANSLATE_MODEL = "gpt-4.1-mini"
DEFAULT_ZAI_BASE_URL = "https://open.bigmodel.cn/api/paas/v4/"
DEFAULT_ZAI_TRANSLATE_MODEL = "glm-4.7-flash"
DEFAULT_ZAI_TRANSLATION_BATCH_SEGMENTS = 24
DEFAULT_ZAI_TRANSLATION_BATCH_CHARACTERS = 4000
ZAI_TRANSLATION_RETRY_LIMIT = 2
DEFAULT_API_TIMEOUT_SECONDS = 60.0
DEFAULT_ZAI_REQUEST_DELAY_SECONDS = 2.0
DEFAULT_ZAI_RATE_LIMIT_RETRY_SECONDS = 20.0
DEFAULT_ZAI_RATE_LIMIT_RETRY_LIMIT = 3
ProgressCallback = Callable[[str], None]
_ZAI_REQUEST_LOCK = threading.Lock()


def build_client() -> Any:
    if not os.environ.get("OPENAI_API_KEY"):
        raise OpenAIConfigError(
            "OPENAI_API_KEY is not set. Export it or add it to a .env file in this project."
        )

    try:
        from openai import OpenAI
    except ImportError as exc:
        raise OpenAIConfigError(
            "The OpenAI Python package is not installed. Run: pip install -e ."
        ) from exc

    return OpenAI(timeout=_api_timeout_seconds("OPENAI_TIMEOUT_SECONDS"))


def build_zai_client() -> Any:
    if not os.environ.get("ZAI_API_KEY"):
        raise OpenAIConfigError(
            "ZAI_API_KEY is not set. Export it or add it to a .env file in this project."
        )

    try:
        from openai import OpenAI
    except ImportError as exc:
        raise OpenAIConfigError(
            "The OpenAI Python package is not installed. Run: pip install -e ."
        ) from exc

    return OpenAI(
        api_key=os.environ["ZAI_API_KEY"],
        base_url=os.environ.get("ZAI_API_BASE", DEFAULT_ZAI_BASE_URL),
        timeout=_api_timeout_seconds("ZAI_TIMEOUT_SECONDS"),
    )


def transcribe_audio(
    audio_path: Path, source_lang: str | None = None, model: str | None = None
) -> list[SubtitleSegment]:
    client = build_client()
    transcription_model = model or os.environ.get(
        "SUBTITLE_TOOL_TRANSCRIBE_MODEL", DEFAULT_TRANSCRIBE_MODEL
    )

    kwargs: dict[str, Any] = {
        "model": transcription_model,
        "file": audio_path.open("rb"),
        "response_format": "verbose_json",
        "timestamp_granularities": ["segment"],
    }
    if source_lang:
        kwargs["language"] = source_lang

    try:
        response = client.audio.transcriptions.create(**kwargs)
    except Exception as exc:
        raise SubtitleToolError(f"OpenAI transcription failed: {exc}") from exc
    finally:
        kwargs["file"].close()

    raw_segments = _get_response_field(response, "segments") or []
    segments: list[SubtitleSegment] = []
    for index, item in enumerate(raw_segments, start=1):
        start = float(_get_mapping_field(item, "start", 0))
        end = float(_get_mapping_field(item, "end", start))
        text = str(_get_mapping_field(item, "text", "")).strip()
        if not text:
            continue
        segments.append(
            SubtitleSegment(
                index=index,
                start_ms=round(start * 1000),
                end_ms=round(end * 1000),
                text=text,
            )
        )

    if not segments:
        text = str(_get_response_field(response, "text") or "").strip()
        if text:
            segments.append(SubtitleSegment(index=1, start_ms=0, end_ms=3000, text=text))

    if not segments:
        raise SubtitleToolError("OpenAI transcription returned no subtitle segments.")

    return segments


def translate_segments(
    segments: list[SubtitleSegment],
    target_lang: str,
    source_lang: str | None = None,
    model: str | None = None,
) -> dict[int, str]:
    client = build_client()
    translate_model = model or os.environ.get(
        "SUBTITLE_TOOL_TRANSLATE_MODEL", DEFAULT_TRANSLATE_MODEL
    )
    payload = {
        "source_language": source_lang or "auto",
        "target_language": target_lang,
        "subtitles": [
            {"index": segment.index, "text": segment.text} for segment in segments
        ],
    }

    system_prompt = (
        "Translate subtitle text for video subtitles. Preserve meaning, tone, names, "
        "numbers, and line breaks where helpful. Return exactly one translated item "
        "for every input index. Do not add commentary."
    )
    user_prompt = json.dumps(payload, ensure_ascii=False)
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "index": {"type": "integer"},
                        "text": {"type": "string"},
                    },
                    "required": ["index", "text"],
                },
            }
        },
        "required": ["items"],
    }

    try:
        content = _responses_json(client, translate_model, system_prompt, user_prompt, schema)
    except AttributeError:
        content = _chat_json(client, translate_model, system_prompt, user_prompt, schema)
    except Exception as exc:
        raise SubtitleToolError(f"OpenAI translation to {target_lang} failed: {exc}") from exc

    return _parse_translation_json(content, target_lang, segments, "OpenAI")


def translate_segments_with_zai(
    segments: list[SubtitleSegment],
    target_lang: str,
    source_lang: str | None = None,
    model: str | None = None,
    progress_callback: ProgressCallback | None = None,
) -> dict[int, str]:
    client = build_zai_client()
    translate_model = model or os.environ.get(
        "ZAI_MODEL", DEFAULT_ZAI_TRANSLATE_MODEL
    )
    return _translate_segments_with_zai_batches(
        client,
        translate_model,
        segments,
        target_lang,
        source_lang,
        progress_callback,
    )


def _translate_segments_with_zai_batches(
    client: Any,
    translate_model: str,
    segments: list[SubtitleSegment],
    target_lang: str,
    source_lang: str | None = None,
    progress_callback: ProgressCallback | None = None,
) -> dict[int, str]:
    translations: dict[int, str] = {}
    max_segments = _int_env(
        "ZAI_TRANSLATION_BATCH_SEGMENTS",
        DEFAULT_ZAI_TRANSLATION_BATCH_SEGMENTS,
        minimum=1,
    )
    max_characters = _int_env(
        "ZAI_TRANSLATION_BATCH_CHARACTERS",
        DEFAULT_ZAI_TRANSLATION_BATCH_CHARACTERS,
        minimum=1,
    )
    batches = _chunk_segments_by_budget(segments, max_segments, max_characters)
    for batch_index, batch in enumerate(batches, start=1):
        if batch_index > 1:
            _sleep_between_zai_requests(progress_callback)
        if progress_callback:
            progress_callback(
                f"z.ai 翻译 {target_lang}: 第 {batch_index}/{len(batches)} 批"
            )
        translations.update(
            _translate_zai_batch(
                client,
                translate_model,
                batch,
                target_lang,
                source_lang,
                progress_callback,
            )
        )

    for retry_index in range(1, ZAI_TRANSLATION_RETRY_LIMIT + 1):
        missing_segments = [
            segment for segment in segments if segment.index not in translations
        ]
        if not missing_segments:
            break
        if progress_callback:
            missing_preview = ", ".join(
                str(segment.index) for segment in missing_segments[:10]
            )
            progress_callback(
                f"z.ai 补翻 {target_lang}: 第 {retry_index} 次，缺失 {missing_preview}"
            )
        for batch in _chunk_segments_by_budget(
            missing_segments,
            max(1, max_segments // 2),
            max(1, max_characters // 2),
        ):
            _sleep_between_zai_requests(progress_callback)
            translations.update(
                _translate_zai_batch(
                    client,
                    translate_model,
                    batch,
                    target_lang,
                    source_lang,
                    progress_callback,
                )
            )

    _raise_if_missing(translations, target_lang, segments, "z.ai")
    return translations


def _translate_zai_batch(
    client: Any,
    translate_model: str,
    segments: list[SubtitleSegment],
    target_lang: str,
    source_lang: str | None = None,
    progress_callback: ProgressCallback | None = None,
) -> dict[int, str]:
    payload = {
        "source_language": source_lang or "auto",
        "target_language": target_lang,
        "subtitles": [
            {"index": segment.index, "text": segment.text} for segment in segments
        ],
    }
    system_prompt = (
        "Translate subtitle text for video subtitles. Preserve meaning, tone, names, "
        "numbers, and line breaks where helpful. Return valid JSON only, in the shape "
        '{"items":[{"index":1,"text":"..."}]}. Return exactly one translated item '
        "for every input index. Do not add commentary."
    )
    user_prompt = json.dumps(payload, ensure_ascii=False)

    with _ZAI_REQUEST_LOCK:
        content = _chat_json_object_with_rate_limit_retry(
            client,
            translate_model,
            system_prompt,
            user_prompt,
            target_lang,
            progress_callback,
        )

    translations = _parse_translation_items(content, target_lang, "z.ai")
    requested_indexes = {segment.index for segment in segments}
    return {
        index: text
        for index, text in translations.items()
        if index in requested_indexes
    }


def _responses_json(
    client: Any, model: str, system_prompt: str, user_prompt: str, schema: dict[str, Any]
) -> str:
    response = client.responses.create(
        model=model,
        input=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": "subtitle_translation",
                "strict": True,
                "schema": schema,
            }
        },
    )
    output_text = getattr(response, "output_text", None)
    if output_text:
        return output_text
    return json.dumps(response.model_dump(), ensure_ascii=False)


def _chat_json(
    client: Any, model: str, system_prompt: str, user_prompt: str, schema: dict[str, Any]
) -> str:
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "subtitle_translation",
                "strict": True,
                "schema": schema,
            },
        },
    )
    return response.choices[0].message.content or "{}"


def _chat_json_object(
    client: Any, model: str, system_prompt: str, user_prompt: str
) -> str:
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"},
    )
    return response.choices[0].message.content or "{}"


def _chat_json_object_with_rate_limit_retry(
    client: Any,
    model: str,
    system_prompt: str,
    user_prompt: str,
    target_lang: str,
    progress_callback: ProgressCallback | None = None,
) -> str:
    retry_limit = _int_env(
        "ZAI_RATE_LIMIT_RETRY_LIMIT", DEFAULT_ZAI_RATE_LIMIT_RETRY_LIMIT, minimum=0
    )
    for attempt in range(retry_limit + 1):
        try:
            return _chat_json_object(client, model, system_prompt, user_prompt)
        except Exception as exc:
            is_rate_limit = _is_rate_limit_error(exc)
            if not is_rate_limit:
                raise SubtitleToolError(
                    f"z.ai translation to {target_lang} failed: {exc}"
                ) from exc
            if attempt >= retry_limit:
                raise ProviderRateLimitError(
                    "z.ai",
                    f"z.ai translation to {target_lang} failed after "
                    f"{retry_limit} rate-limit retries: {exc}",
                ) from exc
            delay = _zai_rate_limit_retry_seconds(attempt)
            if progress_callback:
                progress_callback(
                    f"z.ai 触发限流，等待 {delay:g} 秒后重试 "
                    f"({attempt + 1}/{retry_limit})"
                )
            time.sleep(delay)

    raise SubtitleToolError(f"z.ai translation to {target_lang} failed after retries.")


def _parse_translation_json(
    content: str,
    target_lang: str,
    segments: list[SubtitleSegment],
    provider_name: str,
) -> dict[int, str]:
    translations = _parse_translation_items(content, target_lang, provider_name)
    _raise_if_missing(translations, target_lang, segments, provider_name)
    return translations


def _parse_translation_items(
    content: str,
    target_lang: str,
    provider_name: str,
) -> dict[int, str]:
    try:
        parsed = json.loads(content)
        items = parsed["items"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise SubtitleToolError(
            f"{provider_name} translation to {target_lang} returned invalid JSON."
        ) from exc

    translations: dict[int, str] = {}
    for item in items:
        try:
            index = int(item["index"])
            text = str(item["text"]).strip()
        except (KeyError, TypeError, ValueError):
            continue
        if text:
            translations[index] = text

    return translations


def _raise_if_missing(
    translations: dict[int, str],
    target_lang: str,
    segments: list[SubtitleSegment],
    provider_name: str,
) -> None:
    missing = {segment.index for segment in segments} - set(translations)
    if missing:
        missing_list = ", ".join(str(value) for value in sorted(missing)[:10])
        raise SubtitleToolError(
            f"{provider_name} translation to {target_lang} missed subtitle indexes: {missing_list}"
        )

def _chunk_segments(
    segments: list[SubtitleSegment],
    size: int,
) -> list[list[SubtitleSegment]]:
    return [segments[index : index + size] for index in range(0, len(segments), size)]


def _chunk_segments_by_budget(
    segments: list[SubtitleSegment],
    max_segments: int,
    max_characters: int,
) -> list[list[SubtitleSegment]]:
    batches: list[list[SubtitleSegment]] = []
    current: list[SubtitleSegment] = []
    current_characters = 0
    for segment in segments:
        segment_characters = len(segment.text)
        exceeds_count = len(current) >= max_segments
        exceeds_characters = (
            bool(current) and current_characters + segment_characters > max_characters
        )
        if exceeds_count or exceeds_characters:
            batches.append(current)
            current = []
            current_characters = 0
        current.append(segment)
        current_characters += segment_characters
    if current:
        batches.append(current)
    return batches


def _api_timeout_seconds(env_name: str) -> float:
    value = os.environ.get(env_name, "").strip()
    if not value:
        return DEFAULT_API_TIMEOUT_SECONDS
    try:
        return max(1.0, float(value))
    except ValueError:
        return DEFAULT_API_TIMEOUT_SECONDS


def _sleep_between_zai_requests(progress_callback: ProgressCallback | None = None) -> None:
    delay = _float_env(
        "ZAI_REQUEST_DELAY_SECONDS", DEFAULT_ZAI_REQUEST_DELAY_SECONDS, minimum=0.0
    )
    if delay <= 0:
        return
    if progress_callback:
        progress_callback(f"z.ai 控制请求频率，等待 {delay:g} 秒")
    time.sleep(delay)


def _zai_rate_limit_retry_seconds(attempt: int) -> float:
    base_delay = _float_env(
        "ZAI_RATE_LIMIT_RETRY_SECONDS",
        DEFAULT_ZAI_RATE_LIMIT_RETRY_SECONDS,
        minimum=1.0,
    )
    return base_delay * (attempt + 1)


def _is_rate_limit_error(exc: Exception) -> bool:
    status_code = getattr(exc, "status_code", None)
    code = getattr(exc, "code", None)
    message = str(exc)
    return (
        status_code == 429
        or code in {"rate_limit_exceeded", 429, "429", "1302"}
        or "429" in message
        or "速率限制" in message
        or "rate limit" in message.lower()
    )


def _float_env(env_name: str, default: float, minimum: float | None = None) -> float:
    value = os.environ.get(env_name, "").strip()
    if not value:
        return default
    try:
        parsed = float(value)
    except ValueError:
        return default
    if minimum is not None:
        return max(minimum, parsed)
    return parsed


def _int_env(env_name: str, default: int, minimum: int | None = None) -> int:
    value = os.environ.get(env_name, "").strip()
    if not value:
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    if minimum is not None:
        return max(minimum, parsed)
    return parsed


def _get_response_field(response: Any, name: str) -> Any:
    if isinstance(response, dict):
        return response.get(name)
    return getattr(response, name, None)


def _get_mapping_field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)
