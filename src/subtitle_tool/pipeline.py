from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from random import randint
import re
from tempfile import TemporaryDirectory
from typing import Callable

from .errors import CancellationError, MediaError, SubtitleToolError
from .asset_cache import AssetCache
from .local_translate import (
    NLLB_MODEL_NAME,
    NLLB_QUALITY_MODEL_NAME,
    normalize_lang,
    translate_segments_locally,
    translate_segments_with_nllb,
)
from .local_whisper import transcribe_with_whisper_cpp
from .media import (
    burn_subtitle_track,
    extract_audio,
    extract_first_subtitle,
    find_subtitle_streams,
    mux_subtitle_track,
)
from .openai_client import transcribe_audio, translate_segments, translate_segments_with_zai
from .process_control import CancelCheck
from .runtime_paths import cache_root
from .srt import SubtitleSegment, read_srt, replace_text, write_srt
from .subtitle_layout import layout_subtitles, write_ass
from .talksmith import extract_scenario_id, is_talksmith_url, is_url, resolve_talksmith_input
from .translation_cache import TranslationCache
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
    translator: str = "openai"
    embed_subtitles: bool = False
    avoid_subtitle_overlap: bool = False
    subtitle_video_mode: str = "soft"
    subtitle_position: str = "auto"
    progress_callback: ProgressCallback | None = None
    cancel_check: CancelCheck | None = None


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


def run_pipeline(options: PipelineOptions) -> PipelineResult:
    _progress(options, "检查参数", 2)
    if options.output_format != "srt":
        raise SubtitleToolError("v1 only supports --format srt.")
    if options.source not in {"auto", "embedded", "audio"}:
        raise SubtitleToolError("--source must be one of: auto, embedded, audio.")
    if options.transcriber not in {"openai", "local-whisper"}:
        raise SubtitleToolError("--transcriber must be one of: openai, local-whisper.")
    if options.translator not in {
        "openai",
        "z-ai",
        "local-transformer",
        "local-nllb",
        "local-nllb-quality",
    }:
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

    timestamp = _timestamp_suffix()
    output_stem = _base_output_stem(_input_output_stem(options.input_value), timestamp)
    task_out_dir = options.out_dir / f"{output_stem}.{timestamp}"
    task_out_dir.mkdir(parents=True, exist_ok=True)
    asset_cache = AssetCache(cache_root(options.out_dir))
    _progress(options, "准备输入视频", 5)
    input_path, downloaded_video_path = _resolve_input(
        options, task_out_dir, timestamp, asset_cache
    )
    video_fingerprint = asset_cache.file_fingerprint(input_path)
    _progress(options, f"视频已准备: {input_path.name}", 15)

    if options.download_only:
        _progress(options, "下载任务完成", 100)
        return PipelineResult(
            source_subtitle_path=None,
            translated_paths={},
            failed_languages={},
            source_kind="download",
            downloaded_video_path=downloaded_video_path or input_path,
            input_video_path=input_path,
        )

    _progress(options, "读取字幕来源", 18)
    source_segments, source_kind = _load_source_segments(
        options, input_path, asset_cache
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
    translation_cache = TranslationCache(asset_cache.root / "translations")
    subtitle_video_mode = _resolved_subtitle_video_mode(options)
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
    mux_executor = ThreadPoolExecutor(max_workers=1) if options.embed_subtitles else None
    mux_jobs: dict[str, tuple[Future[Path], Path, int]] = {}
    total_targets = max(len(options.target_langs), 1)
    try:
        for target_index, target_lang in enumerate(options.target_langs, start=1):
            try:
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
                else:
                    partial = translation_cache.load_partial(
                        source_segments,
                        options.source_lang,
                        target_lang,
                        options.translator,
                    )
                    cached = translation_cache.load(
                        source_segments,
                        options.source_lang,
                        target_lang,
                        options.translator,
                    )
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
                            if partial and options.translator == "z-ai"
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
                            lambda values: translation_cache.store_partial(
                                source_segments,
                                options.source_lang,
                                target_lang,
                                options.translator,
                                values,
                                "z.ai",
                            ),
                        )
                        translation_cache.store(
                            source_segments,
                            options.source_lang,
                            target_lang,
                            options.translator,
                            translations,
                            engine,
                        )
                translation_engines[target_lang] = engine
                _progress(options, f"翻译完成: {target_lang}", translated_percent)
                translated = layout_subtitles(
                    replace_text(source_segments, translations)
                )
                output_path = task_out_dir / f"{output_stem}.{timestamp}.{target_lang}.srt"
                write_srt(output_path, translated)
                translated_paths[target_lang] = output_path
                _progress(options, f"字幕文件已输出: {output_path.name}", output_percent)
                if mux_executor:
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
                            burn_subtitle_track,
                            input_path,
                            ass_path,
                            video_output_path,
                            options.cancel_check,
                        )
                    mux_jobs[target_lang] = (
                        future,
                        video_output_path,
                        min(output_percent + 3, 96),
                    )
            except CancellationError:
                raise
            except Exception as exc:
                failed_languages[target_lang] = str(exc)
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

    if not translated_paths and failed_languages:
        details = "; ".join(
            f"{language}: {message}" for language, message in failed_languages.items()
        )
        raise SubtitleToolError(f"All subtitle translations failed. {details}")

    _progress(options, "任务完成", 100)
    return PipelineResult(
        source_subtitle_path=source_path,
        translated_paths=translated_paths,
        failed_languages=failed_languages,
        source_kind=source_kind,
        translation_engines=translation_engines,
        downloaded_video_path=downloaded_video_path,
        subtitled_video_paths=subtitled_video_paths,
        input_video_path=input_path,
    )


