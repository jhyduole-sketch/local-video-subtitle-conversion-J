"""统计并清理无任务引用的保留上传。 Inspect and clean retained uploads without job references."""
from __future__ import annotations

import os
from pathlib import Path
import stat

from .web_security import RequestError


def retained_inputs(out_dir: Path, references: set[Path], *, clear: bool = False) -> dict[str, int]:
    root = out_dir.resolve() / ".inputs"
    result = dict(bytes=0, files=0, protectedBytes=0, reclaimableBytes=0,
                  removedBytes=0, removedFiles=0, skippedEntries=0)
    # 目录句柄和 O_NOFOLLOW 使检查后的删除也不会沿符号链接越界。
    # Directory descriptors and O_NOFOLLOW keep deletion from following symlinks after inspection.
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        root_fd = os.open(root, flags)
    except FileNotFoundError:
        return result
    except OSError as exc:
        raise RequestError("保留原视频目录无法安全访问，不能是符号链接。", 403) from exc
    try:
        for directory in os.listdir(root_fd):
            try:
                task_fd = os.open(directory, flags, dir_fd=root_fd)
            except OSError:
                result["skippedEntries"] += 1
                continue
            try:
                for name in os.listdir(task_fd):
                    try:
                        info = os.stat(name, dir_fd=task_fd, follow_symlinks=False)
                    except FileNotFoundError:
                        continue
                    if not stat.S_ISREG(info.st_mode):
                        result["skippedEntries"] += 1
                        continue
                    protected = root / directory / name in references
                    result["bytes"] += info.st_size
                    result["files"] += 1
                    result["protectedBytes" if protected else "reclaimableBytes"] += info.st_size
                    if clear and not protected:
                        os.unlink(name, dir_fd=task_fd)
                        result["removedFiles"] += 1
                        result["removedBytes"] += info.st_size
            finally:
                os.close(task_fd)
            if clear:
                try:
                    os.rmdir(directory, dir_fd=root_fd)
                except OSError:
                    pass  # 非空目录保留。 Keep nonempty directories.
    finally:
        os.close(root_fd)
    return result


def paths_in_record(value: object) -> set[Path]:
    if isinstance(value, dict):
        return set().union(*(paths_in_record(item) for item in value.values()))
    if isinstance(value, list):
        return set().union(*(paths_in_record(item) for item in value))
    if isinstance(value, str) and value and "://" not in value:
        try:
            return {Path(value).expanduser().resolve()}
        except (OSError, ValueError, RuntimeError):
            pass
    return set()
