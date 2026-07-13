from __future__ import annotations

import shutil
from pathlib import Path
from typing import Callable

from .errors import DependencyError, SubtitleToolError
from .process_control import CancelCheck, run_process
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
    completed = run_process(command, cancel_check=cancel_check)
    if completed.returncode != 0 and effective_use_gpu:
        detail = completed.stderr.strip() or completed.stdout.strip()
        _gpu_failed = True
        if output_srt.exists():
            output_srt.unlink()
        if progress_callback is not None:
            progress_callback(
                f"Metal 转写未完成，已切换 CPU 模式重试: {detail}"
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
        completed = run_process(command, cancel_check=cancel_check)
    if completed.returncode != 0 and vad_model is not None:
        detail = completed.stderr.strip() or completed.stdout.strip()
        if output_srt.exists():
            output_srt.unlink()
        if progress_callback is not None:
            progress_callback(f"VAD 转写未完成，已关闭 VAD 重试: {detail}")
        command = _build_command(
            whisper_cli,
            model,
            audio_path,
            source_lang,
            output_base,
            use_gpu=False,
            vad_model=None,
        )
        completed = run_process(command, cancel_check=cancel_check)
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise SubtitleToolError(f"Local Whisper transcription failed: {detail}")
    if not output_srt.exists():
        raise SubtitleToolError("Local Whisper did not produce an SRT file.")

    segments = read_srt(output_srt)
    if not segments:
        raise SubtitleToolError("Local Whisper returned no subtitle segments.")
    return segments
