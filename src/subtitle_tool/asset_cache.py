from __future__ import annotations

from hashlib import sha256
import json
import os
import shutil
import stat
from pathlib import Path
from time import monotonic
from typing import Callable

from .atomic_files import atomic_write_text
from .errors import CancellationError
from .process_control import CancelCheck


class AssetCache:
    SCHEMA_VERSION = 2
    FINGERPRINT_VERSION = "content-sha256-v2"

    CATEGORY_DIRS = {
        "videos": "videos",
        "audio": "audio",
        "sourceSubtitles": "source-subtitles",
        "transcripts": "transcripts",
        "translations": "translations",
        "analysis": "analysis",
    }

    def __init__(self, root: Path):
        self.root = root

    @property
    def videos_dir(self) -> Path:
        return self.root / "videos"

    def file_fingerprint(
        self,
        path: Path,
        *,
        cancel_check: CancelCheck | None = None,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> str:
        # 流式读取全部字节；相同大小和首尾内容不能证明文件相同。
        # Stream every byte: matching size and file ends do not identify content.
        def check_cancelled() -> None:
            if cancel_check and cancel_check():
                raise CancellationError("Task was cancelled by user.")

        check_cancelled()
        digest = sha256()
        digest.update((self.FINGERPRINT_VERSION + "\0").encode("ascii"))
        with path.open("rb") as handle:
            total_bytes = os.fstat(handle.fileno()).st_size
            processed_bytes = 0
            last_progress = monotonic()
            if progress_callback:
                progress_callback(0, total_bytes)
            while True:
                check_cancelled()
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
                processed_bytes += len(chunk)
                check_cancelled()
                # 每块检查取消，但最多每半秒通知进度，避免频繁写任务状态。
                # Check cancellation each chunk, but limit progress writes to twice per second.
                if progress_callback and processed_bytes < total_bytes:
                    now = monotonic()
                    if now - last_progress >= 0.5:
                        progress_callback(processed_bytes, total_bytes)
                        last_progress = now
            check_cancelled()
            if progress_callback:
                progress_callback(processed_bytes, total_bytes)
        check_cancelled()
        return f"v{self.SCHEMA_VERSION}-" + digest.hexdigest()

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
        transcription_profile: str | None = None,
    ) -> Path:
        identity = {
            "schema": self.SCHEMA_VERSION,
            "video": video_fingerprint,
            "transcriber": transcriber,
            "source": source_lang or "auto",
            "model": str(whisper_model or "default"),
            "profile": transcription_profile or "standard",
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

    def load_subtitle_detection(self, video_fingerprint: str) -> dict[str, object] | None:
        path = self.root / "analysis" / f"{video_fingerprint}.subtitle-region.json"
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def store_subtitle_detection(
        self, video_fingerprint: str, payload: dict[str, object]
    ) -> Path:
        path = self.root / "analysis" / f"{video_fingerprint}.subtitle-region.json"
        atomic_write_text(
            path, json.dumps(payload, ensure_ascii=False, sort_keys=True)
        )
        return path

    def summary(self) -> dict[str, object]:
        categories: dict[str, dict[str, int]] = {}
        total_bytes = 0
        total_files = 0
        for name, directory_name in self.CATEGORY_DIRS.items():
            directory = self.root / directory_name
            size = 0
            count = 0
            try:
                for path in directory.rglob("*"):
                    try:
                        info = path.stat()
                    except (FileNotFoundError, NotADirectoryError):
                        continue
                    if stat.S_ISREG(info.st_mode):
                        size += info.st_size
                        count += 1
            except (FileNotFoundError, NotADirectoryError):
                pass
            categories[name] = {"bytes": size, "files": count}
            total_bytes += size
            total_files += count
        return {
            "schemaVersion": self.SCHEMA_VERSION,
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
