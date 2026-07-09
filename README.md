# local-video-subtitle-conversion-J

一个本地命令行字幕工具，用来把视频里的语音或已有字幕转成新的字幕语言，并可输出带字幕轨的 MP4 视频。

当前版本重点支持：

- 本地视频文件
- TalkSmith 分享页 URL
- YouTube 视频 URL
- 本地 Whisper 语音识别，不需要 OpenAI key
- 本地 Transformer 翻译模型，不需要 OpenAI key
- OpenAI API 转写/翻译作为可选方案
- 输出 `.srt` 字幕文件
- 输出带默认软字幕轨的 MP4 视频

> 注意：当前输出的是“软字幕轨”，不是硬烧录到画面像素里的字幕。播放器如果没有自动显示，请手动打开字幕轨。

## 功能概览

### 输入来源

工具的 `input` 参数可以是：

- 本地视频路径，例如 `input.mp4`
- TalkSmith 链接，例如 `https://service.talk-smith.com/s?id=...`
- YouTube 链接，例如 `https://www.youtube.com/watch?v=...`

TalkSmith 和 YouTube 输入会先下载视频到 `output/`，再进入字幕处理流程。

### 字幕来源

默认 `--source auto`：

- 优先读取视频内置字幕轨
- 如果没有字幕轨，则抽取音频并语音识别

也可以指定：

- `--source embedded`：只使用视频内置字幕
- `--source audio`：强制使用音频识别

### 转写方式

支持两种转写引擎：

- `--transcriber local-whisper`：使用本地 `whisper.cpp`，不需要 OpenAI key
- `--transcriber openai`：使用 OpenAI API，需要 `OPENAI_API_KEY`

推荐本地优先：

```bash
--transcriber local-whisper
```

### 翻译方式

支持两种翻译引擎：

- `--translator local-transformer`：使用本地 Hugging Face Transformer 模型，不需要 OpenAI key
- `--translator openai`：使用 OpenAI API，需要 `OPENAI_API_KEY`

当前本地翻译已验证的方向：

- `ja -> zh-CN`
- `zh` / `zh-CN -> ja`

### 输出内容

常见输出文件：

```text
output/source.zh.srt
output/source.ja.srt
output/subtitles.ja.srt
output/subtitles.zh-CN.srt
output/<video-id>.<lang>.default-sub.mp4
```

如果使用 `--embed-subtitles`，会额外输出一个带默认字幕轨的 MP4。

## 环境要求

- macOS
- Python 3.9+
- `ffmpeg` / `ffprobe`
- `yt-dlp`，处理 YouTube 链接时需要
- `whisper.cpp`，本地语音识别时需要
- whisper.cpp GGML 模型文件，例如 `models/ggml-base.bin`
- 本地翻译模型缓存，使用 `local-transformer` 时需要

### 安装系统工具

```bash
brew install ffmpeg
brew install whisper-cpp
brew install yt-dlp
```

### 安装 Python 依赖

```bash
python3 -m pip install openai
python3 -m pip install transformers sentencepiece torch protobuf
```

如果要使用可选的第三方翻译库：

```bash
python3 -m pip install deep-translator
```

### 下载 Whisper 模型

```bash
mkdir -p models
curl -L https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin -o models/ggml-base.bin
```

`ggml-base.bin` 速度和体积比较合适，但识别质量只是够用。质量更高可以换 `small` 或 `medium` 模型。

## 基本用法

所有命令建议在项目目录运行：

```bash
cd /Users/duole/DDeveloper/AI/codex-test/project3-codex
```

为了直接用源码运行，命令前加：

```bash
env PYTHONPATH=src
```

## 图形界面

可以启动本地网页界面：

```bash
env PYTHONPATH=src python3 -m subtitle_tool.web --host 127.0.0.1 --port 7860
```

或安装项目后运行：

```bash
subtitle-tool-web --host 127.0.0.1 --port 7860
```

浏览器打开：

```text
http://127.0.0.1:7860
```

界面支持：

- 输入本地视频路径、TalkSmith URL 或 YouTube URL
- 选择原语言和目标语言
- 选择内置字幕、音频识别或自动模式
- 选择本地 Whisper / OpenAI 转写
- 选择本地 Transformer / OpenAI 翻译
- 只下载视频、重新下载、输出带字幕轨 MP4
- 查看环境检查、任务日志和输出文件路径

图形界面默认使用本地 Whisper 和本地 Transformer，适合不配置 OpenAI key 的场景。

## 用法示例

### 1. 本地视频识别原文字幕

