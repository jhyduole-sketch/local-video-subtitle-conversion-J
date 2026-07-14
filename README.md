# 本地多语言视频字幕工具

[中文首页](README.md) · [完整使用指南](docs/使用指南.md) · [更新记录](docs/更新记录.md) · [English](README.en.md)

输入一个**本地视频、上传文件或公开视频网址**，工具会自动取得源字幕或识别视频语音，再生成一种或多种目标语言的 `.srt` 字幕。需要时，还可以输出保留原画质的软字幕视频，或固定位置显示的硬字幕视频。

项目同时提供本地 Web 界面和命令行，适合个人在 macOS 上处理日语、中文、英语及其他常见语言的视频。

## 项目亮点

- **多种输入**：本地路径、网页上传、YouTube、Bilibili，以及其它公开单视频网址的通用尝试下载。
- **智能字幕来源**：优先读取视频内置字幕；没有字幕轨时，使用本地 Whisper 或 OpenAI 识别语音。
- **多语言翻译**：支持 z.ai、OpenAI、本地中/日/英快速模型，以及 NLLB 600M / 1.3B 多语言模型。
- **稳定回退**：z.ai 限流或翻译失败时，可自动切换本地模型；本地结果不合格时再尝试 OpenAI。
- **质量保护**：检测空字幕、重复内容、异常长度、语言不匹配，并对 NLLB 异常句进行单句重试。
- **多种成品**：输出外挂 `.srt`、可开关软字幕 MP4，或固定位置硬字幕 MP4。
- **字幕避让**：分析视频顶部和底部的文字区域，把新硬字幕放到更合适的位置，减少与原画面字幕重叠。
- **预览与校对**：任务完成后可在浏览器中播放视频、同步查看字幕、修改文字和时间轴，再重新生成视频。
- **任务可靠性**：实时进度、时间戳日志、停止任务、任务历史、失败继续、缓存复用和重复提交保护。
- **本地优先**：视频、模型、缓存、任务记录和输出均保存在当前电脑，不需要单独部署服务端。

## 处理流程

```mermaid
flowchart LR
    A["本地视频 / 上传文件 / 公共 URL"] --> B["准备视频"]
    B --> C{"存在内置字幕轨？"}
    C -- "是" --> D["导出源字幕与时间轴"]
    C -- "否" --> E["抽取音频"]
    E --> F["本地 Whisper / OpenAI 转写"]
    F --> D
    D --> G["选择目标语言与翻译引擎"]
    G --> H["翻译、质量检查与自动回退"]
    H --> I["生成目标语言 SRT"]
    I --> J["软字幕视频：保留原画质"]
    I --> K["硬字幕视频：固定位置"]
    I --> L["浏览器预览与字幕校对"]
    L --> M["保存字幕并重新生成视频"]
```

## 系统架构

```mermaid
flowchart TB
    subgraph Input["输入与操作"]
        WEB["本地 Web 界面"]
        CLI["命令行 CLI"]
        FILE["本地文件 / 视频 URL"]
    end

    subgraph Core["字幕处理核心"]
        JOB["任务调度、历史、停止与继续"]
        MEDIA["ffmpeg / ffprobe / yt-dlp"]
        SOURCE["内置字幕读取与音频抽取"]
        STT["Whisper / OpenAI 转写"]
        TRANS["z.ai / OpenAI / OPUS-MT / NLLB"]
        QA["翻译质量检查与引擎回退"]
        LAYOUT["字幕换行、时间整理与位置检测"]
    end

    subgraph Storage["本地数据"]
        CACHE["视频、音频、转写、翻译缓存"]
        STATE["SQLite 任务记录"]
        OUTPUT["SRT、软字幕视频、硬字幕视频"]
    end

    FILE --> WEB
    FILE --> CLI
    WEB --> JOB
    CLI --> JOB
    JOB --> MEDIA --> SOURCE --> STT --> TRANS --> QA --> LAYOUT --> OUTPUT
    JOB <--> STATE
    MEDIA <--> CACHE
    STT <--> CACHE
    TRANS <--> CACHE
```

## 快速开始

### 1. 安装基础工具

```bash
brew install ffmpeg
brew install ffmpeg-full
brew install whisper-cpp
brew install yt-dlp
```

安装 Python 依赖：

```bash
python3 -m pip install -e .
python3 -m pip install transformers sentencepiece torch protobuf
```

下载基础 Whisper 模型：

```bash
mkdir -p models
curl -L https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin -o models/ggml-base.bin
```

完整的 VAD、本地翻译模型和 API 配置见[完整使用指南](docs/使用指南.md)。

### 2. 配置云端模型（可选）

```bash
cp .env.example .env
```

按需要填写：

```text
OPENAI_API_KEY=
ZAI_API_KEY=
ZAI_API_BASE=https://open.bigmodel.cn/api/paas/v4/
ZAI_MODEL=glm-4.7-flash
```

只使用本地 Whisper 和本地翻译模型时，可以不配置云端 Key。

### 3. 启动 Web 界面

仅本机访问：

```bash
env PYTHONPATH=src python3 -m subtitle_tool.web --host 127.0.0.1 --port 7860
```

