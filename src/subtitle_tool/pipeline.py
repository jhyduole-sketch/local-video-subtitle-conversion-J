from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from random import randint
import re
from typing import Callable

from .errors import CancellationError, MediaError, SubtitleToolError
from .asset_cache import AssetCache
from .local_translate import normalize_lang, translate_segments_locally, translate_segments_with_nllb
from .local_whisper import transcribe_with_whisper_cpp
from .media import extract_audio, extract_first_subtitle, find_subtitle_streams, mux_subtitle_track
from .openai_client import transcribe_audio, translate_segments, translate_segments_with_zai
from .process_control import CancelCheck
from .srt import SubtitleSegment, read_srt, replace_text, write_srt
from .talksmith import extract_scenario_id, is_talksmith_url, is_url, resolve_talksmith_input
from .translation_cache import TranslationCache
from .youtube import (
    download_bilibili_video,
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


def run_pipeline(options: PipelineOptions) -> PipelineResult:
    _progress(options, "检查参数", 2)
    if options.output_format != "srt":
        raise SubtitleToolError("v1 only supports --format srt.")
    if options.source not in {"auto", "embedded", "audio"}:
        raise SubtitleToolError("--source must be one of: auto, embedded, audio.")
    if options.transcriber not in {"openai", "local-whisper"}:
        raise SubtitleToolError("--transcriber must be one of: openai, local-whisper.")
    if options.translator not in {"openai", "z-ai", "local-transformer", "local-nllb"}:
        raise SubtitleToolError(
            "--translator must be one of: openai, z-ai, local-transformer, local-nllb."
        )

    timestamp = _timestamp_suffix()
    output_stem = _base_output_stem(_input_output_stem(options.input_value), timestamp)
    task_out_dir = options.out_dir / f"{output_stem}.{timestamp}"
    task_out_dir.mkdir(parents=True, exist_ok=True)
    asset_cache = AssetCache(options.out_dir / ".subtitle-tool-cache")
    _progress(options, "准备输入视频", 5)
    input_path, downloaded_video_path = _resolve_input(
        options, task_out_dir, timestamp, asset_cache
    )
    _progress(options, f"视频已准备: {input_path.name}", 15)

    if options.download_only:
        _progress(options, "下载任务完成", 100)
        return PipelineResult(
            source_subtitle_path=None,
            translated_paths={},
            failed_languages={},
            source_kind="download",
            downloaded_video_path=downloaded_video_path or input_path,
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
    translation_cache = TranslationCache(
        options.out_dir / ".subtitle-tool-cache" / "translations"
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
                translated = replace_text(source_segments, translations)
                output_path = task_out_dir / f"{output_stem}.{timestamp}.{target_lang}.srt"
                write_srt(output_path, translated)
                translated_paths[target_lang] = output_path
                _progress(options, f"字幕文件已输出: {output_path.name}", output_percent)
                if mux_executor:
                    if options.avoid_subtitle_overlap:
                        _progress(
                            options,
                            "已选择避免遮挡原字幕；当前 MP4 软字幕位置仍由播放器控制",
                            min(output_percent + 1, 95),
                        )
                    video_output_path = task_out_dir / f"{output_stem}.{timestamp}.{target_lang}.default-sub.mp4"
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
                f"软字幕视频已输出: {video_output_path.name}",
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
    if options.translator == "local-nllb":
        return (
            translate_segments_with_nllb(
                source_segments, options.source_lang, target_lang
            ),
            "本地 NLLB",
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
            source_segments, options.source_lang, target_lang
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
        raise SubtitleToolError(
            "Unsupported URL. v1 supports TalkSmith share URLs, YouTube URLs, and Bilibili URLs."
        )

    input_path = Path(options.input_value).expanduser().resolve()
    _progress(options, "检查本地视频文件", 8)
    if not input_path.exists():
        raise SubtitleToolError(f"Input video does not exist: {input_path}")
    return input_path, None


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
