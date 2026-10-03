from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from random import randint
import re
import sys
from time import monotonic
from .estimate_history import record_processing_time
from .processing_diagnostics import estimate_input
from .input_resolution import resolve_input
from .source_selection import load_source_segments
from tempfile import TemporaryDirectory
from typing import Callable, TypeVar

from .errors import CancellationError, MediaError, SubtitleToolError
from .asset_cache import AssetCache
from .local_translate import (
    NLLB_QUALITY_MODEL_NAME,
    normalize_lang,
    translate_segments_locally,
    translate_segments_with_nllb,
)
from .local_whisper import DEFAULT_VAD_MODEL_PATH, transcribe_with_whisper_cpp
from .media import (
    EncodingProgress,
    burn_subtitle_track,
    extract_audio,
    extract_first_subtitle,
    find_subtitle_streams,
    mux_subtitle_track,
    mux_subtitle_tracks,
    probe_duration_seconds,
)
from .openai_client import transcribe_audio, translate_segments, translate_segments_with_zai
from .performance import StageTimer
from .preflight import validate_processing_space
from .processing_estimate import estimate_processing, format_estimate
from .resource_scheduler import HEAVY_RESOURCE_SCHEDULER
from .process_control import CancelCheck
from .runtime_paths import cache_root
from .screen_ocr import get_screen_ocr_engine, is_suspicious_transcript
from .source_quality import score_source_segments
from .srt import SubtitleSegment, read_srt, replace_text, write_srt
from .subtitle_layout import layout_subtitles, write_ass
from .talksmith import extract_scenario_id, is_talksmith_url, is_url, resolve_talksmith_input
from .translation_cache import TranslationCache
from .translation_engines import (
    TRANSLATOR_IDS,
    canonical_translator_id,
    translation_cache_provider,
    translator_label,
)
from .translation_scheduler import (
    TranslationAttempt, classify_translation_failure, schedule_translation,
    _deduplicate_translation_segments, _collapse_initial_translations,
    _expand_deduplicated_translations,
)
from .video_subtitle_detection import (
    SubtitleRegionDetection,
    detect_video_subtitle_region,
)
from .youtube import (
    download_bilibili_video,
    download_generic_video,
    download_youtube_video,
    extract_bilibili_id,
    extract_youtube_id,
    is_bilibili_url,
    is_youtube_url,
)


ProgressCallback = Callable[[str, int], None]
T = TypeVar("T")


@dataclass(frozen=True)
class PipelineOptions:
    input_value: str
    target_langs: list[str]
    source_lang: str | None
    out_dir: Path
    source: str
    output_format: str
    force_download: bool = False
    download_only: bool = False
    transcriber: str = "openai"
    whisper_model: Path | None = None
    whisper_use_gpu: bool = True
    whisper_use_vad: bool = True
    whisper_vad_model: Path | None = None
    translator: str = "openai"
    embed_subtitles: bool = False
    avoid_subtitle_overlap: bool = False
    subtitle_video_mode: str = "soft"
    subtitle_position: str = "auto"
    subtitle_encoding_profile: str = "auto"
    progress_callback: ProgressCallback | None = None
    cancel_check: CancelCheck | None = None
    force_regenerate: bool = False


@dataclass(frozen=True)
class PipelineResult:
    source_subtitle_path: Path | None
    translated_paths: dict[str, Path]
    failed_languages: dict[str, str]
    source_kind: str
    translation_engines: dict[str, str] | None = None
    downloaded_video_path: Path | None = None
    subtitled_video_paths: dict[str, Path] | None = None
    input_video_path: Path | None = None
    stage_durations: dict[str, float] | None = None
    total_duration_seconds: float | None = None
    multilingual_subtitled_video_path: Path | None = None
    processing_estimate_seconds: int | None = None
    processing_estimate_factors: list[str] | None = None
    processing_estimate_lower_seconds: int | None = None
    processing_estimate_upper_seconds: int | None = None
    processing_estimate_history_samples: int = 0
    source_quality: dict[str, object] | None = None
    translation_attempts: dict[str, list[dict[str, str]]] | None = None