浏览器打开 [http://127.0.0.1:7860](http://127.0.0.1:7860)。

允许可信局域网设备访问：

```bash
env PYTHONPATH=src python3 -m subtitle_tool.web --host 0.0.0.0 --port 7860
```

当前 Web 页面没有登录保护，局域网模式只适合可信网络。

## 常见使用方式

### 本地视频生成中文字幕

```bash
env PYTHONPATH=src python3 -m subtitle_tool.cli input.mp4 \
  --source-lang ja \
  --target-lang zh-CN \
  --transcriber local-whisper \
  --translator z-ai \
  --embed-subtitles \
  --out-dir output
```

### 远程视频生成日语和英语字幕

```bash
env PYTHONPATH=src python3 -m subtitle_tool.cli 'https://www.youtube.com/watch?v=VIDEO_ID' \
  --source-lang auto \
  --target-lang ja \
  --target-lang en \
  --transcriber local-whisper \
  --translator z-ai \
  --embed-subtitles \
  --out-dir output
```

### 只下载视频

```bash
env PYTHONPATH=src python3 -m subtitle_tool.cli 'https://example.com/video' \
  --download-only \
  --out-dir output
```

通用网址下载属于尽力尝试：需要登录、Cookie、DRM、地区授权或特殊播放器的网站可能无法下载。

## 翻译引擎怎么选

| 引擎 | 适合场景 | 特点 |
| --- | --- | --- |
| z.ai | 默认在线多语言翻译 | 语言覆盖广；可能遇到账号限流 |
| OpenAI | 高质量在线备用 | 质量稳定；需要 API Key 并产生 API 费用 |
| 本地快速模型 | 中、日、英离线粗翻 | 速度快、模型较小；支持方向有限 |
| NLLB 600M | 更多语言的本地快速翻译 | 离线、覆盖广；质量低于 1.3B |
| NLLB 1.3B | 更多语言的本地质量模式 | 更准确；模型更大、CPU 推理更慢 |

转写和翻译不是一件事：Whisper 负责“听懂视频在说什么”，翻译模型负责“把源字幕转换成目标语言”。

## 输出结果

每次任务都会建立独立时间戳目录：

```text
output/<video-name>.<YYYYMMDDHHMMSSX>/
  <video-name>.<timestamp>.mp4
  <video-name>.<timestamp>.source.<source-lang>.srt
  <video-name>.<timestamp>.<target-lang>.srt
  <video-name>.<timestamp>.<target-lang>.default-sub.mp4
  <video-name>.<timestamp>.<target-lang>.fixed-sub.mp4
```

- `*.srt`：外挂字幕，可在播放器或剪辑软件中单独使用。
- `*.default-sub.mp4`：软字幕视频，字幕可开关，视频流保持原画质。
- `*.fixed-sub.mp4`：硬字幕视频，字幕固定在画面中，需要重新编码。

软字幕推荐使用 IINA 或 VLC 验证。QuickTime 对部分 MP4 软字幕轨的显示兼容性有限。

## 近期更新

- Whisper 支持 Metal/GPU 加速、VAD 跳过静音，以及失败后的 CPU/标准转写回退。
- 硬字幕支持 Apple VideoToolbox、快速 CPU 和高质量 CPU 编码，并显示真实百分比、速度和预计剩余时间。
- Web 前后端共同阻止连续点击和重复提交，页面刷新后可恢复当前任务状态。
- 任务历史支持安全清空已结束记录；缓存支持分类清理和一键清空全部，并在删除前明确提示影响范围。
- 加入 NLLB 1.3B、多语言质量检查、异常句重试、翻译缓存和云端限流回退。
- 加入画面字幕位置检测、自动避让、字幕预览校对和保存后重新生成视频。
- 加入任务历史、失败继续、分类缓存管理和通用公开视频网址尝试下载。

完整变化见[更新记录](docs/更新记录.md)和[性能与任务安全技术说明](docs/2026-07-13-performance-and-task-safety.md)。

## 文档导航

- [完整使用指南](docs/使用指南.md)：安装、配置、Web、CLI、模型、缓存、字幕编辑和故障排查。
- [更新记录](docs/更新记录.md)：按阶段查看项目能力变化。
- [English README](README.en.md)：英文项目简介和快速启动。
- [性能与任务安全更新](docs/2026-07-13-performance-and-task-safety.md)：最近一轮性能优化的详细说明。

## 当前限制

- 不做视频画面 OCR，不能直接读取已经烧录进画面的字幕文字。
- 通用下载不保证支持所有网站，也不绕过 DRM、登录、付费或地区限制。
- 本地 Whisper `base` 模型和小型翻译模型适合快速试跑，不代表最高识别或翻译质量。
- 硬字幕需要重新编码，长视频和高分辨率视频会消耗较多时间。
- 自动字幕位置检测是视觉启发式分析，复杂台标、弹幕或大量画面文字可能降低置信度。
- 任务历史和缓存保存在当前电脑，不会自动同步到其它设备。

## 开发验证

```bash
python3 -m unittest discover -s tests
env PYTHONPYCACHEPREFIX=/private/tmp/subtitle-tool-pycache python3 -m compileall src tests
```

项目不会提交 `.env`、`output/`、本地模型、缓存和任务数据库。
