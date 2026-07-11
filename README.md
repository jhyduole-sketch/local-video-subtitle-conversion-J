# local-video-subtitle-conversion-J

本项目是一个本地视频字幕转换工具：输入本地视频、TalkSmith 分享链接、YouTube 或 Bilibili 链接，生成目标语言 `.srt` 字幕，并可输出带默认软字幕轨的 MP4 视频。

当前版本重点做的是“稳定产出外挂字幕和软字幕视频”，不是把字幕硬烧录进画面像素里。

## 功能要点

- 支持本地视频路径、网页上传视频、TalkSmith URL、YouTube URL、Bilibili URL。
- YouTube 默认优先下载高清视频，不再优先使用低清 360p 格式。
- 字幕来源支持自动判断：优先读视频内置字幕，没有内置字幕时再抽音频语音识别。
- 语音转写支持本地 Whisper 和 OpenAI。
- 字幕翻译支持 z.ai、本地中/日/英快速模型、本地多语言 NLLB 和 OpenAI。
- z.ai 连续限流或翻译失败时，会自动尝试本地模型；本地结果未通过质量检查时再切换 OpenAI，并在日志和结果中标明实际引擎。
- 相同源字幕、目标语言和翻译策略会复用本地翻译缓存，减少重复 API 请求。
- 支持一次选择多个目标语言，分别输出多份字幕和多份软字幕视频。
- 支持“重新下载”“只下载”“输出软字幕视频”“避免遮挡原字幕”等选项。
- Web 页面提供环境检查、进度条、实时日志、已用时、停止任务按钮。
- Web 任务按单队列顺序执行，避免多个本地模型或下载进程同时争抢资源。
- 任务历史会写入本地 SQLite；服务重启后仍可查看，失败、取消或中断的任务可以继续执行。
- 视频、音频、源字幕、转写结果和翻译结果均有本地缓存，并可在页面按类别查看和清理。
- 每次任务创建带时间戳的独立目录，文件名也带同一时间戳，便于区分多次任务。

## 适合场景

- 把日语或英语视频转成中文字幕。
- 把中文视频转成日语、英语等字幕。
- 批量生成不同目标语言的 `.srt` 文件。
- 给 MP4 添加默认软字幕轨，方便在 IINA / VLC 等播放器里选择字幕。
- 生成固定位置的硬字幕视频，避开原画面底部字幕。
- 下载 TalkSmith、YouTube 或 Bilibili 视频后再生成字幕。

## 重要概念

### 软字幕

软字幕是独立字幕轨，被封装进 MP4 或作为 `.srt` 文件存在。播放器可以开关和切换字幕。

本项目的 `*.default-sub.mp4` 是软字幕视频。它不会改变原视频画面清晰度，因为视频流使用 `copy` 方式保留。

### 硬字幕

硬字幕是画面像素的一部分，播放器不能关闭，也不能直接提取成文本。选择“稳定硬字幕”后，工具会使用 ASS 样式和 FFmpeg 把新字幕烧录进画面，因此需要重新编码视频。

如果原视频底部已经有硬字幕，推荐选择“稳定硬字幕”和“自动避让”或“原底部字幕上方”。软字幕实际显示位置主要由播放器控制，无法保证在每个播放器里都能避让。

页面勾选“自动避让原字幕”时会强制使用稳定硬字幕，避免出现“勾选了避让、实际却仍输出软字幕”的冲突。任务日志会显示最终采用的字幕模式和位置。主动切换回软字幕时，页面会自动关闭避让选项。

自动避让会从视频时间轴均匀抽取最多 8 帧，分析顶部和底部反复出现的文字边缘。检测到底部硬字幕时，新字幕放到原字幕上方；检测到顶部硬字幕时，新字幕放到底部。检测结果带置信度并缓存在 `.subtitle-tool-cache/analysis/`。置信度不足时采用保守的底部上方位置，不擦除原画面。

所有目标字幕写出前都会自动整理：按中英文显示宽度换行、尽量保持最多两行、长句按原时间段拆分，并修复相邻字幕时间重叠。字幕文字不会被截断。

## 环境要求

- macOS
- Python 3.9+
- `ffmpeg` / `ffprobe`
- `ffmpeg-full`，仅固定位置硬字幕模式需要；它提供 `libass` 过滤器
- `yt-dlp`，处理 YouTube / Bilibili 链接时需要
- `whisper.cpp`，本地语音识别时需要
- whisper.cpp GGML 模型文件，例如 `models/ggml-base.bin`
- 本地翻译模型缓存，使用本地翻译时需要

安装系统工具：

```bash
brew install ffmpeg
brew install ffmpeg-full
brew install whisper-cpp
brew install yt-dlp
```