@dataclass
class _TranslationRunState:
    zai_circuit_open: bool = False
    zai_failure_reason: str | None = None
    checkpoint_engine: str | None = None


def run_pipeline(options: PipelineOptions) -> PipelineResult:
    timer = StageTimer()
    _progress(options, "检查参数", 2)
    for language in [options.source_lang, *options.target_langs]:
        if language is not None and not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,31}", language):
            raise SubtitleToolError("语言标识只能包含字母、数字、连字符和下划线，长度不超过 32。")
    if options.output_format != "srt":
        raise SubtitleToolError("v1 only supports --format srt.")
    if options.source not in {"auto", "embedded", "audio", "screen-ocr"}:
        raise SubtitleToolError(
            "--source must be one of: auto, embedded, audio, screen-ocr."
        )
    if options.transcriber not in {"openai", "local-whisper"}:
        raise SubtitleToolError("--transcriber must be one of: openai, local-whisper.")
    if options.translator not in TRANSLATOR_IDS:
        raise SubtitleToolError(
            "--translator must be one of: openai, z-ai, local-transformer, "
            "local-nllb, local-nllb-quality."
        )
    if options.subtitle_video_mode not in {"soft", "hard"}:
        raise SubtitleToolError("--subtitle-video-mode must be one of: soft, hard.")
    if options.subtitle_position not in {"auto", "bottom", "above-bottom", "top"}:
        raise SubtitleToolError(
            "--subtitle-position must be one of: auto, bottom, above-bottom, top."
        )
    if options.subtitle_encoding_profile not in {"auto", "hardware", "fast", "quality"}:
        raise SubtitleToolError(
            "--hard-subtitle-encoder must be one of: auto, hardware, fast, quality."
        )

    timestamp = _timestamp_suffix()
    output_stem = _base_output_stem(_input_output_stem(options.input_value), timestamp)
    task_out_dir = options.out_dir / f"{output_stem}.{timestamp}"
    task_out_dir.mkdir(parents=True, exist_ok=True)
    asset_cache = AssetCache(cache_root(options.out_dir))
    _progress(options, "准备输入视频", 5)
    with timer.stage("input"):
        input_path, downloaded_video_path = _resolve_input(
            options, task_out_dir, timestamp, asset_cache
        )
    _progress(options, f"视频已准备: {input_path.name}", 15)
    if options.download_only:
        _progress(options, "下载任务完成", 100)
        return PipelineResult(
            source_subtitle_path=None, translated_paths={}, failed_languages={}, source_kind="download",
            downloaded_video_path=downloaded_video_path or input_path, input_video_path=input_path,
            stage_durations=timer.durations(), total_duration_seconds=timer.total_duration_seconds(),
        )
    video_fingerprint = asset_cache.file_fingerprint(
        input_path,
        cancel_check=options.cancel_check,
        progress_callback=lambda done, total: _progress(
            options, f"计算视频内容指纹: {done * 100 // max(total, 1)}%", 15
        ),
    )
    with timer.stage("input-analysis"):
        duration_seconds = probe_duration_seconds(input_path, options.cancel_check)
        processing_estimate, estimate_history_path = estimate_input(
            options, input_path, asset_cache, video_fingerprint, duration_seconds,
            _resolved_subtitle_video_mode(options),
        )
    processing_started = monotonic()
    estimate_text = format_estimate(processing_estimate.seconds)
    if processing_estimate.lower_seconds is not None:
        estimate_text = f"约 {processing_estimate.lower_seconds}–{processing_estimate.upper_seconds} 秒"
    _progress(
        options,
        f"处理预估: {estimate_text} · "
        + "、".join(processing_estimate.factors),
        15,
    )

    required_bytes = validate_processing_space(
        input_path,
        task_out_dir,
        options.embed_subtitles,
        _resolved_subtitle_video_mode(options),
        len(options.target_langs),
    )
    _progress(
        options,
        f"预检完成，已为任务预留空间估算 {_format_bytes(required_bytes)}",
        16,
    )

    _progress(options, "读取字幕来源", 18)
    with timer.stage("source"):
        source_segments, source_kind = _load_source_segments(
            options, input_path, asset_cache, video_fingerprint=video_fingerprint
        )
    source_quality = score_source_segments(source_segments, options.source_lang).to_dict()
    _progress(
        options,
        f"源字幕质量: {source_quality['score']} 分 · "
        + "、".join(list(source_quality["reasons"])[:2]),
        53,
    )
    _progress(options, f"得到源字幕片段: {len(source_segments)} 条", 52)
    lang_suffix = options.source_lang or "auto"
    source_path = task_out_dir / f"{output_stem}.{timestamp}.source.{lang_suffix}.srt"
    write_srt(source_path, source_segments)
    _progress(options, f"源字幕已输出: {source_path.name}", 56)

    translated_paths: dict[str, Path] = {}
    subtitled_video_paths: dict[str, Path] = {}
    failed_languages: dict[str, str] = {}
    translation_engines: dict[str, str] = {}
    translation_attempts: dict[str, list[dict[str, str]]] = {}
    translation_cache = TranslationCache(asset_cache.root / "translations")
    cache_provider = translation_cache_provider(options.translator)
    translation_run_state = _TranslationRunState()
    subtitle_video_mode = _resolved_subtitle_video_mode(options)
    multi_language_soft_video = (
        options.embed_subtitles
        and subtitle_video_mode == "soft"
        and len(options.target_langs) > 1
    )
    if (
        options.embed_subtitles
        and subtitle_video_mode == "hard"
        and options.subtitle_video_mode == "soft"
    ):
        _progress(
            options,
            "检测到避免遮挡与软字幕冲突，已自动切换稳定硬字幕",
            57,
        )
    subtitle_position = _resolve_effective_subtitle_position(
        options,
        input_path,
        video_fingerprint,
        asset_cache,
        task_out_dir,
    )
    if options.embed_subtitles:
        position_label = {
            "bottom": "画面底部",
            "above-bottom": "原底部字幕上方",
            "top": "画面顶部",
        }[subtitle_position]
        mode_label = "稳定硬字幕" if subtitle_video_mode == "hard" else "软字幕"
        _progress(
            options,
            f"实际字幕模式: {mode_label} · {position_label}",
            57,
        )
    mux_executor = (
        ThreadPoolExecutor(max_workers=1)
        if options.embed_subtitles and not multi_language_soft_video
        else None
    )
    mux_jobs: dict[str, tuple[Future[Path], Path, int]] = {}
    video_output_timer_started = False
    total_targets = max(len(options.target_langs), 1)
    try:
        for target_index, target_lang in enumerate(options.target_langs, start=1):
            attempts: list[dict[str, str]] = []
            try:
                timer.start(f"translation:{target_lang}")
                base_percent = 56 + round((target_index - 1) * 36 / total_targets)
                translated_percent = 56 + round((target_index - 0.45) * 36 / total_targets)
                output_percent = 56 + round(target_index * 36 / total_targets)
                _progress(options, f"开始翻译: {target_lang}", base_percent)
                if _is_same_language(options.source_lang, target_lang):
                    _progress(
                        options,
                        f"目标语言 {target_lang} 与原视频语言一致，直接输出源字幕",
                        translated_percent,
                    )
                    translations = {
                        segment.index: segment.text for segment in source_segments
                    }
                    engine = "源字幕直出"
                    attempts.append(TranslationAttempt(engine, "success").to_dict())
                else:
                    translation_session = translation_cache.bind(
                        source_segments, options.source_lang, target_lang, cache_provider
                    )
                    if options.force_regenerate:
                        translation_session.clear()
                    partial = translation_session.load_partial()
                    cached = partial if partial and partial.complete else None
                    if cached:
                        translations = cached.translations
                        engine = f"{cached.engine}（缓存）"
                        _progress(
                            options,
                            f"使用翻译缓存: {target_lang} · {cached.engine}",
                            min(translated_percent - 1, base_percent + 1),
                        )
                    else:
                        initial_translations = (
                            partial.translations
                            if partial
                            else None
                        )
                        if initial_translations:
                            _progress(
                                options,
                                f"恢复翻译断点: {target_lang} · "
                                f"已完成 {len(initial_translations)}/{len(source_segments)} 条",
                                min(translated_percent - 1, base_percent + 1),
                            )
                        translations, engine = _translate_target(
                            options,
                            source_segments,
                            target_lang,
                            min(translated_percent - 1, base_percent + 1),
                            initial_translations,
                            lambda values: translation_session.store_partial(
                                values,
                                translation_run_state.checkpoint_engine or translator_label(cache_provider),
                            ),
                            final_progress_percent=translated_percent,
                            run_state=translation_run_state,
                            attempt_callback=lambda attempt: attempts.append(attempt.to_dict()),
                            initial_engine=partial.engine if partial and initial_translations else None,
                        )
                        translation_session.store(
                            translations,
                            engine,
                        )
                translation_engines[target_lang] = engine
                if not attempts or attempts[-1].get("outcome") != "success":
                    attempts.append(TranslationAttempt(engine, "success").to_dict())
                translation_attempts[target_lang] = attempts
                _progress(options, f"翻译完成: {target_lang}", translated_percent)
                translated = layout_subtitles(
                    replace_text(source_segments, translations)
                )
                output_path = task_out_dir / f"{output_stem}.{timestamp}.{target_lang}.srt"
                write_srt(output_path, translated)
                translated_paths[target_lang] = output_path
                timer.finish(f"translation:{target_lang}")
                _progress(options, f"字幕文件已输出: {output_path.name}", output_percent)
                if mux_executor:
                    if not video_output_timer_started:
                        timer.start("video-output")
                        video_output_timer_started = True
                    if subtitle_video_mode == "soft":
                        if options.avoid_subtitle_overlap:
                            _progress(
                                options,
                                "软字幕位置由播放器控制；需要固定避让请改用稳定硬字幕视频",
                                min(output_percent + 1, 95),
                            )
                        video_output_path = task_out_dir / (
                            f"{output_stem}.{timestamp}.{target_lang}.default-sub.mp4"
                        )
                        _progress(
                            options,
                            f"后台合成软字幕视频: {target_lang}",
                            min(output_percent + 1, 95),
                        )
                        future = mux_executor.submit(
                            mux_subtitle_track,
                            input_path,
                            output_path,
                            video_output_path,
                            _mp4_language_code(target_lang),
                            target_lang,
                            options.cancel_check,
                        )
                    else:
                        ass_path = task_out_dir / (
                            f"{output_stem}.{timestamp}.{target_lang}.ass"
                        )
                        write_ass(ass_path, translated, subtitle_position)
                        video_output_path = task_out_dir / (
                            f"{output_stem}.{timestamp}.{target_lang}.fixed-sub.mp4"
                        )
                        _progress(
                            options,
                            f"后台烧录固定位置字幕: {target_lang} · {subtitle_position}",
                            min(output_percent + 1, 95),
                        )
                        future = mux_executor.submit(
                            _burn_subtitle_track_with_resource,
                            options,
                            input_path,
                            ass_path,
                            video_output_path,
                            options.cancel_check,
                            encoding_profile=options.subtitle_encoding_profile,
                            progress_callback=lambda progress, language=target_lang: _encoding_progress(
                                options, language, progress
                            ),
                            status_callback=lambda message, language=target_lang: _progress(
                                options, f"硬字幕 {language}: {message}", 93
                            ),
                        )
                    mux_jobs[target_lang] = (
                        future,
                        video_output_path,
                        99 if subtitle_video_mode == "hard" else min(output_percent + 3, 96),
                    )
            except CancellationError:
                timer.finish(f"translation:{target_lang}")
                raise
            except Exception as exc:
                timer.finish(f"translation:{target_lang}")
                failed_languages[target_lang] = str(exc)
                if not attempts or attempts[-1].get("outcome") != "failed":
                    attempts.append(
                        TranslationAttempt(
                            translator_label(canonical_translator_id(options.translator)),
                            "failed", str(exc), classify_translation_failure(exc),
                        ).to_dict()
                    )
                translation_attempts[target_lang] = attempts
                _progress(options, f"翻译失败: {target_lang}: {exc}", 92)
    finally:
        if mux_executor:
            mux_executor.shutdown(wait=True)

    for target_lang, (future, video_output_path, output_percent) in mux_jobs.items():
        try:
            future.result()
            subtitled_video_paths[target_lang] = video_output_path
            _progress(
                options,
                f"字幕视频已输出: {video_output_path.name}",
                output_percent,
            )
        except Exception as exc:
            failed_languages[f"video:{target_lang}"] = str(exc)
            _progress(options, f"视频封装失败: {target_lang}: {exc}", 96)
    if video_output_timer_started:
        timer.finish("video-output")

    multilingual_subtitled_video_path: Path | None = None
    if multi_language_soft_video and translated_paths:
        tracks = [
            (path, _mp4_language_code(language), language)
            for language, path in translated_paths.items()
        ]
        if len(tracks) == 1:
            language, _subtitle_path = next(iter(translated_paths.items()))
            video_output_path = task_out_dir / (
                f"{output_stem}.{timestamp}.{language}.default-sub.mp4"
            )
        else:
            multilingual_subtitled_video_path = task_out_dir / (
                f"{output_stem}.{timestamp}.multilingual.default-sub.mp4"
            )
            video_output_path = multilingual_subtitled_video_path
        try:
            timer.start("video-output")
            if len(tracks) == 1:
                _progress(options, "仅一种语言翻译成功，按单语言方式封装", 95)
                subtitle_path, language_code, title = tracks[0]
                mux_subtitle_track(
                    input_path,
                    subtitle_path,
                    video_output_path,
                    language_code,
                    title,
                    options.cancel_check,
                )
                subtitled_video_paths[language] = video_output_path
                _progress(options, f"字幕视频已输出: {video_output_path.name}", 99)
            else:
                _progress(
                    options,
                    f"一次封装 {len(tracks)} 条可切换字幕轨",
                    95,
                )
                mux_subtitle_tracks(
                    input_path,
                    tracks,
                    video_output_path,
                    options.cancel_check,
                )
                _progress(
                    options,
                    f"多语言软字幕视频已输出: {video_output_path.name}",
                    99,
                )
        except Exception as exc:
            failed_languages["video:multilingual"] = str(exc)
            multilingual_subtitled_video_path = None
            _progress(options, f"多语言视频封装失败: {exc}", 96)
        finally:
            timer.finish("video-output")

    if not translated_paths and failed_languages:
        details = "; ".join(
            f"{language}: {message}" for language, message in failed_languages.items()
        )
        raise SubtitleToolError(f"All subtitle translations failed. {details}")

    _progress(options, "任务完成", 100)
    if not failed_languages:
        record_processing_time(estimate_history_path, processing_estimate, monotonic() - processing_started)
    stage_durations = timer.durations()
    total_duration_seconds = timer.total_duration_seconds()
    _progress(
        options,
        f"阶段耗时: {_format_stage_durations(stage_durations)} · "
        f"总计 {total_duration_seconds:.1f} 秒",
        100,
    )
    return PipelineResult(
        source_subtitle_path=source_path,
        translated_paths=translated_paths,
        failed_languages=failed_languages,
        source_kind=source_kind,
        translation_engines=translation_engines,
        downloaded_video_path=downloaded_video_path,
        subtitled_video_paths=subtitled_video_paths,
        input_video_path=input_path,
        stage_durations=stage_durations,
        total_duration_seconds=total_duration_seconds,
        multilingual_subtitled_video_path=multilingual_subtitled_video_path,
        processing_estimate_seconds=processing_estimate.seconds,
        processing_estimate_factors=processing_estimate.factors,
        processing_estimate_lower_seconds=processing_estimate.lower_seconds,
        processing_estimate_upper_seconds=processing_estimate.upper_seconds,
        processing_estimate_history_samples=processing_estimate.history_samples,
        source_quality=source_quality,
        translation_attempts=translation_attempts,
    )


