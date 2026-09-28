"""可选的小型本机校准记录，不保存视频路径或凭据。
Small, optional local calibration store; no video paths or credentials are saved.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from threading import RLock
from typing import TYPE_CHECKING

from .atomic_files import atomic_write_text

if TYPE_CHECKING:
    from .processing_estimate import ProcessingEstimate

HISTORY_VERSION = 1
MAX_SAMPLES = 100
MAX_HISTORY_BYTES = 128 * 1024
_LOCK = RLock()


def load_history(path: Path) -> list[dict[str, object]]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            text = handle.read(MAX_HISTORY_BYTES + 1)
        if len(text) > MAX_HISTORY_BYTES:
            return []
        payload = json.loads(text)
    except (OSError, ValueError, UnicodeError):
        return []
    if not isinstance(payload, dict) or payload.get("version") != HISTORY_VERSION:
        return []
    raw = payload.get("samples")
    if not isinstance(raw, list):
        return []
    samples = []
    for item in raw[-MAX_SAMPLES:]:
        if not isinstance(item, dict) or not isinstance(item.get("key"), str):
            continue
        ratio = item.get("ratio")
        if type(ratio) not in (int, float) or not math.isfinite(ratio) or not 0.05 <= ratio <= 20:
            continue
        samples.append({"key": item["key"], "ratio": float(ratio)})
    return samples


def record_processing_time(path: Path, estimate: ProcessingEstimate, actual_seconds: float) -> bool:
    """记录从生成预估开始计时的成功任务，排除失败和取消的运行。

    校准写盘失败不应影响已完成任务；锁仅保护本进程，多个 CLI 进程可能丢失一个样本。

    Record a successful run timed from estimate creation; failures/cancellations must be excluded.

    Disk failures are ignored because optional calibration must not fail a finished job.
    The lock serializes writers in this process; independent CLI processes may lose a sample.
    """
    if not estimate.baseline_seconds or not estimate.calibration_key:
        return False
    if not math.isfinite(actual_seconds) or actual_seconds <= 0:
        return False
    ratio = actual_seconds / estimate.baseline_seconds
    if not 0.05 <= ratio <= 20:
        return False
    with _LOCK:
        samples = load_history(path)
        samples.append({"key": estimate.calibration_key, "ratio": ratio})
        try:
            atomic_write_text(path, json.dumps({"version": HISTORY_VERSION, "samples": samples[-MAX_SAMPLES:]}))
        except OSError:
            return False
    return True
