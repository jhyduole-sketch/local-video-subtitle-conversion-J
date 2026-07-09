# subtitle-tool

一个本地命令行工具：输入英语或日语视频，或 TalkSmith 分享页 URL，优先读取视频内置字幕；如果没有字幕，就根据音频转写生成源字幕；再翻译成一个或多个目标语言，输出 `.srt` 字幕文件。

v1 只输出外挂字幕文件，不把字幕烧录进视频。

## Requirements

- Python 3.9+
- `ffmpeg` 和 `ffprobe`
- OpenAI API key

macOS 可以用 Homebrew 安装视频工具：

```bash
brew install ffmpeg
```

## Setup

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
export OPENAI_API_KEY="你的 API key"
```

也可以在当前目录创建 `.env`：

```bash
OPENAI_API_KEY=你的 API key
```

## Usage

```bash
subtitle-tool input.mp4 --source-lang en --target-lang zh-CN --target-lang ja --out-dir output
```

也可以直接传 TalkSmith 分享页 URL，工具会先下载视频再转字幕：

```bash
subtitle-tool 'https://service.talk-smith.com/s?id=cmdfs4a5k265w0z1anf9fk08z' --source-lang ja --target-lang zh-CN --out-dir output
```

不用 OpenAI key，只生成原文字幕：

```bash
subtitle-tool input.mp4 --source-lang ja --transcriber local-whisper --out-dir output
```

只下载视频、不生成字幕：

```bash
subtitle-tool 'https://service.talk-smith.com/s?id=cmdfs4a5k265w0z1anf9fk08z' --download-only --out-dir output
```

YouTube 链接也可以处理。下面这个命令会下载视频、用本地 Whisper 识别中文语音、用本地模型翻成日语，并输出带日语字幕轨的视频：

```bash
subtitle-tool 'https://www.youtube.com/watch?v=gaaarGhydLk' --source-lang zh --target-lang ja --transcriber local-whisper --translator local-transformer --embed-subtitles --out-dir output
```

常用参数：

- `input`: 视频文件路径、`https://service.talk-smith.com/s?id=...`，或 YouTube 链接
- `--target-lang`: 目标语言，可重复传入，例如 `zh-CN`, `en`, `ja`；不传则只输出原文字幕
- `--source-lang`: 源语言，建议传 `en` 或 `ja`
- `--out-dir`: 输出目录，默认 `./output`
- `--source`: `auto`, `embedded`, `audio`，默认 `auto`
- `--format`: v1 只支持 `srt`
- `--force-download`: TalkSmith 视频已存在时也重新下载
- `--download-only`: 只下载 TalkSmith 视频，不转写、不翻译
- `--transcriber`: `openai` 或 `local-whisper`，默认 `openai`
- `--whisper-model`: whisper.cpp 模型路径，默认 `models/ggml-base.bin`
- `--translator`: `openai` 或 `local-transformer`，默认 `openai`
- `--embed-subtitles`: 输出带翻译字幕轨的 MP4 视频

输出示例：

```text
output/source.en.srt
output/subtitles.zh-CN.srt
output/subtitles.ja.srt
output/downloads/cmdfs4a5k265w0z1anf9fk08z.mp4
```

## Notes

- `auto` 模式会先找视频内置字幕，找不到再抽取音频并调用 OpenAI 转写。
- 翻译会保留原始字幕时间轴，只替换字幕文本。
- 可以通过环境变量覆盖模型：
  - `SUBTITLE_TOOL_TRANSCRIBE_MODEL`，默认 `whisper-1`
  - `SUBTITLE_TOOL_TRANSLATE_MODEL`，默认 `gpt-4.1-mini`