def _format_stage_durations(durations: dict[str, float]) -> str:
    labels = {"input": "输入", "source": "源字幕", "video-output": "视频输出"}
    parts = []
    for name, seconds in durations.items():
        label = labels.get(name, name.replace("translation:", "翻译 "))
        parts.append(f"{label} {seconds:.1f}s")
    return " · ".join(parts) if parts else "无"


def _format_bytes(value: int) -> str:
    if value >= 1024**3:
        return f"{value / 1024**3:.1f} GB"
    return f"{value / 1024**2:.1f} MB"


def render_edited_subtitle_video(
    video_path: Path,
    subtitle_path: Path,
    output_path: Path,
    mode: str,
    position: str,
    cancel_check: CancelCheck | None = None,
    encoding_profile: str = "auto",
    progress_callback: Callable[[EncodingProgress], None] | None = None,
    status_callback: Callable[[str], None] | None = None,
) -> Path:
    if mode not in {"soft", "hard"}:
        raise SubtitleToolError("Edited subtitle video mode must be soft or hard.")
    if position not in {"bottom", "above-bottom", "top"}:
        raise SubtitleToolError("Edited subtitle position is invalid.")
    segments = layout_subtitles(read_srt(subtitle_path))
    write_srt(subtitle_path, segments)
    if mode == "hard":
        ass_path = output_path.with_suffix(".ass")
        write_ass(ass_path, segments, position)
        with HEAVY_RESOURCE_SCHEDULER.reserve(
            "编辑字幕视频烧录", cancel_check=cancel_check
        ):
            return burn_subtitle_track(
                video_path,
                ass_path,
                output_path,
                cancel_check,
                encoding_profile=encoding_profile,
                progress_callback=progress_callback,
                status_callback=status_callback,
            )
    return mux_subtitle_track(
        video_path,
        subtitle_path,
        output_path,
        "und",
        "edited",
        cancel_check,
    )


