from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4


def atomic_output_path(final_path: Path) -> Path:
    final_path.parent.mkdir(parents=True, exist_ok=True)
    return final_path.with_name(
        f".{final_path.stem}.partial-{uuid4().hex[:10]}{final_path.suffix}"
    )


def commit_output(temporary_path: Path, final_path: Path) -> Path:
    final_path.parent.mkdir(parents=True, exist_ok=True)
    os.replace(temporary_path, final_path)
    return final_path


def atomic_write_text(path: Path, content: str, encoding: str = "utf-8") -> None:
    temporary_path = atomic_output_path(path)
    try:
        with temporary_path.open("w", encoding=encoding) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        commit_output(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)
