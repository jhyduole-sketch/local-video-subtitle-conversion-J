from __future__ import annotations

import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from random import randint
import re
from typing import Callable

from .errors import CancellationError, MediaError, SubtitleToolError
from .local_translate import translate_segments_locally
from .local_whisper import transcribe_with_whisper_cpp
from .media import extract_audio, extract_first_subtitle, find_subtitle_streams, mux_subtitle_track
from .openai_client import transcribe_audio, translate_segments, translate_segments_with_zai
from .srt import SubtitleSegment, read_srt, replace_text, write_srt
from .talksmith import extract_scenario_id, is_talksmith_url, is_url, resolve_talksmith_input
from .youtube import download_youtube_video, extract_youtube_id, is_youtube_url


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


@dataclass(frozen=True)
class PipelineResult:
    source_subtitle_path: Path | None
    translated_paths: dict[str, Path]
    failed_languages: dict[str, str]
    source_kind: str
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
    if options.translator not in {"openai", "z-ai", "local-transformer"}:
        raise SubtitleToolError("--translator must be one of: openai, z-ai, local-transformer.")

    timestamp = _timestamp_suffix()
    output_stem = _base_output_stem(_input_output_stem(options.input_value), timestamp)
    task_out_dir = options.out_dir / output_stem
    task_out_dir.mkdir(parents=True, exist_ok=True)
    _progress(options, "准备输入视频", 5)
    input_path, downloaded_video_path = _resolve_input(options, task_out_dir, timestamp)
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
    source_segments, source_kind = _load_source_segments(options, input_path)
    _progress(options, f"得到源字幕片段: {len(source_segments)} 条", 52)
    lang_suffix = options.source_lang or "auto"
    source_path = task_out_dir / f"{output_stem}.{timestamp}.source.{lang_suffix}.srt"
    write_srt(source_path, source_segments)
    _progress(options, f"源字幕已输出: {source_path.name}", 56)

    translated_paths: dict[str, Path] = {}
    subtitled_video_paths: dict[str, Path] = {}
    failed_languages: dict[str, str] = {}
    total_targets = max(len(options.target_langs), 1)
    for target_index, target_lang in enumerate(options.target_langs, start=1):
        try:
            base_percent = 56 + round((target_index - 1) * 36 / total_targets)
            translated_percent = 56 + round((target_index - 0.45) * 36 / total_targets)
            output_percent = 56 + round(target_index * 36 / total_targets)
            _progress(options, f"开始翻译: {target_lang}", base_percent)
            if options.translator == "local-transformer":
                translations = translate_segments_locally(
                    source_segments, options.source_lang, target_lang
                )
            elif options.translator == "z-ai":
                translations = translate_segments_with_zai(
                    source_segments,
                    target_lang=target_lang,
                    source_lang=options.source_lang,
                    progress_callback=lambda message: _progress(
                        options, message, min(translated_percent - 1, base_percent + 1)
                    ),
                )
            else:
                translations = translate_segments(
                    source_segments,
                    target_lang=target_lang,
                    source_lang=options.source_lang,
                )
            _progress(options, f"翻译完成: {target_lang}", translated_percent)
            translated = replace_text(source_segments, translations)
            output_path = task_out_dir / f"{output_stem}.{timestamp}.{target_lang}.srt"
            write_srt(output_path, translated)
            translated_paths[target_lang] = output_path
            _progress(options, f"字幕文件已输出: {output_path.name}", output_percent)
            if options.embed_subtitles:
                if options.avoid_subtitle_overlap:
                    _progress(
                        options,
                        "已选择避免遮挡原字幕；当前 MP4 软字幕位置仍由播放器控制",
                        min(output_percent + 1, 95),
                    )
                video_output_path = task_out_dir / f"{output_stem}.{timestamp}.{target_lang}.default-sub.mp4"
                _progress(options, f"开始合成软字幕视频: {target_lang}", min(output_percent + 1, 95))
                mux_subtitle_track(
                    input_path,
                    output_path,
                    video_output_path,
                    _mp4_language_code(target_lang),
                    target_lang,
                )
                subtitled_video_paths[target_lang] = video_output_path
                _progress(options, f"软字幕视频已输出: {video_output_path.name}", min(output_percent + 3, 96))
        except CancellationError:
            raise
        except Exception as exc:
            failed_languages[target_lang] = str(exc)
            _progress(options, f"翻译失败: {target_lang}: {exc}", 92)

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
        downloaded_video_path=downloaded_video_path,
        subtitled_video_paths=subtitled_video_paths,
    )


def _resolve_input(
    options: PipelineOptions, task_out_dir: Path, timestamp: str
) -> tuple[Path, Path | None]:
    if is_talksmith_url(options.input_value):
        _progress(options, "解析 TalkSmith 链接并下载视频", 8)
        downloaded_path = resolve_talksmith_input(
            options.input_value, task_out_dir, options.force_download, timestamp
        )
        return downloaded_path, downloaded_path

    if is_youtube_url(options.input_value):
        _progress(options, "解析 YouTube 链接并下载视频", 8)
        video = download_youtube_video(
            options.input_value, task_out_dir, options.force_download, timestamp
        )
        return video.path, video.path

    if is_url(options.input_value):
        raise SubtitleToolError(
            "Unsupported URL. v1 supports TalkSmith share URLs and YouTube URLs."
        )

    input_path = Path(options.input_value).expanduser().resolve()
    _progress(options, "检查本地视频文件", 8)
    if not input_path.exists():
        raise SubtitleToolError(f"Input video does not exist: {input_path}")
    return input_path, None


def _load_source_segments(
    options: PipelineOptions, input_path: Path
) -> tuple[list[SubtitleSegment], str]:
    if options.source in {"auto", "embedded"}:
        _progress(options, "检查视频内置字幕轨", 22)
        streams = find_subtitle_streams(input_path)
        if streams:
            _progress(options, "发现内置字幕，正在导出", 30)
            with tempfile.TemporaryDirectory() as tmpdir:
                extracted_path = Path(tmpdir) / "embedded.srt"
                extract_first_subtitle(input_path, extracted_path)
                segments = read_srt(extracted_path)
            if segments:
                _progress(options, "已使用内置字幕作为源字幕", 48)
                return segments, "embedded"
            if options.source == "embedded":
                raise MediaError("Embedded subtitle stream was found but produced no SRT segments.")
        elif options.source == "embedded":
            raise MediaError("No embedded subtitle stream found in the input video.")

    if options.source in {"auto", "audio"}:
        with tempfile.TemporaryDirectory() as tmpdir:
            audio_path = Path(tmpdir) / "audio.mp3"
            _progress(options, "正在抽取音频", 28)
            extract_audio(input_path, audio_path)
            _progress(options, "音频抽取完成，开始语音转写", 34)
            if options.transcriber == "local-whisper":
                segments = transcribe_with_whisper_cpp(
                    audio_path, options.source_lang, options.whisper_model
                )
                _progress(options, "本地 Whisper 转写完成", 48)
                return segments, "audio-local-whisper"
            segments = transcribe_audio(audio_path, options.source_lang)
            _progress(options, "OpenAI 转写完成", 48)
            return segments, "audio"

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


def _progress(options: PipelineOptions, message: str, percent: int) -> None:
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
    if is_talksmith_url(input_value):
        return extract_scenario_id(input_value)
    return Path(input_value).expanduser().stem or "video"
