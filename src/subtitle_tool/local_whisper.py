from __future__ import annotations

import shutil
from pathlib import Path
from typing import Callable

from .errors import DependencyError, SubtitleToolError
from .process_control import CancelCheck, run_process, timeout_seconds_from_env
from .srt import SubtitleSegment, read_srt


DEFAULT_MODEL_PATH = Path("models/ggml-base.bin")
DEFAULT_VAD_MODEL_PATH = Path("models/ggml-silero-v6.2.0.bin")
_gpu_failed = False


def _resolve_path(path: Path) -> Path:
    resolved = path.expanduser()
    if not resolved.is_absolute():
        resolved = Path.cwd() / resolved
    return resolved


def _build_command(
    whisper_cli: str,
    model: Path,
    audio_path: Path,
    source_lang: str | None,
    output_base: Path,
    *,
    use_gpu: bool,
    vad_model: Path | None,
) -> list[str]:
    command = [
        whisper_cli,
        "-m",
        str(model),
        "-f",
        str(audio_path),
        "-l",
        source_lang or "auto",
        "-ml",
        "80",
    ]
    if not use_gpu:
        command.append("-ng")
    if vad_model is not None:
        command.extend(["--vad", "-vm", str(vad_model)])
    command.extend(["-osrt", "-of", str(output_base), "-np"])
    return command


def transcribe_with_whisper_cpp(
    audio_path: Path,
    source_lang: str | None = None,
    model_path: Path | None = None,
    cancel_check: CancelCheck | None = None,
    progress_callback: Callable[[str], None] | None = None,
    use_gpu: bool = True,
    use_vad: bool = True,
    vad_model_path: Path | None = None,
) -> list[SubtitleSegment]:
    global _gpu_failed

    whisper_cli = shutil.which("whisper-cli")
    if whisper_cli is None:
        raise DependencyError(
            "whisper-cli is not installed. Install it with: brew install whisper-cpp"
        )

    model = _resolve_path(model_path or DEFAULT_MODEL_PATH)
    if not model.exists():
        raise DependencyError(
            f"Local Whisper model not found: {model}. Download one, for example ggml-base.bin."
        )

    output_base = audio_path.with_suffix("")
    output_srt = output_base.with_suffix(".srt")
    vad_model = _resolve_path(vad_model_path or DEFAULT_VAD_MODEL_PATH)
    if not use_vad or not vad_model.exists():
        if use_vad and progress_callback is not None:
            progress_callback("VAD 模型未安装，继续使用标准语音转写")
        vad_model = None
    elif progress_callback is not None:
        progress_callback("VAD 已启用，将跳过静音片段")

    effective_use_gpu = use_gpu and not _gpu_failed
    if effective_use_gpu and progress_callback is not None:
        progress_callback("本地 Whisper 已启用 Metal/GPU 加速")
    elif use_gpu and progress_callback is not None:
        progress_callback("Metal/GPU 此前运行失败，本次直接使用 CPU")

    command = _build_command(
        whisper_cli,
        model,
        audio_path,
        source_lang,
        output_base,
        use_gpu=effective_use_gpu,
        vad_model=vad_model,
    )
    output_srt.unlink(missing_ok=True)
    completed = _run_whisper_process(command, cancel_check, progress_callback)
    segments = _attempt_segments(
        completed.returncode, output_srt, require_dialogue=vad_model is not None
    )
    if not segments and effective_use_gpu:
        detail = _attempt_detail(completed, output_srt)
        _gpu_failed = True
        output_srt.unlink(missing_ok=True)
        if progress_callback is not None:
            progress_callback(
                f"Metal 转写未完成或产生空字幕，已切换 CPU 模式重试: {detail}"
            )
        command = _build_command(
            whisper_cli,
            model,
            audio_path,
            source_lang,
            output_base,
            use_gpu=False,
            vad_model=vad_model,
        )
        completed = _run_whisper_process(command, cancel_check, progress_callback)
        segments = _attempt_segments(
            completed.returncode, output_srt, require_dialogue=vad_model is not None
        )
    if not segments and vad_model is not None:
        detail = _attempt_detail(completed, output_srt)
        output_srt.unlink(missing_ok=True)
        if progress_callback is not None:
            progress_callback(
                f"VAD 未识别到可用对白，已关闭 VAD 并使用 CPU 标准转写重试: {detail}"
            )
        command = _build_command(
            whisper_cli,
            model,
            audio_path,
            source_lang,
            output_base,
            use_gpu=False,
            vad_model=None,
        )
        completed = _run_whisper_process(command, cancel_check, progress_callback)
        segments = _attempt_segments(completed.returncode, output_srt)
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise SubtitleToolError(f"Local Whisper transcription failed: {detail}")
    if not output_srt.exists():
        raise SubtitleToolError("Local Whisper did not produce an SRT file.")

    if not segments:
        raise SubtitleToolError("Local Whisper returned no subtitle segments.")
    return segments


def _attempt_segments(
    returncode: int, output_srt: Path, *, require_dialogue: bool = False
) -> list[SubtitleSegment]:
    if returncode != 0 or not output_srt.exists() or output_srt.stat().st_size == 0:
        return []
    segments = read_srt(output_srt)
    if require_dialogue and segments and all(
        _is_sound_cue(segment.text) for segment in segments
    ):
        return []
    return segments


def _is_sound_cue(text: str) -> bool:
    value = text.strip()
    pairs = (("(", ")"), ("（", "）"), ("[", "]"), ("【", "】"), ("<", ">"))
    return any(value.startswith(left) and value.endswith(right) for left, right in pairs)


def _run_whisper_process(
    command: list[str],
    cancel_check: CancelCheck | None,
    progress_callback: Callable[[str], None] | None,
):
    def heartbeat(elapsed_seconds: float) -> None:
        if progress_callback is not None:
            progress_callback(
                f"本地 Whisper 仍在运行，已用时 {_format_elapsed(elapsed_seconds)}"
            )

    return run_process(
        command,
        cancel_check=cancel_check,
        timeout_seconds=timeout_seconds_from_env(
            "SUBTITLE_TOOL_WHISPER_TIMEOUT_SECONDS", 7200.0
        ),
        heartbeat_interval_seconds=30.0,
        heartbeat_callback=heartbeat,
        operation_name="本地 Whisper 转写",
    )


def _format_elapsed(seconds: float) -> str:
    total = max(0, round(seconds))
    minutes, secs = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _attempt_detail(completed, output_srt: Path) -> str:
    if completed.returncode != 0:
        return completed.stderr.strip() or completed.stdout.strip() or "进程异常退出"
    if not output_srt.exists():
        return "没有生成 SRT 文件"
    return "生成的 SRT 为空或不包含有效字幕"
