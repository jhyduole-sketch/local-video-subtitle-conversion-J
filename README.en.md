# Local Multilingual Video Subtitle Tool

[中文首页](README.md) · [Full Chinese Guide](docs/使用指南.md) · [Release Notes](docs/更新记录.md)

A local-first subtitle workflow for macOS. Give it a local video, an uploaded file, or a public video URL; it extracts embedded subtitles or transcribes the audio, translates the timeline into one or more languages, and produces SRT files plus optional soft-subtitle or burned-in MP4 videos.

The project includes both a local Web UI and a CLI.

The Web service restricts local paths to server-configured directories and rejects cross-site requests. LAN mode requires `SUBTITLE_TOOL_WEB_TOKEN` (at least 24 characters); browser access uses an HttpOnly session cookie. Uploads are streamed with a default 2 GiB limit (`--max-upload-mb`), and task inputs are retained for resume. Add trusted directories using `--allow-input-dir` and `--allow-output-dir`.

Source selection now respects embedded track languages and retains manual choices. Translation fallback preserves completed batches and checks cancellation between batches. Estimates show a range calibrated against local successful runs; cache identity hashes the full video content. Existing fingerprint-based analysis caches are rebuilt on first use after this upgrade.

- [Development and maintenance (bilingual architecture, comment convention, and verification)](docs/开发与维护.md)

## Main Features

- Local files, browser uploads, YouTube, Bilibili, and best-effort public URL downloads.
- Embedded subtitle extraction with automatic fallback to audio transcription.
- Local whisper.cpp or OpenAI speech-to-text.
- z.ai, OpenAI, local Chinese/Japanese/English models, and NLLB 1.3B multilingual translation.
- Translation validation, sentence-level retry, rate-limit handling, engine fallback, and cache reuse.
- Multiple target languages in a single job.
- SRT, switchable soft-subtitle MP4, or fixed-position burned-in subtitle MP4 output.
- A multi-language soft-subtitle job muxes all tracks into one MP4 instead of copying the video once per language.
- Original-subtitle position detection and placement of new burned-in subtitles above or below it.
- Browser-based video preview, synchronized subtitle editing, and video regeneration.
- Live progress, timestamps, cancellation, persistent job history, resume support, and categorized caches.
- Confirmed cleanup actions for finished job history, individual cache categories, or all caches without deleting generated outputs.
- Duplicate-job protection across repeated clicks, page refreshes, and multiple LAN clients.
- A local processing-time estimate, source-subtitle quality score, and per-language translation fallback record.
- Safe local UI preferences for non-sensitive defaults only; API keys, cookies, and passwords are never stored there.
- Download failures are categorized as DRM, login/Cookie, unsupported page, or network issues. The app does not read browser cookies or bypass protection.

## Requirements

- macOS
- Python 3.9+
- FFmpeg and ffprobe
- `ffmpeg-full` for fixed-position burned-in subtitles
- `yt-dlp` for supported remote URLs
- whisper.cpp and a GGML model for local transcription
- `transformers`, `sentencepiece`, `torch`, and cached models for local translation

Install the common tools with Homebrew:

```bash
brew install ffmpeg
brew install ffmpeg-full
brew install whisper-cpp
brew install yt-dlp
```

Install Python dependencies:

```bash
python3 -m pip install -e .
python3 -m pip install transformers sentencepiece torch protobuf
```

Download the base Whisper model:

```bash
mkdir -p models
curl -L https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin -o models/ggml-base.bin
```

## Optional API Configuration

```bash
cp .env.example .env
```

Fill in the providers you want to use:

```text
OPENAI_API_KEY=
ZAI_API_KEY=
ZAI_API_BASE=https://open.bigmodel.cn/api/paas/v4/
ZAI_MODEL=glm-4.7-flash
```

Cloud API keys are not required when both transcription and translation run locally.

## Start the Web UI

Local access only:

```bash
env PYTHONPATH=src python3 -m subtitle_tool.web --host 127.0.0.1 --port 7860
```

Open [http://127.0.0.1:7860](http://127.0.0.1:7860).

Trusted local network access:

```bash
env PYTHONPATH=src python3 -m subtitle_tool.web --host 0.0.0.0 --port 7860
```

Set `SUBTITLE_TOOL_WEB_TOKEN` before starting LAN mode and enter it on the access page. Use the machine's LAN IP address; the HTTP service is intended for a trusted local network.

## CLI Example

Translate a Japanese video into Chinese and create a subtitle video:

```bash
env PYTHONPATH=src python3 -m subtitle_tool.cli input.mp4 \
  --source-lang ja \
  --target-lang zh-CN \
  --transcriber local-whisper \
  --translator z-ai \
  --embed-subtitles \
  --out-dir output
```

Repeat `--target-lang` to generate multiple languages in one job.

## Outputs

Each job gets a timestamped directory:

```text
output/<video-name>.<timestamp>/
  <video-name>.<timestamp>.source.<language>.srt
  <video-name>.<timestamp>.<target-language>.srt
  <video-name>.<timestamp>.<target-language>.default-sub.mp4
  <video-name>.<timestamp>.<target-language>.fixed-sub.mp4
  <video-name>.<timestamp>.multilingual.default-sub.mp4
```

- `*.srt`: external subtitle file.
- `*.default-sub.mp4`: switchable soft subtitle; the original video stream is preserved.
- `*.fixed-sub.mp4`: burned-in subtitle at a stable position; video re-encoding is required.
- `*.multilingual.default-sub.mp4`: one original-quality video with multiple switchable subtitle tracks.

Use IINA or VLC to verify soft subtitles. QuickTime may not display some MP4 subtitle tracks even when they are present.

## Documentation

- [Chinese project overview](README.md)
- [Full Chinese user guide](docs/使用指南.md)
- [Chinese release notes](docs/更新记录.md)
- [Performance and task-safety update](docs/2026-07-13-performance-and-task-safety.md)

## Limitations

- Burned-in subtitle OCR currently ships with a macOS Vision engine; other platforms need another compatible engine.
- Generic URL downloads do not bypass login, DRM, payment, or regional restrictions.
- Small local transcription and translation models prioritize speed over maximum quality.
- Burned-in subtitles require video re-encoding and can take a long time for high-resolution videos.
- Job state and caches remain on the current computer and are not synchronized between machines.
