from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .env import load_dotenv
from .errors import SubtitleToolError
from .pipeline import PipelineOptions, run_pipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="subtitle-tool",
        description="Generate translated SRT subtitles from embedded subtitles or video audio.",
    )
    parser.add_argument("input", help="Input video path or TalkSmith share URL.")
    parser.add_argument(
        "--target-lang",
        action="append",
        dest="target_langs",
        default=[],
        help="Target subtitle language, for example zh-CN, en, ja. Can be repeated. Omit to output only source subtitles.",
    )
    parser.add_argument(
        "--source-lang",
        default=None,
        help="Source language, for example en or ja. Recommended but optional.",
    )
    parser.add_argument(
        "--out-dir",
        default="output",
        help="Output directory. Defaults to ./output.",
    )
    parser.add_argument(
        "--source",
        choices=["auto", "embedded", "audio"],
        default="auto",
        help="Subtitle source strategy. Defaults to auto.",
    )
    parser.add_argument(
        "--format",
        choices=["srt"],
        default="srt",
        help="Subtitle output format. v1 supports only srt.",
    )
    parser.add_argument(
        "--force-download",
        action="store_true",
        help="Re-download TalkSmith videos even when a cached file exists.",
    )
    parser.add_argument(
        "--download-only",
        action="store_true",
        help="Download the TalkSmith video and skip subtitle generation.",
    )
    parser.add_argument(
        "--transcriber",
        choices=["openai", "local-whisper"],
        default="openai",
        help="Audio transcription engine. Use local-whisper to avoid OpenAI API keys.",
    )
    parser.add_argument(
        "--whisper-model",
        default=None,
        help="Path to a whisper.cpp GGML model, default models/ggml-base.bin.",
    )
    parser.add_argument(
        "--translator",
        choices=["openai", "z-ai", "local-transformer"],
        default="openai",
        help="Subtitle translation engine. Use z-ai with ZAI_API_KEY, or local-transformer to avoid API keys.",
    )
    parser.add_argument(
        "--embed-subtitles",
        action="store_true",
        help="Create MP4 files with translated subtitles embedded as default soft subtitle tracks.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv(Path.cwd() / ".env")
    parser = build_parser()
    args = parser.parse_args(argv)

    options = PipelineOptions(
        input_value=args.input,
        target_langs=args.target_langs,
        source_lang=args.source_lang,
        out_dir=Path(args.out_dir).expanduser().resolve(),
        source=args.source,
        output_format=args.format,
        force_download=args.force_download,
        download_only=args.download_only,
        transcriber=args.transcriber,
        whisper_model=Path(args.whisper_model).expanduser().resolve()
        if args.whisper_model
        else None,
        translator=args.translator,
        embed_subtitles=args.embed_subtitles,
    )

    try:
        result = run_pipeline(options)
    except SubtitleToolError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if result.downloaded_video_path:
        print(f"Downloaded video: {result.downloaded_video_path}")
    if result.source_subtitle_path:
        print(f"Source subtitles ({result.source_kind}): {result.source_subtitle_path}")
    for language, path in result.translated_paths.items():
        print(f"Translated subtitles [{language}]: {path}")
    for language, path in (result.subtitled_video_paths or {}).items():
        print(f"Subtitled video [{language}]: {path}")
    for language, message in result.failed_languages.items():
        print(f"Translation failed [{language}]: {message}", file=sys.stderr)
    return 0 if not result.failed_languages else 2


if __name__ == "__main__":
    raise SystemExit(main())