def _resolved_subtitle_position(options: PipelineOptions) -> str:
    if options.subtitle_position != "auto":
        return options.subtitle_position
    return "above-bottom" if options.avoid_subtitle_overlap else "bottom"


def _encoding_progress(
    options: PipelineOptions, language: str, progress: EncodingProgress
) -> None:
    processed = _format_elapsed(progress.processed_seconds)
    duration = _format_elapsed(progress.duration_seconds)
    speed = f"{progress.speed:.2f}x" if progress.speed else "计算中"
    eta = (
        _format_elapsed(progress.eta_seconds)
        if progress.eta_seconds is not None
        else "计算中"
    )
    overall_percent = min(99, 93 + round(progress.percent * 6 / 100))
    _progress(
        options,
        f"烧录硬字幕 {language}: {progress.percent}% · 已处理 {processed}/{duration} "
        f"· 速度 {speed} · 预计剩余 {eta}",
        overall_percent,
    )


def _format_elapsed(seconds: float) -> str:
    total_seconds = max(0, round(seconds))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _heavy_call(
    options: PipelineOptions, label: str, operation: Callable[[], T]
) -> T:
    with HEAVY_RESOURCE_SCHEDULER.reserve(
        label,
        cancel_check=options.cancel_check,
        wait_callback=lambda active: _progress(
            options, f"等待重任务资源：当前正在执行 {active}", 93
        ),
    ):
        return operation()


