"""将下载错误归类为可操作的提示，保留技术详情供诊断。
Classify download failures into actionable guidance while retaining diagnostic details.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DownloadCapability:
    kind: str
    user_message: str
    technical_detail: str | None = None


def classify_download_error(detail: str) -> DownloadCapability:
    normalized = detail.lower()
    if "drm" in normalized or "widevine" in normalized or "protected content" in normalized:
        return DownloadCapability(
            "drm",
            "该视频受 DRM 内容保护，工具不能下载或绕过保护。请使用已合法取得的本地视频文件。",
            detail,
        )
    if any(token in normalized for token in ("sign in", "login", "cookie", "private", "not a bot")):
        return DownloadCapability(
            "login",
            "该网站要求登录或 Cookie 才能访问。工具不会自动读取浏览器 Cookie；请先在浏览器中合法下载视频后上传本地文件。",
            detail,
        )
    if any(token in normalized for token in ("unsupported url", "no suitable extractor", "can't find any video")):
        return DownloadCapability(
            "unsupported",
            "当前下载器暂不支持这个公开视频页面，或网站页面结构已变化。可先下载视频后上传处理。",
            detail,
        )
    if any(token in normalized for token in ("timed out", "network", "connection", "http error 5")):
        return DownloadCapability(
            "network",
            "视频下载遇到网络或站点临时问题，请稍后重试。",
            detail,
        )
    return DownloadCapability(
        "unknown",
        "视频下载失败。请确认链接可以公开播放；若网站需要登录、Cookie 或受保护内容，请先下载视频后上传处理。",
        detail,
    )