`ffmpeg-full` 是 keg-only，无需替换系统中的普通 `ffmpeg`。本工具会自动使用 `/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg` 处理硬字幕。

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
ZAI_TRANSLATION_BATCH_SEGMENTS=24
ZAI_TRANSLATION_BATCH_CHARACTERS=4000
LOCAL_TRANSLATION_BATCH_SIZE=8
LOCAL_TRANSLATION_DEVICE=cpu
```

说明：

- `ZAI_REQUEST_DELAY_SECONDS`：每批翻译之间等待几秒，降低限流概率。
- `ZAI_RATE_LIMIT_RETRY_SECONDS`：遇到 429 后首次等待秒数，后续会递增。
- `ZAI_RATE_LIMIT_RETRY_LIMIT`：遇到 429 最多重试几次。
- `ZAI_TRANSLATION_BATCH_SEGMENTS` / `ZAI_TRANSLATION_BATCH_CHARACTERS`：限制每次 z.ai 请求包含的字幕条数和字符数。
- `LOCAL_TRANSLATION_BATCH_SIZE`：本地模型每批处理的字幕条数。
- `LOCAL_TRANSLATION_DEVICE`：默认 `cpu`；Apple 芯片可手动设为 `mps`，设备推理失败时会回退 CPU。
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

- 输入 YouTube / Bilibili / TalkSmith URL。
- 输入本地视频路径。
- 上传本地视频文件。上传视频优先级高于文本框里的 URL 或路径。
- 选择原视频语言和目标语言。
- 目标语言可以多选，例如 `ja, vi, en`。
- 常用目标语言使用下拉复选框；切换字幕翻译模型时，会自动收敛到当前模型支持/推荐的语言范围。
- 选择字幕来源：自动、内置字幕、音频识别。
- 选择语音转写：本地 Whisper 或 OpenAI。
- 选择本地 Whisper 模型大小：`base`、`small`、`medium` 或自定义模型路径。
- 选择字幕翻译：z.ai、本地快速模型、本地多语言 NLLB、OpenAI。
- 选择字幕视频模式：软字幕保持原画质，稳定硬字幕固定显示位置。
- 选择新字幕位置：自动避让、原底部字幕上方、画面底部或画面顶部。
- 任务运行时显示进度、日志、已用时。
- 任务运行时可点击“停止任务”。
- 查看历史任务，并继续失败、取消或因服务重启而中断的任务。
- 查看缓存占用，并按视频、音频、源字幕、转写或翻译类别清理缓存。
- 在输出区点击“编辑字幕”，修改字幕文字与开始/结束时间。
- 保存字幕时自动创建 `.backup.srt`；可保存后直接提交重新生成视频任务。

Web 服务同一时间只执行一个任务，后提交的任务会进入队列。这样速度未必最快，但能避免 Whisper、ffmpeg 和本地翻译模型互相争抢内存与 CPU。

点击“停止任务”后，工具会终止当前 `ffmpeg`、`yt-dlp` 或 `whisper-cli` 子进程。正在等待的云端 API 请求仍需等该请求返回或超时，然后任务才会完全停止。

任务记录保存在项目根目录的 `.subtitle-tool-state/jobs.sqlite3`。继续任务会创建一个新的关联任务，并复用已完成的下载、音频、转写及翻译批次，不会覆盖原任务记录。`output/` 只保存下载视频、字幕和成品视频。

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

### Bilibili 视频转日语字幕

```bash
env PYTHONPATH=src python3 -m subtitle_tool.cli 'https://www.bilibili.com/video/BV1rR4y197tP/' \
  --source-lang zh \
  --target-lang ja \
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

输入视频路径或 URL。支持本地视频、TalkSmith 分享 URL、YouTube URL、Bilibili URL。

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

- `z-ai`
- `local-transformer`
- `local-nllb`
- `openai`

```text
--embed-subtitles
```

输出字幕视频，默认生成带可开关软字幕轨的 MP4。

```text
--subtitle-video-mode soft|hard
```

- `soft`：复制原视频和音频流，速度快、不改变视频清晰度，但字幕位置由播放器控制。
- `hard`：将字幕烧录进画面，位置稳定，需要重新编码视频。

```text
--subtitle-position auto|bottom|above-bottom|top
```

硬字幕位置。`auto` 在启用 `--avoid-subtitle-overlap` 时自动使用 `above-bottom`。
为了保证避让真实生效，只要同时启用 `--embed-subtitles` 和 `--avoid-subtitle-overlap`，后端就会自动使用硬字幕模式，即使传入的 `--subtitle-video-mode` 是 `soft`。

在原底部字幕上方生成稳定英文字幕视频：

```bash
env PYTHONPATH=src python3 -m subtitle_tool.cli input.mp4 \
  --source-lang ja \
  --target-lang en \
  --translator z-ai \
  --embed-subtitles \
  --avoid-subtitle-overlap \
  --subtitle-video-mode hard \
  --subtitle-position above-bottom
```

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