def _burn_subtitle_track_with_resource(
    options: PipelineOptions,
    video_path: Path,
    ass_path: Path,
    output_path: Path,
    cancel_check: CancelCheck | None,
    **kwargs,
) -> Path:
    return _heavy_call(
        options,
        f"硬字幕编码 {output_path.name}",
        lambda: burn_subtitle_track(
            video_path, ass_path, output_path, cancel_check, **kwargs
        ),
    )


def _resolved_subtitle_video_mode(options: PipelineOptions) -> str:
    if options.embed_subtitles and options.avoid_subtitle_overlap:
        return "hard"
    return options.subtitle_video_mode


def _resolve_effective_subtitle_position(
    options: PipelineOptions,
    input_path: Path,
    video_fingerprint: str,
    asset_cache: AssetCache,
    task_out_dir: Path,
) -> str:
    fallback = _resolved_subtitle_position(options)
    if not (
        options.embed_subtitles
        and options.avoid_subtitle_overlap
        and options.subtitle_position == "auto"
        and _resolved_subtitle_video_mode(options) == "hard"
    ):
        return fallback

    cached = asset_cache.load_subtitle_detection(video_fingerprint)
    try:
        if cached:
            detection = _detection_from_payload(cached)
            _progress(options, "使用缓存的画面字幕位置检测", 55)
        else:
            _progress(options, "正在抽帧检测原画面字幕位置", 55)
            with TemporaryDirectory(prefix="subtitle-detection-") as temporary_dir:
                detection = detect_video_subtitle_region(
                    input_path,
                    Path(temporary_dir),
                    options.cancel_check,
                )
            asset_cache.store_subtitle_detection(
                video_fingerprint, _detection_to_payload(detection)
            )
    except CancellationError:
        raise
    except Exception as exc:
        _progress(options, f"画面字幕检测未完成，使用保守避让: {exc}", 55)
        return "above-bottom"

    target_position = {
        "top": "bottom",
        "bottom": "above-bottom",
        "none": "bottom",
        "unknown": "above-bottom",
    }.get(detection.position, "above-bottom")
    _progress(
        options,
        "画面字幕检测: "
        f"{detection.position} · 置信度 {round(detection.confidence * 100)}% · "
        f"新字幕位置 {target_position}",
        55,
    )
    return target_position


