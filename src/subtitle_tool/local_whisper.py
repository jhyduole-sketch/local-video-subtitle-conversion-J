from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .errors import DependencyError, SubtitleToolError
from .srt import SubtitleSegment, read_srt


DEFAULT_MODEL_PATH = Path("models/ggml-base.bin")


def transcribe_with_whisper_cpp(
    audio_path: Path,
    source_lang: str | None = None,
    model_path: Path | None = None,
) -> list[SubtitleSegment]:
    whisper_cli = shutil.which("whisper-cli")
    if whisper_cli is None:
        raise DependencyError(
            "whisper-cli is not installed. Install it with: brew install whisper-cpp"
        )

    model = (model_path or DEFAULT_MODEL_PATH).expanduser()
    if not model.is_absolute():
        model = Path.cwd() / model
    if not model.exists():
        raise DependencyError(
            f"Local Whisper model not found: {model}. Download one, for example ggml-base.bin."
        )

    output_base = audio_path.with_suffix("")
    output_srt = output_base.with_suffix(".srt")
    command = [
        whisper_cli,
        "-m",
        str(model),
        "-f",
        str(audio_path),
        "-l",
        source_lang or "auto",
        "-ng",
        "-osrt",
        "-of",
        str(output_base),
        "-np",
    ]
    completed = subprocess.run(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise SubtitleToolError(f"Local Whisper transcription failed: {detail}")
    if not output_srt.exists():
        raise SubtitleToolError("Local Whisper did not produce an SRT file.")

    segments = read_srt(output_srt)
    if not segments:
        raise SubtitleToolError("Local Whisper returned no subtitle segments.")
    return segments
