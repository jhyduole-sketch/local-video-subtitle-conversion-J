from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Callable

from .errors import MediaError
from .process_control import (
    CancelCheck,
    run_process,
    run_process_streaming,
    timeout_seconds_from_env,
)
from .screen_ocr import (
    FrameOcrResult,
    OcrAvailability,
    OcrObservation,
    build_ocr_subtitle_segments,
)
from .srt import SubtitleSegment


class MacVisionOcrEngine:
    engine_id = "macos-vision"
    label = "macOS Vision"

    def __init__(self, cache_root: Path, sample_interval_ms: int = 500):
        self.cache_root = cache_root
        self.sample_interval_ms = sample_interval_ms

    def availability(self) -> OcrAvailability:
        if sys.platform != "darwin":
            return OcrAvailability(False, "macOS Vision 仅在 macOS 上可用")
        if shutil.which("swiftc") is None:
            return OcrAvailability(False, "缺少 Swift 编译器，无法启用 macOS Vision")
        if shutil.which("ffmpeg") is None:
            return OcrAvailability(False, "缺少 ffmpeg，无法抽取 OCR 视频帧")
        if not self._swift_source_path().is_file():
            return OcrAvailability(False, "缺少 macOS Vision OCR 辅助程序源码")
        return OcrAvailability(True, "可用")

    def ensure_helper(self) -> Path:
        helper_path = self.cache_root / "tools" / "vision-ocr"
        if helper_path.is_file() and helper_path.stat().st_size > 0:
            return helper_path

        swiftc = shutil.which("swiftc") or "swiftc"
        helper_path.parent.mkdir(parents=True, exist_ok=True)
        module_cache_path = self.cache_root / "tools" / "swift-module-cache"
        module_cache_path.mkdir(parents=True, exist_ok=True)
        command = [
            swiftc,
            "-O",
            "-module-cache-path",
            str(module_cache_path),
            str(self._swift_source_path()),
            "-o",
            str(helper_path),
        ]
        completed = run_process(
            command,
            timeout_seconds=timeout_seconds_from_env(
                "SUBTITLE_TOOL_OCR_COMPILE_TIMEOUT_SECONDS", 180
            ),
            operation_name="编译 macOS Vision OCR 工具",
        )
        if completed.returncode != 0 or not helper_path.is_file():
            detail = completed.stderr.strip() or completed.stdout.strip()
            raise MediaError(f"macOS Vision OCR 工具编译失败: {detail}")
        helper_path.chmod(0o755)
        return helper_path

    def frame_extraction_command(self, video_path: Path, frame_dir: Path) -> list[str]:
        frames_per_second = 1_000 / self.sample_interval_ms
        fps_value = f"{frames_per_second:g}"
        return [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(video_path),
            "-vf",
            f"fps={fps_value},scale=720:-2",
            "-q:v",
            "3",
            str(frame_dir / "frame-%08d.jpg"),
        ]

    def parse_helper_line(self, line: str) -> FrameOcrResult:
        try:
            payload = json.loads(line)
            frame_index = int(payload["frameIndex"])
            raw_observations = payload.get("observations", [])
            observations = tuple(
                OcrObservation(
                    text=str(item["text"]),
                    confidence=float(item["confidence"]),
                    x=float(item["x"]),
                    y=float(item["y"]),
                    width=float(item["width"]),
                    height=float(item["height"]),
                )
                for item in raw_observations
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"Vision OCR 返回了无法解析的数据: {line[:120]}") from exc
        return FrameOcrResult(
            timestamp_ms=max(0, frame_index - 1) * self.sample_interval_ms,
            observations=observations,
        )

    def recognize_video(
        self,
        video_path: Path,
        source_lang: str | None,
        *,
        cancel_check: CancelCheck | None = None,
        progress_callback: Callable[[str], None] | None = None,
    ) -> list[SubtitleSegment]:
        availability = self.availability()
        if not availability.available:
            raise MediaError(availability.detail)

        if progress_callback:
            progress_callback("画面字幕 OCR：准备 macOS Vision 引擎")
        helper_path = self.ensure_helper()

        with TemporaryDirectory(prefix="subtitle-screen-ocr-") as temporary_dir:
            frame_dir = Path(temporary_dir) / "frames"
            frame_dir.mkdir(parents=True, exist_ok=True)
            if progress_callback:
                progress_callback("画面字幕 OCR：正在抽取视频帧")
            extraction = run_process(
                self.frame_extraction_command(video_path, frame_dir),
                cancel_check=cancel_check,
                timeout_seconds=timeout_seconds_from_env(
                    "SUBTITLE_TOOL_OCR_FRAME_TIMEOUT_SECONDS", 1_800
                ),
                heartbeat_interval_seconds=30,
                heartbeat_callback=(
                    lambda elapsed: progress_callback(
                        f"画面字幕 OCR：抽帧仍在进行，已用时 {round(elapsed)} 秒"
                    )
                    if progress_callback
                    else None
                ),
                operation_name="画面字幕 OCR 抽帧",
            )
            if extraction.returncode != 0:
                detail = extraction.stderr.strip() or extraction.stdout.strip()
                raise MediaError(f"画面字幕 OCR 抽帧失败: {detail}")

            frame_count = len(list(frame_dir.glob("frame-*.jpg")))
            if frame_count == 0:
                raise MediaError("画面字幕 OCR 未能从视频中抽取任何画面")
            if progress_callback:
                progress_callback(f"画面字幕 OCR：开始识别 {frame_count} 帧")

            frames: list[FrameOcrResult] = []

            def receive_line(line: str) -> None:
                if not line.strip():
                    return
                frames.append(self.parse_helper_line(line))
                if progress_callback and (
                    len(frames) == 1
                    or len(frames) == frame_count
                    or len(frames) % max(1, frame_count // 10) == 0
                ):
                    percent = min(100, round(len(frames) * 100 / frame_count))
                    progress_callback(
                        f"画面字幕 OCR：已识别 {len(frames)}/{frame_count} 帧（{percent}%）"
                    )

            completed = run_process_streaming(
                [
                    str(helper_path),
                    str(frame_dir),
                    ",".join(_vision_languages(source_lang)),
                ],
                cancel_check=cancel_check,
                stdout_line_callback=receive_line,
                timeout_seconds=timeout_seconds_from_env(
                    "SUBTITLE_TOOL_OCR_RECOGNITION_TIMEOUT_SECONDS", 3_600
                ),
                inactivity_timeout_seconds=timeout_seconds_from_env(
                    "SUBTITLE_TOOL_OCR_INACTIVITY_TIMEOUT_SECONDS", 180
                ),
                heartbeat_interval_seconds=30,
                heartbeat_callback=(
                    lambda elapsed: progress_callback(
                        f"画面字幕 OCR：Vision 仍在识别，已用时 {round(elapsed)} 秒"
                    )
                    if progress_callback
                    else None
                ),
                operation_name="macOS Vision 画面字幕识别",
            )
            if completed.returncode != 0:
                detail = completed.stderr.strip() or completed.stdout.strip()
                raise MediaError(f"macOS Vision OCR 识别失败: {detail}")

        segments = build_ocr_subtitle_segments(
            frames, sample_interval_ms=self.sample_interval_ms
        )
        if not segments:
            raise MediaError("画面字幕 OCR 没有识别到可用字幕，请检查画面文字是否清晰")
        if progress_callback:
            progress_callback(f"画面字幕 OCR：已合并为 {len(segments)} 条源字幕")
        return segments

    @staticmethod
    def _swift_source_path() -> Path:
        return Path(__file__).resolve().parent / "swift" / "vision_ocr.swift"


def _vision_languages(source_lang: str | None) -> list[str]:
    normalized = (source_lang or "").lower()
    if normalized.startswith("ja"):
        return ["ja-JP", "en-US"]
    if normalized.startswith("zh"):
        return ["zh-Hans", "zh-Hant", "en-US"]
    if normalized.startswith("en"):
        return ["en-US"]
    return ["ja-JP", "zh-Hans", "zh-Hant", "en-US"]
