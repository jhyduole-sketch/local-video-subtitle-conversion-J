from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

from .errors import MediaError, SubtitleToolError
from .local_translate import translate_segments_locally
from .local_whisper import transcribe_with_whisper_cpp
from .media import extract_audio, extract_first_subtitle, find_subtitle_streams, mux_subtitle_track
from .openai_client import transcribe_audio, translate_segments
from .srt import SubtitleSegment, read_srt, replace_text, write_srt
from .talksmith import is_talksmith_url, is_url, resolve_talksmith_input
from .youtube import download_youtube_video, is_youtube_url


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


@dataclass(frozen=True)
class PipelineResult:
    source_subtitle_path: Path | None
    translated_paths: dict[str, Path]
    failed_languages: dict[str, str]
    source_kind: str
    downloaded_video_path: Path | None = None
    subtitled_video_paths: dict[str, Path] | None = None


def run_pipeline(options: PipelineOptions) -> PipelineResult:
    if options.output_format != "srt":
        raise SubtitleToolError("v1 only supports --format srt.")
    if options.source not in {"auto", "embedded", "audio"}:
        raise SubtitleToolError("--source must be one of: auto, embedded, audio.")
    if options.transcriber not in {"openai", "local-whisper"}:
        raise SubtitleToolError("--transcriber must be one of: openai, local-whisper.")
    if options.translator not in {"openai", "local-transformer"}:
        raise SubtitleToolError("--translator must be one of: openai, local-transformer.")

    options.out_dir.mkdir(parents=True, exist_ok=True)
    input_path, downloaded_video_path = _resolve_input(options)

    if options.download_only:
        return PipelineResult(
            source_subtitle_path=None,
            translated_paths={},
            failed_languages={},
            source_kind="download",
            downloaded_video_path=downloaded_video_path or input_path,
        )

    source_segments, source_kind = _load_source_segments(options, input_path)
    lang_suffix = options.source_lang or "auto"
    source_path = options.out_dir / f"source.{lang_suffix}.srt"
    write_srt(source_path, source_segments)

    translated_paths: dict[str, Path] = {}
    subtitled_video_paths: dict[str, Path] = {}
    failed_languages: dict[str, str] = {}
    for target_lang in options.target_langs:
        try:
            if options.translator == "local-transformer":
                translations = translate_segments_locally(
                    source_segments, options.source_lang, target_lang
                )
            else:
                translations = translate_segments(
                    source_segments,
                    target_lang=target_lang,
                    source_lang=options.source_lang,
                )
            translated = replace_text(source_segments, translations)
            output_path = options.out_dir / f"subtitles.{target_lang}.srt"
            write_srt(output_path, translated)
            translated_paths[target_lang] = output_path
            if options.embed_subtitles:
                video_output_path = options.out_dir / f"{input_path.stem}.{target_lang}.default-sub.mp4"
                mux_subtitle_track(
                    input_path,
                    output_path,
                    video_output_path,
                    _mp4_language_code(target_lang),
                    target_lang,
                )
                subtitled_video_paths[target_lang] = video_output_path
        except Exception as exc:
            failed_languages[target_lang] = str(exc)

    if not translated_paths and failed_languages:
        details = "; ".join(
            f"{language}: {message}" for language, message in failed_languages.items()
        )
        raise SubtitleToolError(f"All subtitle translations failed. {details}")

    return PipelineResult(
        source_subtitle_path=source_path,
        translated_paths=translated_paths,
        failed_languages=failed_languages,
        source_kind=source_kind,
        downloaded_video_path=downloaded_video_path,
        subtitled_video_paths=subtitled_video_paths,
    )


def _resolve_input(options: PipelineOptions) -> tuple[Path, Path | None]:
    if is_talksmith_url(options.input_value):
        downloaded_path = resolve_talksmith_input(
            options.input_value, options.out_dir, options.force_download
        )
        return downloaded_path, downloaded_path

    if is_youtube_url(options.input_value):
        video = download_youtube_video(
            options.input_value, options.out_dir, options.force_download
        )
        return video.path, video.path

    if is_url(options.input_value):
        raise SubtitleToolError(
            "Unsupported URL. v1 supports TalkSmith share URLs and YouTube URLs."
        )

    input_path = Path(options.input_value).expanduser().resolve()
    if not input_path.exists():
        raise SubtitleToolError(f"Input video does not exist: {input_path}")
    return input_path, None


def _load_source_segments(
    options: PipelineOptions, input_path: Path
) -> tuple[list[SubtitleSegment], str]:
    if options.source in {"auto", "embedded"}:
        streams = find_subtitle_streams(input_path)
        if streams:
            with tempfile.TemporaryDirectory() as tmpdir:
                extracted_path = Path(tmpdir) / "embedded.srt"
                extract_first_subtitle(input_path, extracted_path)
                segments = read_srt(extracted_path)
            if segments:
                return segments, "embedded"
            if options.source == "embedded":
                raise MediaError("Embedded subtitle stream was found but produced no SRT segments.")
        elif options.source == "embedded":
            raise MediaError("No embedded subtitle stream found in the input video.")

    if options.source in {"auto", "audio"}:
        with tempfile.TemporaryDirectory() as tmpdir:
            audio_path = Path(tmpdir) / "audio.mp3"
            extract_audio(input_path, audio_path)
            if options.transcriber == "local-whisper":
                return (
                    transcribe_with_whisper_cpp(
                        audio_path, options.source_lang, options.whisper_model
                    ),
                    "audio-local-whisper",
                )
            return transcribe_audio(audio_path, options.source_lang), "audio"

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
