# local-video-subtitle-conversion-J

本项目是一个本地视频字幕转换工具：输入本地视频、TalkSmith 分享链接或 YouTube 链接，生成目标语言 `.srt` 字幕，并可输出带默认软字幕轨的 MP4 视频。

当前版本重点做的是“稳定产出外挂字幕和软字幕视频”，不是把字幕硬烧录进画面像素里。

## 功能要点

- 支持本地视频路径、网页上传视频、TalkSmith URL、YouTube URL。
- YouTube 默认优先下载高清视频，不再优先使用低清 360p 格式。
- 字幕来源支持自动判断：优先读视频内置字幕，没有内置字幕时再抽音频语音识别。
- 语音转写支持本地 Whisper 和 OpenAI。
- 字幕翻译支持本地中日模型、z.ai、OpenAI。
- 支持一次选择多个目标语言，分别输出多份字幕和多份软字幕视频。
- 支持“重新下载”“只下载”“输出软字幕视频”“避免遮挡原字幕”等选项。
- Web 页面提供环境检查、进度条、实时日志、已用时、停止任务按钮。
- 输出文件按原视频名归档到独立目录，文件名带时间戳，便于区分多次任务。

## 适合场景

- 把日语或英语视频转成中文字幕。
- 把中文视频转成日语、英语等字幕。
- 批量生成不同目标语言的 `.srt` 文件。
- 给 MP4 添加默认软字幕轨，方便在 IINA / VLC 等播放器里选择字幕。
- 下载 TalkSmith 或 YouTube 视频后再生成字幕。

## 重要概念

### 软字幕

软字幕是独立字幕轨，被封装进 MP4 或作为 `.srt` 文件存在。播放器可以开关和切换字幕。

本项目的 `*.default-sub.mp4` 是软字幕视频。它不会改变原视频画面清晰度，因为视频流使用 `copy` 方式保留。

### 硬字幕

硬字幕是画面像素的一部分，播放器不能关闭，也不能直接提取成文本。本项目当前不会 OCR 画面上的硬字幕，也不会把字幕烧录进画面。

如果原视频里已经有一行硬字幕，新生成的软字幕可能会在播放器默认位置附近显示。页面里的“避免遮挡原字幕”目前只是记录意图；软字幕实际显示位置主要由播放器控制。

## 环境要求

- macOS
- Python 3.9+
- `ffmpeg` / `ffprobe`
- `yt-dlp`，处理 YouTube 链接时需要
- `whisper.cpp`，本地语音识别时需要
- whisper.cpp GGML 模型文件，例如 `models/ggml-base.bin`
- 本地翻译模型缓存，使用本地翻译时需要

安装系统工具：

```bash
brew install ffmpeg
brew install whisper-cpp
brew install yt-dlp
```

安装 Python 依赖：

```bash
python3 -m pip install openai
python3 -m pip install transformers sentencepiece torch protobuf
```

下载 Whisper 模型：

```bash
mkdir -p models
curl -L https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin -o models/ggml-base.bin
```

## 配置 API Key

项目支持 `.env`。复制示例文件：

```bash
cp .env.example .env
```

然后按需填写：

```text
OPENAI_API_KEY=
ZAI_API_KEY=
ZAI_API_BASE=https://open.bigmodel.cn/api/paas/v4/
ZAI_MODEL=glm-4.7-flash
```

z.ai 限流保护参数：

```text
ZAI_TIMEOUT_SECONDS=60
ZAI_REQUEST_DELAY_SECONDS=2
ZAI_RATE_LIMIT_RETRY_SECONDS=20
ZAI_RATE_LIMIT_RETRY_LIMIT=3
```

说明：

- `ZAI_REQUEST_DELAY_SECONDS`：每批翻译之间等待几秒，降低限流概率。
- `ZAI_RATE_LIMIT_RETRY_SECONDS`：遇到 429 后首次等待秒数，后续会递增。
- `ZAI_RATE_LIMIT_RETRY_LIMIT`：遇到 429 最多重试几次。
- `.env` 不会提交到 GitHub。

## 启动图形界面

在项目目录运行：

```bash
env PYTHONPATH=src python3 -m subtitle_tool.web --host 127.0.0.1 --port 7860
```

浏览器打开：

```text
http://127.0.0.1:7860
```

