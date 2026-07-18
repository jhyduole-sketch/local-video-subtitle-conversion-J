from __future__ import annotations

from importlib import util
import os
from pathlib import Path
import shutil

from .errors import SubtitleToolError
from .local_translate import local_translation_model_statuses, nllb_model_status
from .local_whisper import DEFAULT_VAD_MODEL_PATH
from .media import ass_ffmpeg_binary, videotoolbox_available
from .runtime_paths import cache_root
from .screen_ocr import available_screen_ocr_engines
from .translation_engines import NLLB_MODEL_NAME


def collect_health(project_root: Path | None = None) -> dict[str, object]:
    root = project_root or Path.cwd()
    checks = [
        _tool_check("ffmpeg"),
        _tool_check("ffprobe"),
        _ass_ffmpeg_check(),
        _videotoolbox_check(),
        _tool_check("yt-dlp"),
        _tool_check("whisper-cli"),
        _whisper_models_check(root),
        _whisper_vad_model_check(root),
        _python_module_check("openai"),
        _python_module_check("transformers"),
        _python_module_check("torch"),
        {
            "name": "ZAI_API_KEY",
            "ok": bool(os.environ.get("ZAI_API_KEY")),
            "optional": True,
            "detail": "已配置" if os.environ.get("ZAI_API_KEY") else "未配置",
        },
    ]
    checks.extend(_local_translation_model_checks())
    checks.append(_nllb_model_check(NLLB_MODEL_NAME, "本地多语言 NLLB 1.3B"))
    checks.append(_screen_ocr_check(root))
    return {
        "checks": checks,
        "ok": all(check["ok"] for check in checks if not check.get("optional")),
    }


def _ass_ffmpeg_check() -> dict[str, object]:
    try:
        binary = ass_ffmpeg_binary()
    except SubtitleToolError:
        return {
            "name": "固定位置硬字幕",
            "ok": False,
            "optional": True,
            "detail": "未安装；运行 brew install ffmpeg-full",
        }
    return {
        "name": "固定位置硬字幕",
        "ok": True,
        "optional": True,
        "detail": binary,
    }


def _videotoolbox_check() -> dict[str, object]:
    available = videotoolbox_available()
    return {
        "name": "Apple 硬件编码",
        "ok": available,
        "optional": True,
        "detail": "VideoToolbox 可用" if available else "不可用；自动模式将使用快速 CPU",
    }


def _tool_check(name: str) -> dict[str, object]:
    path = shutil.which(name)
    return {"name": name, "ok": path is not None, "detail": path or "未找到"}


def _python_module_check(name: str) -> dict[str, object]:
    spec = util.find_spec(name)
    return {
        "name": f"Python: {name}",
        "ok": spec is not None,
        "detail": "可用" if spec is not None else "未安装",
    }


def _whisper_models_check(root: Path) -> dict[str, object]:
    statuses = []
    has_any_model = False
    for name in ("base", "small", "medium"):
        path = root / "models" / f"ggml-{name}.bin"
        installed = path.exists() and path.stat().st_size > 0
        has_any_model = has_any_model or installed
        statuses.append(f"{name}: {'已安装' if installed else '未安装'}")
    return {
        "name": "Whisper 模型",
        "ok": has_any_model,
        "detail": "；".join(statuses),
    }


def _whisper_vad_model_check(root: Path) -> dict[str, object]:
    path = root / DEFAULT_VAD_MODEL_PATH
    installed = path.exists() and path.stat().st_size > 0
    return {
        "name": "Whisper VAD 模型",
        "ok": installed,
        "optional": True,
        "detail": str(path) if installed else "未安装；将自动使用标准语音转写",
    }


def _local_translation_model_checks() -> list[dict[str, object]]:
    checks = []
    for status in local_translation_model_statuses():
        installed = bool(status["installed"])
        detail = "已安装"
        if not installed:
            detail = f"未安装；下载命令：{status['downloadCommand']}"
        checks.append(
            {
                "name": f"本地翻译 {status['label']}",
                "ok": installed,
                "optional": True,
                "detail": detail,
            }
        )
    return checks


def _nllb_model_check(model_name: str, display_name: str) -> dict[str, object]:
    status = nllb_model_status(model_name=model_name)
    installed = bool(status["installed"])
    detail = "已安装"
    if not installed:
        detail = (
            "未安装；模型较大，首次下载较慢；下载命令："
            f"{status['downloadCommand']}"
        )
    return {
        "name": display_name,
        "ok": installed,
        "optional": True,
        "detail": detail,
    }


def _screen_ocr_check(root: Path) -> dict[str, object]:
    engines = available_screen_ocr_engines(cache_root(root / "output"))
    available = [engine.label for engine, status in engines if status.available]
    if available:
        detail = f"已安装：{', '.join(available)}"
        ok = True
    else:
        details = [status.detail for _, status in engines]
        detail = "；".join(details) or "未注册可用引擎"
        ok = False
    return {
        "name": "画面字幕 OCR",
        "ok": ok,
        "optional": True,
        "detail": detail,
    }