Web 页面可以选择 `base`、`small`、`medium` 三档模型：

- `base`：速度快，适合快速试跑。
- `small`：速度和准确率更平衡。
- `medium`：更准但更慢，对机器性能要求更高。

选择更大的模型前，需要先把对应文件下载到 `models/`，例如 `models/ggml-small.bin` 或 `models/ggml-medium.bin`。

### 本地中/日/英翻译模型

当前本地翻译支持：

```text
ja -> zh-CN
zh / zh-CN -> ja
ja -> en
en -> ja
zh / zh-CN -> en
en -> zh-CN
```

中日方向继续使用已有小模型。英文方向使用 Helsinki-NLP OPUS-MT 模型：

```text
Helsinki-NLP/opus-mt-zh-en
Helsinki-NLP/opus-mt-en-zh
Helsinki-NLP/opus-mt-ja-en
Helsinki-NLP/opus-mt-en-jap
```

这些英文模型需要先下载到 Hugging Face 本地缓存。Web 页面右侧“环境”区会显示每个本地翻译方向是否已安装；未安装时，会直接显示对应下载命令。

也可以手动执行类似命令下载：

```bash
python3 -c "from transformers import AutoTokenizer, AutoModelForSeq2SeqLM; AutoTokenizer.from_pretrained('Helsinki-NLP/opus-mt-zh-en', use_fast=False); AutoModelForSeq2SeqLM.from_pretrained('Helsinki-NLP/opus-mt-zh-en')"
```

### 本地多语言 NLLB 模型

如果需要离线支持更多语言，可以在 Web 页面选择：

```text
本地多语言模型（NLLB）
```

当前使用模型：

```text
facebook/nllb-200-distilled-600M
```

它支持常用目标语言，例如 `zh-CN`、`zh-TW`、`ja`、`en`、`ko`、`fr`、`de`、`es`、`pt`、`it`、`ru`、`ar`、`th`、`vi`、`id`。

NLLB 模型较大，首次下载会比较慢，CPU 翻译速度也比本地快速模型慢。工具不会自动下载该模型；Web 页面右侧“环境”区会显示是否已安装，并给出下载命令。

手动下载命令示例：

```bash
python3 -c "from transformers import AutoTokenizer, AutoModelForSeq2SeqLM; AutoTokenizer.from_pretrained('facebook/nllb-200-distilled-600M', use_fast=False); AutoModelForSeq2SeqLM.from_pretrained('facebook/nllb-200-distilled-600M')"
```

本地快速模型速度快，但质量不如 z.ai / OpenAI，也不支持越南语、韩语、法语等更多语言方向。NLLB 覆盖语言更多，但模型更大、速度更慢。遇到源字幕质量差时，本地模型可能出现重复词、重复句或语义崩坏。

当前版本会对本地翻译结果做基础质量保护：

- 空翻译会失败。
- 明显过长的翻译会失败。
- 重复词/重复短语过多会失败，例如 `密かに密かに密かに...`。
- 目标是日语但输出明显不像日语时会失败。

检测失败时不会继续生成坏字幕视频，日志会提示改用 z.ai / OpenAI 或先改善源字幕。

### z.ai 翻译

适合多语言翻译，例如 `ja`、`en`、`vi`、`ko`、`fr`。Web 页面会展示更多常用目标语言快捷按钮；这些按钮只是常用入口，也可以在目标语言输入框手动填写其它语言代码，例如 `he`、`fa`、`cs`、`ro`、`hu`、`fi`、`da`、`sw`。

当前实现带动态批次、缺失字幕补翻、全局串行请求、限流等待重试和超时。连续限流或翻译失败后会自动尝试本地快速模型和 NLLB；本地模型不可用或质量检查失败时，再尝试 OpenAI。

每个目标语言的最终结果会标明实际使用的引擎，例如 `z.ai`、`本地模型`、`OpenAI` 或 `OpenAI（缓存）`。

如果一次选择很多目标语言，仍可能遇到 429 限流。可以减少目标语言数量，或调大 `.env` 里的等待参数。

### OpenAI 翻译

适合希望质量更稳定的场景，需要 `OPENAI_API_KEY`。OpenAI 也按云端多语言模型处理，Web 页面会展示和 z.ai 类似的更多常用语言快捷按钮，同时保留手动输入其它语言代码。

## 输出目录

每次任务按原视频名和任务时间戳建立独立目录：

```text
output/<video-name>.<YYYYMMDDHHMMSSX>/
```

文件名带时间戳和一位随机数字：

