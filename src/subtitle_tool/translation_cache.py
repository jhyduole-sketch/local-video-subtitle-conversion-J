from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import threading

from .srt import SubtitleSegment


@dataclass(frozen=True)
class TranslationCacheEntry:
    translations: dict[int, str]
    engine: str
    complete: bool


class TranslationCache:
    def __init__(self, root: Path):
        self.root = root
        self._lock = threading.Lock()

    def load(
        self,
        segments: list[SubtitleSegment],
        source_lang: str | None,
        target_lang: str,
        provider: str,
    ) -> TranslationCacheEntry | None:
        entry = self.load_partial(segments, source_lang, target_lang, provider)
        return entry if entry and entry.complete else None

    def load_partial(
        self,
        segments: list[SubtitleSegment],
        source_lang: str | None,
        target_lang: str,
        provider: str,
    ) -> TranslationCacheEntry | None:
        path = self._path(segments, source_lang, target_lang, provider)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            expected_indexes = {segment.index for segment in segments}
            translations = {
                int(index): str(text)
                for index, text in payload["translations"].items()
                if int(index) in expected_indexes and str(text).strip()
            }
            if not translations:
                return None
            complete = set(translations) == expected_indexes
            return TranslationCacheEntry(
                translations=translations,
                engine=str(payload["engine"]),
                complete=complete,
            )
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def store(
        self,
        segments: list[SubtitleSegment],
        source_lang: str | None,
        target_lang: str,
        provider: str,
        translations: dict[int, str],
        engine: str,
    ) -> None:
        expected_indexes = {segment.index for segment in segments}
        if set(translations) != expected_indexes:
            return
        self._write(
            segments,
            source_lang,
            target_lang,
            provider,
            translations,
            engine,
            complete=True,
        )

    def store_partial(
        self,
        segments: list[SubtitleSegment],
        source_lang: str | None,
        target_lang: str,
        provider: str,
        translations: dict[int, str],
        engine: str,
    ) -> None:
        expected_indexes = {segment.index for segment in segments}
        valid = {
            index: text
            for index, text in translations.items()
            if index in expected_indexes and text.strip()
        }
        if not valid:
            return
        existing = self.load_partial(segments, source_lang, target_lang, provider)
        if existing:
            valid = {**existing.translations, **valid}
        self._write(
            segments,
            source_lang,
            target_lang,
            provider,
            valid,
            engine,
            complete=set(valid) == expected_indexes,
        )

    def _write(
        self,
        segments: list[SubtitleSegment],
        source_lang: str | None,
        target_lang: str,
        provider: str,
        translations: dict[int, str],
        engine: str,
        complete: bool,
    ) -> None:
        path = self._path(segments, source_lang, target_lang, provider)
        payload = {
            "engine": engine,
            "complete": complete,
            "translations": {
                str(index): translations[index] for index in sorted(translations)
            },
        }
        with self._lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path = path.with_suffix(".tmp")
            temporary_path.write_text(
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
                encoding="utf-8",
            )
            temporary_path.replace(path)

    def _path(
        self,
        segments: list[SubtitleSegment],
        source_lang: str | None,
        target_lang: str,
        provider: str,
    ) -> Path:
        identity = {
            "version": 1,
            "source": source_lang or "auto",
            "target": target_lang,
            "provider": provider,
            "segments": [
                {"index": segment.index, "text": segment.text}
                for segment in segments
            ],
        }
        digest = sha256(
            json.dumps(
                identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()
        return self.root / f"{digest}.json"
