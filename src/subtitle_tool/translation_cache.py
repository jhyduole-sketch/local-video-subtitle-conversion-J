from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import fcntl
import os
from pathlib import Path
import sqlite3

from .cache_identity import translation_identity
from .srt import SubtitleSegment


@dataclass(frozen=True)
class TranslationCacheEntry:
    translations: dict[int, str]
    engine: str
    complete: bool


def _validated_entry(payload: object, expected: set[int]) -> TranslationCacheEntry | None:
    # 缓存是可丢弃数据；不将损坏字段强制转换成可见译文。
    # Cache data is disposable; never coerce malformed fields into visible translations.
    if not isinstance(payload, dict):
        return None
    raw, engine = payload.get("translations"), payload.get("engine")
    if not isinstance(raw, dict) or not isinstance(engine, str) or not engine.strip():
        return None
    translations = {}
    for index, text in raw.items():
        if not isinstance(index, str) or not index.isdecimal():
            return None
        if not isinstance(text, str) or not text.strip():
            return None
        if int(index) in expected:
            translations[int(index)] = text
    return TranslationCacheEntry(translations, engine, set(translations) == expected) if translations else None


class TranslationSession:
    """一次计算身份，每批只写变更行。 Compute identity once and persist only changed rows per batch."""

    def __init__(self, legacy_path: Path, expected: set[int]):
        self.legacy_path = legacy_path
        self.path = legacy_path.with_suffix(".sqlite3")
        self.expected = expected
        self._loaded = False
        self._invalid = False
        self._entry: TranslationCacheEntry | None = None

    def load_partial(self) -> TranslationCacheEntry | None:
        if self._loaded:
            return self._entry
        if self.path.exists():
            payload = self._transaction(lambda db, recovered: self._read_payload(db))
            self._entry = _validated_entry(payload, self.expected)
            self._invalid = bool(payload["translations"]) and self._entry is None
        elif self.legacy_path.exists():
            try:
                self._entry = _validated_entry(json.loads(self.legacy_path.read_text(encoding="utf-8")), self.expected)
            except (OSError, ValueError, TypeError):
                self._entry = None
        self._loaded = True
        return self._entry

    def clear(self) -> None:
        def remove(db, recovered):
            db.execute("DELETE FROM translations")
            db.execute("DELETE FROM metadata")
        self._transaction(remove)
        self.legacy_path.unlink(missing_ok=True)
        self._entry, self._loaded = None, True

    def store_partial(self, translations: dict[int, str], engine: str) -> None:
        if not isinstance(engine, str) or not engine.strip():
            return
        valid = {index: text for index, text in translations.items()
                 if type(index) is int and index in self.expected and isinstance(text, str) and text.strip()}
        if not valid:
            return
        existing = self.load_partial()
        merged = {**(existing.translations if existing else {}), **valid}
        # 首次写入迁移旧 JSON；事务串行化独立进程，UPSERT 保留其他批次。
        # Migrate legacy JSON on first write; transactions serialize processes and UPSERT preserves other batches.
        delta = merged if not self.path.exists() else {
            index: text for index, text in valid.items()
            if not existing or existing.translations.get(index) != text
        }
        def write(db, recovered):
            if self._invalid:
                current = _validated_entry(self._read_payload(db), self.expected)
                if current is None:
                    db.execute("DELETE FROM translations")
            db.executemany(
                "INSERT INTO translations(position,text) VALUES (?,?) "
                "ON CONFLICT(position) DO UPDATE SET text=excluded.text WHERE text<>excluded.text",
                (merged if recovered else delta).items(),
            )
            db.execute("INSERT INTO metadata(id,engine) VALUES(1,?) ON CONFLICT(id) DO UPDATE SET engine=excluded.engine", (engine,))
        self._transaction(write)
        self._invalid = False
        self._entry = TranslationCacheEntry(merged, engine, set(merged) == self.expected)
        self._loaded = True

    def store(self, translations: dict[int, str], engine: str) -> None:
        if set(translations) == self.expected:
            self.store_partial(translations, engine)

    @staticmethod
    def _read_payload(db):
        row = db.execute("SELECT engine FROM metadata WHERE id=1").fetchone()
        return {"engine": row[0] if row else None, "translations": {
            str(index): text for index, text in db.execute("SELECT position,text FROM translations")
        }}

    def _transaction(self, operation):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # 文件锁覆盖整个读写及损坏恢复，损坏可能直到读取数据页才被发现。
        # Lock the full operation and recovery: corruption may only appear when reading data pages.
        with self.path.with_suffix(".lock").open("a+b") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                for attempt in range(2):
                    db = sqlite3.connect(str(self.path), timeout=10)
                    try:
                        db.execute("BEGIN IMMEDIATE")
                        db.execute("CREATE TABLE IF NOT EXISTS translations(position INTEGER PRIMARY KEY, text TEXT NOT NULL)")
                        db.execute("CREATE TABLE IF NOT EXISTS metadata(id INTEGER PRIMARY KEY CHECK(id=1), engine TEXT NOT NULL)")
                        result = operation(db, bool(attempt))
                        db.commit()
                        return result
                    except sqlite3.DatabaseError as error:
                        db.rollback()
                        code = getattr(error, "sqlite_errorcode", 0) & 0xff
                        corrupt = code in {11, 26} or any(message in str(error).lower() for message in
                            ("not a database", "database disk image is malformed", "malformed database schema"))
                        if attempt or not corrupt:
                            raise
                        db.close()
                        # 仅对确认损坏重建；磁盘满、权限或锁超时错误照常上报。
                        # Rebuild confirmed corruption only; propagate disk-full, permission and lock-timeout errors.
                        os.replace(self.path, self.path.with_suffix(".corrupt"))
                        journal = Path(str(self.path) + "-journal")
                        if journal.exists():
                            os.replace(journal, Path(str(self.path.with_suffix(".corrupt")) + "-journal"))
                    finally:
                        db.close()
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)


class TranslationCache:
    def __init__(self, root: Path):
        self.root = root

    def bind(self, segments, source_lang, target_lang, provider) -> TranslationSession:
        return TranslationSession(self._path(segments, source_lang, target_lang, provider),
                                  {segment.index for segment in segments})

    def load(self, segments, source_lang, target_lang, provider) -> TranslationCacheEntry | None:
        entry = self.load_partial(segments, source_lang, target_lang, provider)
        return entry if entry and entry.complete else None

    def load_partial(self, segments, source_lang, target_lang, provider) -> TranslationCacheEntry | None:
        return self.bind(segments, source_lang, target_lang, provider).load_partial()

    def store(self, segments, source_lang, target_lang, provider, translations, engine) -> None:
        self.bind(segments, source_lang, target_lang, provider).store(translations, engine)

    def store_partial(self, segments, source_lang, target_lang, provider, translations, engine) -> None:
        self.bind(segments, source_lang, target_lang, provider).store_partial(translations, engine)

    def _path(self, segments, source_lang, target_lang, provider) -> Path:
        identity = {
            "version": 2, "configuration": translation_identity(provider),
            "source": source_lang or "auto", "target": target_lang, "provider": provider,
            "segments": [{"index": segment.index, "text": segment.text} for segment in segments],
        }
        digest = sha256(json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return self.root / f"{digest}.json"