Web 页面支持：

- 输入 YouTube / TalkSmith URL。
- 输入本地视频路径。
- 上传本地视频文件。上传视频优先级高于文本框里的 URL 或路径。
- 选择原视频语言和目标语言。
- 目标语言可以多选，例如 `ja, vi, en`。
- 选择字幕来源：自动、内置字幕、音频识别。
- 选择语音转写：本地 Whisper 或 OpenAI。
- 选择字幕翻译：本地中日模型、z.ai、OpenAI。
- 任务运行时显示进度、日志、已用时。
- 任务运行时可点击“停止任务”。

停止任务是协作式取消：如果任务正卡在一次 API 请求、ffmpeg、yt-dlp 等外部步骤里，不能毫秒级硬杀，但会在当前步骤返回或超时后停止。

## 命令行用法

所有命令建议在项目目录运行：

```bash
cd /Users/duole/DDeveloper/AI/codex-test/project3-codex
```

直接用源码运行时，在命令前加：

```bash
env PYTHONPATH=src
```

### 本地视频转字幕

```bash
env PYTHONPATH=src python3 -m subtitle_tool.cli input.mp4 \
  --source-lang ja \
  --target-lang zh-CN \
  --transcriber local-whisper \
  --translator z-ai \
  --embed-subtitles \
  --out-dir output
```

### YouTube 视频转日语字幕视频

```bash
env PYTHONPATH=src python3 -m subtitle_tool.cli 'https://www.youtube.com/watch?v=gaaarGhydLk' \
  --source-lang zh \
  --target-lang ja \
  --transcriber local-whisper \
  --translator z-ai \
  --embed-subtitles \
  --force-download \
  --out-dir output
```

### TalkSmith 视频转中文字幕

```bash
env PYTHONPATH=src python3 -m subtitle_tool.cli 'https://service.talk-smith.com/s?id=cmdfs4a5k265w0z1anf9fk08z' \
  --source-lang ja \
  --target-lang zh-CN \
  --transcriber local-whisper \
  --translator z-ai \
  --embed-subtitles \
  --out-dir output
```

### 一次输出多种语言

```bash
env PYTHONPATH=src python3 -m subtitle_tool.cli input.mp4 \
  --source-lang zh \
  --target-lang ja \
  --target-lang en \
  --target-lang vi \
  --transcriber local-whisper \
  --translator z-ai \
  --embed-subtitles \
  --out-dir output
```

每种目标语言会分别输出 `.srt` 和软字幕 MP4。

### 只下载远程视频

```bash
env PYTHONPATH=src python3 -m subtitle_tool.cli 'https://www.youtube.com/watch?v=gaaarGhydLk' \
  --download-only \
  --force-download \
  --out-dir output
```

`--download-only` 只下载，不转写、不翻译。适合先检查下载视频是否清晰。

`--force-download` 会忽略已有缓存，重新下载。之前下载过低清版本时建议打开。

## 参数说明

```text
input
```

输入视频路径或 URL。支持本地视频、TalkSmith 分享 URL、YouTube URL。

```text
--source-lang
```

原视频语言，例如 `zh`、`zh-CN`、`ja`、`en`。本地 Whisper 建议显式填写，识别更稳定。

```text
--target-lang
```

目标字幕语言，可重复传入。不传时只输出源字幕。

```text
--source
```

字幕来源策略：

- `auto`：默认，先找内置字幕，没有就听音频。
- `embedded`：只读取内置字幕。
- `audio`：强制听音频识别。

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
- `z-ai`
- `openai`

```text
--embed-subtitles
```

输出带默认软字幕轨的 MP4。

```text
--download-only
```

只下载远程视频，不生成字幕。

```text
--force-download
```

远程视频已存在时也重新下载。

```text
--whisper-model
```

指定 whisper.cpp 模型路径。默认：

```text
models/ggml-base.bin
```

## 模型选择建议

### 本地 Whisper

适合不想使用 OpenAI 转写的场景。`ggml-base.bin` 速度快，但对专有名词、噪声、动漫台词、混合语言可能识别不准。

如果源字幕识别错，后续翻译质量也会下降。

### 本地中日翻译模型

当前只适合：

```text
ja -> zh-CN
zh / zh-CN -> ja
```

