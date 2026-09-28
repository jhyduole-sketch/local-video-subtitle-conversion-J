"""根据环境检查生成首次使用指引；这里只返回建议，不执行安装。
Build first-run guidance from environment checks; return advice without installing dependencies.
"""
from __future__ import annotations

from pathlib import Path
import sys


def first_run_guidance(health: dict, settings_path: Path) -> dict[str, object]:
    commands = {
        "ffmpeg": "brew install ffmpeg" if sys.platform == "darwin" else "安装 FFmpeg 并将 ffmpeg、ffprobe 加入 PATH",
        "ffprobe": "brew install ffmpeg" if sys.platform == "darwin" else "安装 FFmpeg 并将 ffmpeg、ffprobe 加入 PATH",
        "whisper-cli": "brew install whisper-cpp" if sys.platform == "darwin" else "安装 whisper.cpp，或在页面选择 OpenAI 转写",
        "yt-dlp": "python3 -m pip install -U yt-dlp",
        "Whisper 模型": "按使用指南下载 Whisper 模型，并在高级设置中指定模型文件",
        "Python: openai": "python3 -m pip install -e .",
        "Python: transformers": "python3 -m pip install transformers sentencepiece protobuf",
        "Python: torch": "python3 -m pip install torch",
    }
    actions = []
    for check in health.get("checks", []):
        if isinstance(check, dict) and not check.get("ok"):
            name = str(check.get("name", "依赖"))
            actions.append({"name": name, "optional": bool(check.get("optional")), "action": commands.get(name, str(check.get("detail") or "查看环境检查和使用指南"))})
    steps = [f"{item['name']}：{item['action']}" for item in actions if not item["optional"]]
    steps += ["选择视频网址或上传本地视频", "先用短视频确认目标语言与字幕效果，再处理长视频"]
    if sys.platform != "darwin":
        steps.append("本平台当前未提供内置画面 OCR 引擎，可选择内置字幕或语音来源")
    return {"steps": steps, "actions": actions, "settingsPath": str(settings_path)}