日语视频转日语字幕：

```bash
env PYTHONPATH=src python3 -m subtitle_tool.cli input.mp4 --source-lang ja --transcriber local-whisper --out-dir output
```

输出：

```text
output/source.ja.srt
```

### 2. TalkSmith 视频转中文字幕

```bash
env PYTHONPATH=src python3 -m subtitle_tool.cli 'https://service.talk-smith.com/s?id=cmdfs4a5k265w0z1anf9fk08z' --source-lang ja --target-lang zh-CN --transcriber local-whisper --translator local-transformer --embed-subtitles --out-dir output
```

输出：

```text
output/downloads/cmdfs4a5k265w0z1anf9fk08z.mp4
output/source.ja.srt
output/subtitles.zh-CN.srt
output/cmdfs4a5k265w0z1anf9fk08z.zh-CN.default-sub.mp4
```

### 3. YouTube 中文视频转日语字幕视频

```bash
env PYTHONPATH=src TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1 python3 -m subtitle_tool.cli 'https://www.youtube.com/watch?v=gaaarGhydLk' --source-lang zh --target-lang ja --transcriber local-whisper --translator local-transformer --embed-subtitles --out-dir output
```

输出：

```text
output/youtube/gaaarGhydLk.mp4
output/source.zh.srt
output/subtitles.ja.srt
output/gaaarGhydLk.ja.default-sub.mp4
```

### 4. 只下载视频

TalkSmith：

```bash
env PYTHONPATH=src python3 -m subtitle_tool.cli 'https://service.talk-smith.com/s?id=cmdfs4a5k265w0z1anf9fk08z' --download-only --out-dir output
```

YouTube：

```bash
env PYTHONPATH=src python3 -m subtitle_tool.cli 'https://www.youtube.com/watch?v=gaaarGhydLk' --download-only --out-dir output
```

### 5. 使用 OpenAI API

如果希望使用 OpenAI API 转写/翻译，先设置环境变量：

```bash
export OPENAI_API_KEY="你的 API key"
```

或在项目根目录创建 `.env`：

```bash
OPENAI_API_KEY=你的 API key
```

然后运行：

```bash
env PYTHONPATH=src python3 -m subtitle_tool.cli input.mp4 --source-lang ja --target-lang zh-CN --transcriber openai --translator openai --out-dir output
```

## 参数说明

```text
input
```

输入视频路径或 URL。支持：

- 本地视频
- TalkSmith 分享 URL
- YouTube URL

```text
--source-lang
```

源语言，例如：

- `ja`
- `zh`
- `zh-CN`
- `en`

本地 Whisper 建议显式传入源语言，识别更稳定。

```text
--target-lang
```

目标字幕语言，可重复传入。不传时只输出源语言字幕。

示例：

```bash
--target-lang ja
--target-lang zh-CN
```

```text
--source
```

字幕来源策略：

- `auto`：默认，先找内置字幕，没有就听音频
- `embedded`：只读取内置字幕
- `audio`：强制听音频识别

```text
--transcriber
```

语音识别引擎：

- `local-whisper`
- `openai`

```text
--translator
```

翻译引擎：

- `local-transformer`
- `openai`

```text
--embed-subtitles
```

输出带默认字幕轨的 MP4。

```text
--download-only
```

只下载远程视频，不生成字幕。

```text
--force-download
```

远程视频已经存在时也重新下载。

```text
--whisper-model
```

指定 whisper.cpp 模型路径。默认：

```text
models/ggml-base.bin
```

## 当前限制

- YouTube 视频如果匿名下载受限，工具会优先使用可下载的匿名格式；部分视频可能仍需要用户自行下载。
- 当前 MP4 输出是软字幕轨，不是硬字幕烧录。
- Homebrew 普通 `ffmpeg` 可能没有 `subtitles` / `drawtext` 滤镜，因此默认不做硬烧录。
- 本地 Whisper `base` 模型对专有名词、口音、噪声场景会有误识别。
- 本地翻译模型是粗翻级别，适合快速看效果；专有名词需要人工修正或词表优化。
- 本地翻译目前主要验证了 `ja -> zh-CN` 和 `zh -> ja`。

## 开发与测试

运行测试：

```bash
python3 -m unittest discover -s tests
```

运行 CLI 帮助：

```bash
env PYTHONPATH=src python3 -m subtitle_tool.cli --help
```

## 文件与仓库说明

不会提交到仓库的内容：

- `output/`
- `models/*.bin`
- `.env`
- Python 缓存和构建产物

这些文件已经在 `.gitignore` 中排除。
