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
        path = self._path(segments, source_lang, target_lang, provider)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            translations = {
                int(index): str(text)
                for index, text in payload["translations"].items()
                if str(text).strip()
            }
            expected_indexes = {segment.index for segment in segments}
            if set(translations) != expected_indexes:
                return None
            return TranslationCacheEntry(
                translations=translations,
                engine=str(payload["engine"]),
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
        path = self._path(segments, source_lang, target_lang, provider)
        payload = {
            "engine": engine,
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