def _detection_to_payload(detection: SubtitleRegionDetection) -> dict[str, object]:
    return {
        "position": detection.position,
        "confidence": detection.confidence,
        "sampledFrames": detection.sampled_frames,
        "topScore": detection.top_score,
        "bottomScore": detection.bottom_score,
    }


def _detection_from_payload(payload: dict[str, object]) -> SubtitleRegionDetection:
    return SubtitleRegionDetection(
        position=str(payload.get("position") or "unknown"),
        confidence=float(payload.get("confidence") or 0.0),
        sampled_frames=int(payload.get("sampledFrames") or 0),
        top_score=float(payload.get("topScore") or 0.0),
        bottom_score=float(payload.get("bottomScore") or 0.0),
    )


def _translate_target(
    options, source_segments, target_lang, progress_percent,
    initial_translations=None, checkpoint_callback=None,
    final_progress_percent=None, run_state=None, attempt_callback=None,
    initial_engine=None,
):
    return schedule_translation(
        options, source_segments, target_lang, progress_percent,
        initial_translations=initial_translations,
        checkpoint_callback=checkpoint_callback,
        final_progress_percent=final_progress_percent,
        run_state=run_state or _TranslationRunState(),
        attempt_callback=attempt_callback, initial_engine=initial_engine,
        dependencies=sys.modules[__name__],
    )