def render_edited_subtitle_video(
    video_path: Path,
    subtitle_path: Path,
    output_path: Path,
    mode: str,
    position: str,
    cancel_check: CancelCheck | None = None,
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
        return burn_subtitle_track(
            video_path, ass_path, output_path, cancel_check
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
    options: PipelineOptions,
    source_segments: list[SubtitleSegment],
    target_lang: str,
    progress_percent: int,
    initial_translations: dict[int, str] | None = None,
    checkpoint_callback: Callable[[dict[int, str]], None] | None = None,
) -> tuple[dict[int, str], str]:
    if options.translator == "local-transformer":
        return (
            translate_segments_locally(
                source_segments, options.source_lang, target_lang
            ),
            "本地快速模型",
        )
    if options.translator in {"local-nllb", "local-nllb-quality"}:
        model_name = (
            NLLB_QUALITY_MODEL_NAME
            if options.translator == "local-nllb-quality"
            else NLLB_MODEL_NAME
        )
        engine = (
            "本地 NLLB 1.3B（质量）"
            if options.translator == "local-nllb-quality"
            else "本地 NLLB 600M（快速）"
        )
        _progress(options, f"加载{engine}并开始批量翻译", progress_percent)
        return (
            translate_segments_with_nllb(
                source_segments,
                options.source_lang,
                target_lang,
                model_name=model_name,
                progress_callback=lambda message: _progress(
                    options, message, progress_percent
                ),
            ),
            engine,
        )
    if options.translator == "openai":
        return (
            translate_segments(
                source_segments,
                target_lang=target_lang,
                source_lang=options.source_lang,
            ),
            "OpenAI",
        )

    try:
        return (
            translate_segments_with_zai(
                source_segments,
                target_lang=target_lang,
                source_lang=options.source_lang,
                progress_callback=lambda message: _progress(
                    options, message, progress_percent
                ),
                initial_translations=initial_translations,
                checkpoint_callback=checkpoint_callback,
            ),
            "z.ai",
        )
    except Exception as zai_error:
        _progress(
            options,
            f"z.ai 翻译未完成，已自动切换本地模型: {zai_error}",
            progress_percent,
        )

    local_errors: list[str] = []
    try:
        translations = translate_segments_locally(
            source_segments, options.source_lang, target_lang
        )
        return translations, "本地模型"
    except Exception as local_error:
        local_errors.append(str(local_error))
        _progress(
            options,
            f"本地快速模型未完成，尝试本地 NLLB: {local_error}",
            progress_percent,
        )

    try:
        translations = translate_segments_with_nllb(
            source_segments,
            options.source_lang,
            target_lang,
            model_name=NLLB_MODEL_NAME,
            progress_callback=lambda message: _progress(
                options, message, progress_percent
            ),
        )
        return translations, "本地模型"
    except Exception as nllb_error:
        local_errors.append(str(nllb_error))

    _progress(
        options,
        "本地翻译未通过质量检查或不可用，已自动切换 OpenAI: "
        + " | ".join(local_errors),
        progress_percent,
    )
    return (
        translate_segments(
            source_segments,
            target_lang=target_lang,
            source_lang=options.source_lang,
        ),
        "OpenAI",
    )


def _resolve_input(
    options: PipelineOptions,
    task_out_dir: Path,
    timestamp: str,
    asset_cache: AssetCache,
) -> tuple[Path, Path | None]:
    if is_talksmith_url(options.input_value):
        _progress(options, "解析 TalkSmith 链接并下载视频", 8)
        downloaded_path = resolve_talksmith_input(
            options.input_value,
            asset_cache.videos_dir,
            options.force_download,
            None,
            options.cancel_check,
        )
        task_path = asset_cache.materialize_video(
            downloaded_path,
            task_out_dir / f"{extract_scenario_id(options.input_value)}.{timestamp}.mp4",
        )
        return task_path, task_path

    if is_youtube_url(options.input_value):
        _progress(options, "解析 YouTube 链接并下载视频", 8)
        video = download_youtube_video(
            options.input_value,
            asset_cache.videos_dir,
            options.force_download,
            None,
            options.cancel_check,
        )
        task_path = asset_cache.materialize_video(
            video.path, task_out_dir / f"{video.video_id}.{timestamp}.mp4"
        )
        return task_path, task_path

    if is_bilibili_url(options.input_value):
        _progress(options, "解析 Bilibili 链接并下载视频", 8)
        video = download_bilibili_video(
            options.input_value,
            asset_cache.videos_dir,
            options.force_download,
            None,
            options.cancel_check,
        )
        task_path = asset_cache.materialize_video(
            video.path, task_out_dir / f"{video.video_id}.{timestamp}.mp4"
        )
        return task_path, task_path

    if is_url(options.input_value):
        _progress(options, "未匹配专用站点，正在尝试通用网址解析", 8)
        video = download_generic_video(
            options.input_value,
            asset_cache.videos_dir,
            options.force_download,
            None,
            options.cancel_check,
        )
        task_path = asset_cache.materialize_video(
            video.path, task_out_dir / f"{video.video_id}.{timestamp}.mp4"
        )
        return task_path, task_path

    input_path = Path(options.input_value).expanduser().resolve()
    _progress(options, "检查本地视频文件", 8)
    if not input_path.exists():
        raise SubtitleToolError(f"Input video does not exist: {input_path}")
    task_path = asset_cache.materialize_video(input_path, task_out_dir / input_path.name)
    return task_path, None


def _load_source_segments(
    options: PipelineOptions, input_path: Path, asset_cache: AssetCache
) -> tuple[list[SubtitleSegment], str]:
    video_fingerprint = asset_cache.file_fingerprint(input_path)
    if options.source in {"auto", "embedded"}:
        cached_embedded_path = asset_cache.source_subtitle_path(
            video_fingerprint, "embedded"
        )
        if cached_embedded_path.exists():
            cached_segments = read_srt(cached_embedded_path)
            if cached_segments:
                _progress(options, "使用缓存的内置源字幕", 48)
                return cached_segments, "embedded-cache"
        _progress(options, "检查视频内置字幕轨", 22)
        streams = find_subtitle_streams(input_path, options.cancel_check)
        if streams:
            _progress(options, "发现内置字幕，正在导出", 30)
            cached_embedded_path.parent.mkdir(parents=True, exist_ok=True)
            extract_first_subtitle(
                input_path, cached_embedded_path, options.cancel_check
            )
            segments = read_srt(cached_embedded_path)
            if segments:
                _progress(options, "已使用内置字幕作为源字幕", 48)
                return segments, "embedded"
            if options.source == "embedded":
                raise MediaError("Embedded subtitle stream was found but produced no SRT segments.")
        elif options.source == "embedded":
            raise MediaError("No embedded subtitle stream found in the input video.")

    if options.source in {"auto", "audio"}:
        audio_path = asset_cache.audio_path(video_fingerprint)
        if audio_path.exists() and audio_path.stat().st_size > 0:
            _progress(options, "使用缓存音频", 34)
        else:
            audio_path.parent.mkdir(parents=True, exist_ok=True)
            _progress(options, "正在抽取音频", 28)
            try:
                extract_audio(input_path, audio_path, options.cancel_check)
            except Exception:
                audio_path.unlink(missing_ok=True)
                raise
            _progress(options, "音频抽取完成，开始语音转写", 34)
        transcript_path = asset_cache.transcript_path(
            video_fingerprint,
            options.transcriber,
            options.source_lang,
            options.whisper_model,
        )
        if transcript_path.exists():
            segments = read_srt(transcript_path)
            if segments:
                _progress(options, "使用缓存的语音转写字幕", 48)
                return segments, f"audio-{options.transcriber}-cache"
        if options.transcriber == "local-whisper":
            segments = transcribe_with_whisper_cpp(
                audio_path,
                options.source_lang,
                options.whisper_model,
                options.cancel_check,
            )
            source_kind = "audio-local-whisper"
            _progress(options, "本地 Whisper 转写完成", 48)
        else:
            segments = transcribe_audio(audio_path, options.source_lang)
            source_kind = "audio"
            _progress(options, "OpenAI 转写完成", 48)
        transcript_path.parent.mkdir(parents=True, exist_ok=True)
        write_srt(transcript_path, segments)
        return segments, source_kind

    raise MediaError("No usable subtitle source found. Try --source audio.")


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
