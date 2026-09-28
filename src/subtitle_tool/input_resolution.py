"""统一准备本地与远程输入；由流水线注入下载依赖以保留兼容入口。
Prepare local and remote inputs using pipeline-injected download dependencies for compatibility.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from .errors import SubtitleToolError
if TYPE_CHECKING:
    from .pipeline import PipelineOptions
    from .asset_cache import AssetCache


def resolve_input(
    options: PipelineOptions,
    task_out_dir: Path,
    timestamp: str,
    asset_cache: AssetCache,
    *, dependencies,
) -> tuple[Path, Path | None]:
    if dependencies.is_talksmith_url(options.input_value):
        dependencies._progress(options, "解析公开视频链接并下载视频", 8)
        downloaded_path = dependencies.resolve_talksmith_input(
            options.input_value,
            asset_cache.videos_dir,
            options.force_download,
            None,
            options.cancel_check,
        )
        task_path = asset_cache.materialize_video(
            downloaded_path,
            task_out_dir / f"{dependencies.extract_scenario_id(options.input_value)}.{timestamp}.mp4",
        )
        return task_path, task_path

    if dependencies.is_youtube_url(options.input_value):
        dependencies._progress(options, "解析 YouTube 链接并下载视频", 8)
        video = dependencies.download_youtube_video(
            options.input_value,
            asset_cache.videos_dir,
            options.force_download,
            None,
            options.cancel_check,
            progress_callback=lambda message: dependencies._progress(options, message, 8),
        )
        task_path = asset_cache.materialize_video(
            video.path, task_out_dir / f"{video.video_id}.{timestamp}.mp4"
        )
        return task_path, task_path

    if dependencies.is_bilibili_url(options.input_value):
        dependencies._progress(options, "解析 Bilibili 链接并下载视频", 8)
        video = dependencies.download_bilibili_video(
            options.input_value,
            asset_cache.videos_dir,
            options.force_download,
            None,
            options.cancel_check,
            progress_callback=lambda message: dependencies._progress(options, message, 8),
        )
        task_path = asset_cache.materialize_video(
            video.path, task_out_dir / f"{video.video_id}.{timestamp}.mp4"
        )
        return task_path, task_path

    if dependencies.is_url(options.input_value):
        dependencies._progress(options, "未匹配专用站点，正在尝试通用网址解析", 8)
        video = dependencies.download_generic_video(
            options.input_value,
            asset_cache.videos_dir,
            options.force_download,
            None,
            options.cancel_check,
            progress_callback=lambda message: dependencies._progress(options, message, 8),
        )
        task_path = asset_cache.materialize_video(
            video.path, task_out_dir / f"{video.video_id}.{timestamp}.mp4"
        )
        return task_path, task_path

    input_path = Path(options.input_value).expanduser().resolve()
    dependencies._progress(options, "检查本地视频文件", 8)
    if not input_path.exists():
        raise SubtitleToolError(f"Input video does not exist: {input_path}")
    task_path = asset_cache.materialize_video(input_path, task_out_dir / input_path.name)
    return task_path, None