def _resolve_input(options, task_out_dir, timestamp, asset_cache):
    return resolve_input(options, task_out_dir, timestamp, asset_cache, dependencies=sys.modules[__name__])


def _load_source_segments(options, input_path, asset_cache, video_fingerprint=None):
    return load_source_segments(
        options, input_path, asset_cache,
        dependencies=sys.modules[__name__], video_fingerprint=video_fingerprint,
    )


def _source_quality_is_usable(
    segments: list[SubtitleSegment], expected_language: str | None
) -> bool:
    return score_source_segments(segments, expected_language).score >= 35


def _load_screen_ocr_segments(
    options: PipelineOptions,
    input_path: Path,
    asset_cache: AssetCache,
    video_fingerprint: str,
) -> tuple[list[SubtitleSegment], str]:
    engine = get_screen_ocr_engine(asset_cache.root)
    if engine is None:
        raise MediaError(
            "画面字幕 OCR 引擎不可用。macOS 请确认已安装 Command Line Tools；"
            "其他系统可接入兼容的 OCR 引擎。"
        )

    source_kind = f"screen-ocr-{engine.engine_id}"
    cache_kind = f"{source_kind}-{options.source_lang or 'auto'}"
    cached_path = asset_cache.source_subtitle_path(video_fingerprint, cache_kind)
    if cached_path.exists():
        cached_segments = read_srt(cached_path)
        if cached_segments:
            _progress(options, f"使用缓存的画面字幕 OCR（{engine.label}）", 48)
            return cached_segments, f"{source_kind}-cache"

    _progress(options, f"启动画面字幕 OCR：{engine.label}", 40)
    segments = _heavy_call(
        options,
        f"画面字幕 OCR {engine.label}",
        lambda: engine.recognize_video(
            input_path,
            options.source_lang,
            cancel_check=options.cancel_check,
            progress_callback=lambda message: _progress(options, message, 44),
        ),
    )
    if not segments:
        raise MediaError("画面字幕 OCR 没有生成可用字幕")
    cached_path.parent.mkdir(parents=True, exist_ok=True)
    write_srt(cached_path, segments)
    _progress(options, f"画面字幕 OCR 完成：{len(segments)} 条", 48)
    return segments, source_kind


