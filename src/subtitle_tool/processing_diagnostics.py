"""根据实际来源配置和已有阶段产物构建预估。
Build estimates from the actual source configuration and existing stage artifacts.
"""
from __future__ import annotations

from .local_whisper import DEFAULT_VAD_MODEL_PATH
from .processing_estimate import estimate_processing


def estimate_input(options, video_path, cache, fingerprint, duration, video_mode):
    profile = "standard"
    if options.transcriber == "local-whisper" and options.whisper_use_vad:
        profile = f"vad:{options.whisper_vad_model or DEFAULT_VAD_MODEL_PATH}"
    transcript = cache.transcript_path(fingerprint, options.transcriber, options.source_lang, options.whisper_model, profile)
    language = options.source_lang
    embedded_kind = f"embedded-{language}" if language and language != "auto" else "embedded"
    embedded = cache.source_subtitle_path(fingerprint, embedded_kind)
    def present(path):
        return path.is_file() and path.stat().st_size > 0
    stage_cache = {"audio": present(cache.audio_path(fingerprint))}
    if options.source in {"audio", "auto"}:
        stage_cache["transcription"] = present(transcript) and not options.force_regenerate
    if options.source in {"embedded", "auto"}:
        stage_cache["source"] = present(embedded)
    history = cache.root / "analysis" / "processing-estimates.json"
    estimate = estimate_processing(
        duration, video_path.stat().st_size, options.target_langs,
        video_mode if options.embed_subtitles else "none", stage_cache["audio"],
        source_mode=options.source, transcriber=options.transcriber,
        translator=options.translator, stage_cache=stage_cache,
        encoding_profile=options.subtitle_encoding_profile, history_path=history,
    )
    return estimate, history
