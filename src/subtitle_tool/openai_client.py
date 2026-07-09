from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .errors import OpenAIConfigError, SubtitleToolError
from .srt import SubtitleSegment


DEFAULT_TRANSCRIBE_MODEL = "whisper-1"
DEFAULT_TRANSLATE_MODEL = "gpt-4.1-mini"


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

    return OpenAI()


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

    try:
        parsed = json.loads(content)
        items = parsed["items"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise SubtitleToolError(
            f"OpenAI translation to {target_lang} returned invalid JSON."
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

    missing = {segment.index for segment in segments} - set(translations)
    if missing:
        missing_list = ", ".join(str(value) for value in sorted(missing)[:10])
        raise SubtitleToolError(
            f"OpenAI translation to {target_lang} missed subtitle indexes: {missing_list}"
        )

    return translations


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


def _get_response_field(response: Any, name: str) -> Any:
    if isinstance(response, dict):
        return response.get(name)
    return getattr(response, name, None)


def _get_mapping_field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)