def _mp4_language_code(language: str) -> str:
    normalized = language.lower()
    if normalized.startswith("ja"):
        return "jpn"
    if normalized.startswith("zh"):
        return "chi"
    if normalized.startswith("en"):
        return "eng"
    return language[:3]


def _is_same_language(source_lang: str | None, target_lang: str) -> bool:
    source = normalize_lang(source_lang)
    target = normalize_lang(target_lang)
    if source == "auto" or target == "auto":
        return False
    if source.startswith("zh") and target.startswith("zh"):
        return True
    return source == target


def _progress(options: PipelineOptions, message: str, percent: int) -> None:
    if options.cancel_check and options.cancel_check():
        raise CancellationError("Task was cancelled by user.")
    if options.progress_callback:
        options.progress_callback(message, max(0, min(100, percent)))


def _timestamp_suffix() -> str:
    return f"{datetime.now().strftime('%Y%m%d%H%M%S')}{randint(0, 9)}"


def _base_output_stem(stem: str, timestamp: str) -> str:
    if stem.endswith(f".{timestamp}"):
        return stem[: -(len(timestamp) + 1)]
    return re.sub(r"\.\d{14}\d$", "", stem)


def _input_output_stem(input_value: str) -> str:
    if is_youtube_url(input_value):
        return extract_youtube_id(input_value)
    if is_bilibili_url(input_value):
        return extract_bilibili_id(input_value)
    if is_talksmith_url(input_value):
        return extract_scenario_id(input_value)
    return Path(input_value).expanduser().stem or "video"