它速度快，但质量不如 z.ai / OpenAI，也不支持越南语、英语、韩语、法语等多语言方向。遇到源字幕质量差时，可能出现重复词、重复句或语义崩坏。

### z.ai 翻译

适合多语言翻译，例如 `ja`、`en`、`vi`、`ko`、`fr`。当前实现带批次日志、缺失字幕补翻、限流等待重试和超时。

如果一次选择很多目标语言，仍可能遇到 429 限流。可以减少目标语言数量，或调大 `.env` 里的等待参数。

### OpenAI 翻译

适合希望质量更稳定的场景，需要 `OPENAI_API_KEY`。

## 输出目录

输出按原视频名归档：

```text
output/<video-name>/
```

文件名带时间戳和一位随机数字：

```text
<video-name>.<YYYYMMDDHHMMSSX>.mp4
<video-name>.<YYYYMMDDHHMMSSX>.source.<source-lang>.srt
<video-name>.<YYYYMMDDHHMMSSX>.<target-lang>.srt
<video-name>.<YYYYMMDDHHMMSSX>.<target-lang>.default-sub.mp4
```

示例：

```text
output/ftWe_pVrtho/
  ftWe_pVrtho.202607091516421.mp4
  ftWe_pVrtho.202607091516421.source.zh.srt
  ftWe_pVrtho.202607091516421.ja.srt
  ftWe_pVrtho.202607091516421.ja.default-sub.mp4
```

同一个视频再次生成不同目标语言，会继续放在同一个视频目录下。

## 验证字幕

推荐用 IINA 或 VLC 验证软字幕轨。QuickTime 对 MP4 软字幕显示比较挑，可能出现“文件里有字幕但播放时没显示”。

也可以用 `ffprobe` 检查：

```bash
ffprobe -v error -select_streams s -show_entries stream=index,codec_name:stream_tags=language,title -of json output/video/video.default-sub.mp4
```

如果能看到 `mov_text` 字幕流，说明软字幕轨已经写入。

## 常见问题

### 为什么视频变模糊？

早期版本 YouTube 下载优先选过低清格式。当前版本优先下载高清 MP4 视频和 M4A 音频。已下载过低清缓存时，勾选“重新下载”或使用 `--force-download`。

生成软字幕 MP4 时视频流使用 `copy`，不会主动降低清晰度。

### 为什么越南语没有输出？

如果使用本地中日翻译模型，越南语不支持。多语言请用 `z-ai` 或 `openai`。

### 为什么本地模型翻译重复很多句？

本地中日模型是小型翻译模型，质量有限。源字幕识别不准时，模型容易输出重复词或重复句。建议改用 z.ai / OpenAI，或者先提高转写质量。

### 原视频画面上有中文字幕，工具会读取吗？

不会。画面里的字幕通常是硬字幕，已经是像素。当前工具不会 OCR 画面文字。它会优先读取视频内置字幕轨；没有内置字幕轨时，听音频转写。

### 为什么 z.ai 报 429？

429 表示账号触发请求频率限制。当前版本会自动等待并重试。仍频繁出现时，减少目标语言数量，或调大：

```text
ZAI_REQUEST_DELAY_SECONDS
ZAI_RATE_LIMIT_RETRY_SECONDS
```

## 当前限制

- 当前只输出 `.srt` 和软字幕 MP4，不做硬字幕烧录。
- 不做视频画面 OCR，无法直接读取硬字幕文字。
- 本地中日翻译模型语言方向有限，质量是粗翻级别。
- 本地 Whisper `base` 模型识别质量有限，必要时可换更大的 whisper.cpp 模型。
- YouTube 部分视频可能限制匿名下载，仍可能需要用户自行下载。
- 停止任务是协作式取消，不能瞬间终止正在执行的外部进程或 API 请求。

## 开发与测试

运行测试：

```bash
python3 -m unittest discover -s tests
```

编译检查：

```bash
env PYTHONPYCACHEPREFIX=/private/tmp/subtitle-tool-pycache python3 -m compileall src tests
```

查看 CLI 帮助：

```bash
env PYTHONPATH=src python3 -m subtitle_tool.cli --help
```

## 仓库说明

不会提交到仓库的内容：

- `.env`
- `output/`
- `models/*.bin`
- `.venv/`
- Python 缓存和构建产物

这些文件已在 `.gitignore` 中排除。
