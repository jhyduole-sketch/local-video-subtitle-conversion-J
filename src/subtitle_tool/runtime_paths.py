from __future__ import annotations

import os
import shutil
from pathlib import Path


def state_database_path(project_root: Path, out_dir: Path) -> Path:
    configured = os.environ.get("SUBTITLE_TOOL_STATE_DB")
    if configured:
        return Path(configured).expanduser().resolve()

    target = project_root / ".subtitle-tool-state" / "jobs.sqlite3"
    _migrate_state_directory(out_dir / ".subtitle-tool-state", target.parent)
    return target


def cache_root(out_dir: Path) -> Path:
    configured = os.environ.get("SUBTITLE_TOOL_CACHE_DIR")
    if configured:
        return Path(configured).expanduser().resolve()

    cache_name = (
        ".subtitle-tool-cache"
        if out_dir.name == "output"
        else f".{out_dir.name}.subtitle-tool-cache"
    )
    target = out_dir.parent / cache_name
    _merge_cache_directory(out_dir / ".subtitle-tool-cache", target)
    return target


def _migrate_state_directory(legacy: Path, target: Path) -> None:
    if not legacy.exists() or legacy.resolve() == target.resolve():
        return
    target.mkdir(parents=True, exist_ok=True)
    for source in legacy.iterdir():
        destination = target / source.name
        if destination.exists():
            destination = _archive_path(target, source)
        shutil.move(str(source), str(destination))
    shutil.rmtree(legacy)


def _archive_path(target: Path, source: Path) -> Path:
    stem = source.stem
    suffix = source.suffix
    candidate = target / f"{stem}.legacy{suffix}"
    counter = 2
    while candidate.exists():
        candidate = target / f"{stem}.legacy-{counter}{suffix}"
        counter += 1
    return candidate


def _merge_cache_directory(legacy: Path, target: Path) -> None:
    if not legacy.exists() or legacy.resolve() == target.resolve():
        return
    for source in legacy.rglob("*"):
        if not source.is_file():
            continue
        destination = target / source.relative_to(legacy)
        if destination.exists():
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(destination))
    shutil.rmtree(legacy)
