"""按成本顺序选择字幕来源，后续来源失败时保留可用候选。

依赖由流水线兼容入口提供，便于替换媒体和模型边界而无需加载重型引擎。

Cost-ordered source selection, retaining usable candidates on failure.

The dependency facade is supplied by pipeline's compatibility entry points so
callers can still replace media/model boundaries without loading heavy engines.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from .atomic_files import atomic_output_path, commit_output
from .errors import CancellationError, MediaError
from .source_quality import score_source_segments
from .srt import SubtitleSegment

if TYPE_CHECKING:
    from .pipeline import PipelineOptions
    from .asset_cache import AssetCache


def load_source_segments(options: PipelineOptions, input_path: Path, asset_cache: AssetCache, *, dependencies) -> tuple[list[SubtitleSegment], str]:
    d = dependencies
    fingerprint = asset_cache.file_fingerprint(input_path)
    candidates = []
    errors = []
    sources = ("embedded", "audio", "screen-ocr") if options.source == "auto" else (options.source,)
    for source in sources:
        d._progress(options, f"检查字幕来源: {source}", 22)
        try:
            if source == "embedded":
                result = _embedded(options, input_path, asset_cache, fingerprint, d)
            elif source == "audio":
                result = _audio(options, input_path, asset_cache, fingerprint, d)
            else:
                result = d._load_screen_ocr_segments(options, input_path, asset_cache, fingerprint)
            segments, kind = result
            if not any(s.text.strip() for s in segments):
                raise MediaError(f"{source} 没有可用字幕文字")
            quality = score_source_segments(segments, options.source_lang)
            candidates.append((quality.score, segments, kind))
            suspicious = source == "audio" and d.is_suspicious_transcript(segments)
            if quality.score >= 60 and not suspicious:
                return segments, kind
            if options.source != "auto":
                d._progress(options, "字幕质量偏低，按手动选择继续使用", 48)
                return segments, kind
            d._progress(options, f"{source} 字幕质量偏低（{quality.score} 分），继续比较其他来源", 34)
        except CancellationError:
            raise
        except Exception as exc:
            if options.source != "auto":
                raise
            errors.append(f"{source}: {exc}")
            d._progress(options, f"{source} 未得到可用字幕，继续检查其他来源: {exc}", 34)
    if candidates:
        score, segments, kind = max(candidates, key=lambda candidate: candidate[0])
        d._progress(options, f"使用现有最佳字幕来源 {kind}（{score} 分），请检查字幕质量", 48)
        return segments, kind
    raise MediaError("No usable subtitle source found. " + " | ".join(errors))


def _language_matches(actual, expected):
    aliases = {"eng": "en", "zho": "zh", "chi": "zh", "jpn": "ja", "kor": "ko", "fra": "fr", "fre": "fr", "deu": "de", "ger": "de", "spa": "es", "vie": "vi"}
    def base(value):
        value = (value or "").lower().replace("_", "-").split("-")[0]
        return aliases.get(value, value)
    return bool(actual and expected and base(actual) == base(expected))


def _embedded(options, video, cache, fingerprint, d):
    # 缓存身份包含语言，避免把旧的未指定轨道当成新请求语言的字幕。
    # Language is part of the cache identity; an old unspecified track must not
    # silently become a newly requested language.
    language = options.source_lang
    cache_kind = f"embedded-{language}" if language and language != "auto" else "embedded"
    path = cache.source_subtitle_path(fingerprint, cache_kind)
    if path.exists():
        segments = d.read_srt(path)
        if any(s.text.strip() for s in segments):
            return segments, "embedded-cache"
    streams = d.find_subtitle_streams(video, options.cancel_check)
    if not streams:
        raise MediaError("No embedded subtitle stream found in the input video.")
    stream = next((s for s in streams if _language_matches(s.language, language)), streams[0])
    temporary_path = atomic_output_path(path)
    try:
        if stream is streams[0]:
            d.extract_first_subtitle(video, temporary_path, options.cancel_check)
        else:
            d.extract_first_subtitle(video, temporary_path, options.cancel_check, stream_index=stream.index)
        segments = d.read_srt(temporary_path)
        if not any(segment.text.strip() for segment in segments):
            raise MediaError("Embedded subtitle stream produced no usable SRT segments.")
        if options.cancel_check and options.cancel_check():
            raise CancellationError("Task cancelled")
        # 仅在字幕有效且未取消后发布缓存，中断文件不能成为可复用结果。
        # Publish the cache only after validation and cancellation checks; interrupted files are not reusable.
        commit_output(temporary_path, path)
        return segments, "embedded"
    finally:
        temporary_path.unlink(missing_ok=True)


def _audio(options, video, cache, fingerprint, d):
    profile = "standard"
    if options.transcriber == "local-whisper" and options.whisper_use_vad:
        profile = f"vad:{options.whisper_vad_model or d.DEFAULT_VAD_MODEL_PATH}"
    transcript = cache.transcript_path(fingerprint, options.transcriber, options.source_lang, options.whisper_model, profile)
    if transcript.exists():
        segments = d.read_srt(transcript)
        if any(s.text.strip() for s in segments):
            d._progress(options, "使用缓存的语音转写字幕", 48)
            return segments, f"audio-{options.transcriber}-cache"
    audio = cache.audio_path(fingerprint)
    if not audio.exists() or audio.stat().st_size == 0:
        audio.parent.mkdir(parents=True, exist_ok=True)
        d._progress(options, "正在抽取音频", 28)
        try:
            d.extract_audio(video, audio, options.cancel_check)
        except BaseException:
            audio.unlink(missing_ok=True)
            raise
    if options.transcriber == "local-whisper":
        segments = d._heavy_call(options, "本地 Whisper 转写", lambda: d.transcribe_with_whisper_cpp(
            audio, options.source_lang, options.whisper_model, options.cancel_check,
            progress_callback=lambda message: d._progress(options, message, 40),
            use_gpu=options.whisper_use_gpu, use_vad=options.whisper_use_vad,
            vad_model_path=options.whisper_vad_model,
        ))
        kind = "audio-local-whisper"
    else:
        segments = d.transcribe_audio(audio, options.source_lang)
        kind = "audio"
    transcript.parent.mkdir(parents=True, exist_ok=True)
    d.write_srt(transcript, segments)
    return segments, kind
