"""按阶段成本、缓存和本机历史估算剩余耗时。
Estimate remaining time from stage costs, cached artifacts, and local history.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import json
import math
from pathlib import Path
from statistics import median

from .estimate_history import load_history


@dataclass(frozen=True)
class ProcessingEstimate:
    seconds: int | None
    factors: list[str]
    lower_seconds: int | None = None
    upper_seconds: int | None = None
    stages: dict[str, float] = field(default_factory=dict)
    history_samples: int = 0
    baseline_seconds: float | None = None
    calibration_key: str = ""


def estimate_processing(
    duration_seconds: float | None,
    input_bytes: int,
    target_langs: list[str],
    subtitle_video_mode: str,
    cache_hit: bool,
    *,
    source_mode: str = "auto",
    transcriber: str = "openai",
    translator: str = "openai",
    stage_cache: dict[str, bool] | None = None,
    encoding_profile: str = "auto",
    history_path: Path | None = None,
) -> ProcessingEstimate:
    """估算输入准备后的剩余工作，阶段成本采用初始经验值。

    旧参数 cache_hit 仅指音频缓存，具体 stage_cache 会覆盖它。
    历史校准只比较相同来源、引擎和缓存配置的实际耗时与基准耗时比值。

    Estimate remaining work after input preparation; stage costs are initial heuristics.

    Legacy cache_hit means cached audio only. More precise stage_cache entries override it.
    History compares equivalent source/engine/cache configurations using actual/baseline ratios.
    """
    if duration_seconds is None or not math.isfinite(duration_seconds) or duration_seconds <= 0:
        return ProcessingEstimate(None, ["视频时长未知，暂无法估算"])
    duration = float(duration_seconds)
    cache = {"audio": bool(cache_hit)}
    cache.update(stage_cache or {})
    factors = [f"字幕来源: {source_mode}", f"识别引擎: {transcriber}", f"翻译引擎: {translator}"]
    stages: dict[str, float] = {"prepare": 2.0}
    if input_bytes >= 500 * 1024 * 1024:
        stages["prepare"] += max(5, duration * 0.04)
        factors.append("视频文件较大")
    if source_mode == "embedded":
        stages["source"] = max(2, duration * 0.005)
    elif source_mode == "screen-ocr":
        stages["source"] = max(15, duration * 0.65)
    else:
        stages["audio"] = max(4, duration * 0.025)
        stages["transcription"] = max(8, duration * (0.22 if transcriber == "local-whisper" else 0.10))
        if source_mode == "auto":
            stages["source"] = max(3, duration * 0.015)
            factors.append("自动来源选择，可能增加 OCR 耗时")
    language_count = len(set(target_langs))
    translation_rate = {"local-transformer": 0.12, "local-nllb-quality": 0.30, "z-ai": 0.07}.get(translator, 0.08)
    stages["translation"] = language_count * max(3, duration * translation_rate)
    if language_count > 1:
        factors.append(f"{language_count} 种目标语言")
    if subtitle_video_mode == "none":
        stages["render"] = 0
        factors.append("仅输出字幕文件")
    elif subtitle_video_mode == "hard":
        render_rate = {"hardware": 0.20, "fast": 0.55, "quality": 1.2}.get(encoding_profile, 0.8)
        stages["render"] = max(15, duration * render_rate) * max(1, language_count)
        factors.append("固定位置硬字幕")
    else:
        stages["render"] = max(3, duration * 0.015)
        factors.append("软字幕封装")
    # 已有源字幕时，音频抽取和语音转写都无需再次执行。
    # A ready source subtitle supersedes extraction and speech recognition together.
    if cache.get("source"):
        for name in ("audio", "transcription", "source"):
            if name in stages:
                stages[name] = 0.5
        factors.append("字幕来源缓存命中")
    for name, label in (("audio", "音频"), ("transcription", "识别"), ("translation", "翻译"), ("render", "成片")):
        if cache.get(name) and name in stages:
            stages[name] = min(stages[name], 0.5)
            factors.append(f"{label}缓存命中")
    identity = {"version": 1, "source": source_mode, "transcriber": transcriber,
                "translator": translator, "mode": subtitle_video_mode, "encoding": encoding_profile,
                "languages": language_count, "cache": sorted(key for key, value in cache.items() if value)}
    key = sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    baseline = sum(stages.values())
    ratios = [sample["ratio"] for sample in load_history(history_path) if sample["key"] == key] if history_path else []
    multiplier = median(ratios) if ratios else 1.0
    seconds = max(1, round(baseline * multiplier))
    # 这些范围用于任务规划，并非统计置信区间。
    # These are planning ranges, not statistical confidence intervals.
    spread = 0.3 if len(ratios) >= 3 else 0.5
    lower_ratio = min([multiplier * (1 - spread)] + ratios)
    upper_ratio = max([multiplier * (1 + spread)] + ratios)
    if source_mode == "auto":
        upper_ratio = max(upper_ratio, multiplier * 2)
    if ratios:
        factors.append(f"本机历史校准: {len(ratios)} 次同类处理")
    else:
        factors.append("按阶段与引擎经验估算，实际耗时可能变化")
    return ProcessingEstimate(seconds, factors, max(1, math.floor(baseline * lower_ratio)),
                              max(seconds, math.ceil(baseline * upper_ratio)), stages,
                              len(ratios), baseline, key)


def format_estimate(seconds: int | None) -> str:
    if seconds is None:
        return "视频时长未知，暂无法估算"
    minutes, remainder = divmod(max(0, seconds), 60)
    if minutes:
        return f"约 {minutes} 分 {remainder:02} 秒"
    return f"约 {remainder} 秒"