```text
<video-name>.<YYYYMMDDHHMMSSX>.mp4
<video-name>.<YYYYMMDDHHMMSSX>.source.<source-lang>.srt
<video-name>.<YYYYMMDDHHMMSSX>.<target-lang>.srt
<video-name>.<YYYYMMDDHHMMSSX>.<target-lang>.default-sub.mp4
<video-name>.<YYYYMMDDHHMMSSX>.<target-lang>.fixed-sub.mp4
<video-name>.<YYYYMMDDHHMMSSX>.<target-lang>.edited.fixed-sub.mp4
```

示例：

```text
output/ftWe_pVrtho.202607091516421/
  ftWe_pVrtho.202607091516421.mp4
  ftWe_pVrtho.202607091516421.source.zh.srt
  ftWe_pVrtho.202607091516421.ja.srt
  ftWe_pVrtho.202607091516421.ja.default-sub.mp4
```

同一个视频再次运行会创建新的时间戳目录。相同字幕翻译会从 `.subtitle-tool-cache/translations/` 复用缓存，但输出文件仍会放在本次任务目录，避免与旧结果混在一起。

稳定缓存位于项目根目录的 `.subtitle-tool-cache/`，包括：

```text
videos/              下载的视频
audio/               已抽取音频
source-subtitles/    内置源字幕
transcripts/         Whisper 转写结果
translations/        完整及分批翻译结果
analysis/            画面硬字幕位置检测
```

清理缓存不会删除已经生成的时间戳任务目录。z.ai 分批翻译中断后，已成功的批次也会保留；继续任务时只请求尚未完成的字幕片段。

旧版本保存在 `output/.subtitle-tool-state/` 和 `output/.subtitle-tool-cache/` 的数据会在服务启动或首次使用缓存时自动迁移到项目根目录。也可以分别使用 `SUBTITLE_TOOL_STATE_DB` 和 `SUBTITLE_TOOL_CACHE_DIR` 环境变量指定其它位置。

## 验证字幕

推荐用 IINA 或 VLC 验证软字幕轨。QuickTime 对 MP4 软字幕显示比较挑，可能出现“文件里有字幕但播放时没显示”。

也可以用 `ffprobe` 检查：

```bash
ffprobe -v error -select_streams s -show_entries stream=index,codec_name:stream_tags=language,title -of json output/video/video.default-sub.mp4
```

如果能看到 `mov_text` 字幕流，说明软字幕轨已经写入。

`*.fixed-sub.mp4` 的字幕已经成为画面的一部分，不会显示为独立字幕流；直接用 QuickTime、IINA 或 VLC 播放即可验证位置。

## 常见问题

### 为什么视频变模糊？

早期版本 YouTube 下载优先选过低清格式。当前版本优先下载高清 MP4 视频和 M4A 音频。已下载过低清缓存时，勾选“重新下载”或使用 `--force-download`。

生成软字幕 MP4 时视频流使用 `copy`，不会主动降低清晰度。

### 为什么越南语没有输出？

如果使用本地中/日/英翻译模型，越南语不支持。更多语言请用 `z-ai` 或 `openai`。

### 为什么本地模型翻译重复很多句？

本地翻译模型是小型翻译模型，质量有限。源字幕识别不准时，模型容易输出重复词或重复句。当前版本会检测明显异常并阻止坏字幕继续输出；仍建议改用 z.ai / OpenAI，或者先提高转写质量。

### 原视频画面上有中文字幕，工具会读取吗？

不会。画面里的字幕通常是硬字幕，已经是像素。当前工具不会 OCR 画面文字。它会优先读取视频内置字幕轨；没有内置字幕轨时，听音频转写。

### 为什么 z.ai 报 429？

429 表示账号触发请求频率限制。当前版本会自动等待并重试；重试耗尽后会依次尝试本地模型和 OpenAI，并在日志中提示切换过程。仍频繁出现时，可以减少目标语言数量，或调大：

```text
ZAI_REQUEST_DELAY_SECONDS
ZAI_RATE_LIMIT_RETRY_SECONDS
```

## 当前限制

- 硬字幕模式需要重新编码，处理速度慢于软字幕模式，输出文件大小也可能变化。
- 不做视频画面 OCR，无法直接读取硬字幕文字。
- 自动检测置信度不足时会保守假设原字幕位于底部；可在页面手动覆盖新字幕位置。
- 画面字幕检测是多帧视觉启发式判断，不是 OCR；复杂台标、弹幕或大段画面文字可能降低置信度，此时可手动指定位置。
- 本地中/日/英翻译模型语言方向有限，质量是粗翻级别。
- 本地 Whisper `base` 模型识别质量有限，必要时可换更大的 whisper.cpp 模型。
- YouTube / Bilibili 部分视频可能限制匿名下载，仍可能需要用户自行下载。
- 云端 API 请求无法像本地子进程一样立即终止，需要等待当前请求返回或超时。
- 任务历史和缓存是当前电脑上的本地状态，不会自动同步到其它设备。

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
