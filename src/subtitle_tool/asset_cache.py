from __future__ import annotations

from hashlib import sha256
import json
import os
import shutil
from pathlib import Path


class AssetCache:
    CATEGORY_DIRS = {
        "videos": "videos",
        "audio": "audio",
        "sourceSubtitles": "source-subtitles",
        "transcripts": "transcripts",
        "translations": "translations",
    }

    def __init__(self, root: Path):
        self.root = root

    @property
    def videos_dir(self) -> Path:
        return self.root / "videos"

    def file_fingerprint(self, path: Path) -> str:
        stat = path.stat()
        digest = sha256()
        digest.update(str(stat.st_size).encode("ascii"))
        with path.open("rb") as handle:
            digest.update(handle.read(1024 * 1024))
            if stat.st_size > 1024 * 1024:
                handle.seek(max(0, stat.st_size - 1024 * 1024))
                digest.update(handle.read(1024 * 1024))
        return digest.hexdigest()

    def audio_path(self, video_fingerprint: str) -> Path:
        return self.root / "audio" / f"{video_fingerprint}.mp3"

    def source_subtitle_path(self, video_fingerprint: str, kind: str) -> Path:
        return self.root / "source-subtitles" / f"{video_fingerprint}.{kind}.srt"

    def transcript_path(
        self,
        video_fingerprint: str,
        transcriber: str,
        source_lang: str | None,
        whisper_model: Path | None,
    ) -> Path:
        identity = {
            "video": video_fingerprint,
            "transcriber": transcriber,
            "source": source_lang or "auto",
            "model": str(whisper_model or "default"),
        }
        digest = sha256(
            json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return self.root / "transcripts" / f"{digest}.srt"

    def materialize_video(self, cached_path: Path, target_path: Path) -> Path:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if target_path.exists() and target_path.stat().st_size > 0:
            return target_path
        try:
            os.link(cached_path, target_path)
        except OSError:
            shutil.copy2(cached_path, target_path)
        return target_path

    def summary(self) -> dict[str, object]:
        categories: dict[str, dict[str, int]] = {}
        total_bytes = 0
        total_files = 0
        for name, directory_name in self.CATEGORY_DIRS.items():
            directory = self.root / directory_name
            files = [path for path in directory.rglob("*") if path.is_file()] if directory.exists() else []
            size = sum(path.stat().st_size for path in files)
            categories[name] = {"bytes": size, "files": len(files)}
            total_bytes += size
            total_files += len(files)
        return {
            "root": str(self.root),
            "totalBytes": total_bytes,
            "totalFiles": total_files,
            "categories": categories,
        }

    def clear(self, categories: list[str]) -> dict[str, object]:
        cleared: list[str] = []
        for name in categories:
            directory_name = self.CATEGORY_DIRS.get(name)
            if not directory_name:
                continue
            directory = self.root / directory_name
            if directory.exists():
                shutil.rmtree(directory)
            cleared.append(name)
        result = self.summary()
        result["cleared"] = cleared
        return result
