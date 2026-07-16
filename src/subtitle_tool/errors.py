class SubtitleToolError(Exception):
    """Base error for user-facing subtitle tool failures."""


class DependencyError(SubtitleToolError):
    """Raised when a required external dependency is missing."""


class MediaError(SubtitleToolError):
    """Raised when media probing or extraction fails."""


class OpenAIConfigError(SubtitleToolError):
    """Raised when OpenAI configuration is missing or invalid."""


class ProviderRateLimitError(SubtitleToolError):
    """Raised after a translation provider exhausts rate-limit retries."""

    def __init__(self, provider: str, message: str):
        super().__init__(message)
        self.provider = provider


class CancellationError(SubtitleToolError):
    """Raised when a running task is cancelled by the user."""


class ProcessTimeoutError(SubtitleToolError):
    """Raised when an external process exceeds a safety limit."""


def actionable_error_message(exc: Exception) -> str:
    detail = str(exc).strip() or exc.__class__.__name__
    normalized = detail.lower()
    if isinstance(exc, ProcessTimeoutError):
        return detail
    if "no subtitle segments" in normalized or "did not produce an srt" in normalized:
        advice = (
            "语音识别没有识别到有效语音。系统已经尝试 CPU 和关闭 VAD；"
            "请确认视频包含清晰对白，也可以手动关闭 VAD、选择更大的 Whisper 模型，"
            "或改用 OpenAI 转写。"
        )
    elif "timed out" in normalized or "timeout" in normalized:
        advice = (
            "在线模型请求超时。请检查网络后稍后重试；如果持续失败，"
            "可切换本地模型，或在 .env 中适当调大对应超时时间。"
        )
    elif "429" in normalized or "rate limit" in normalized or "速率限制" in detail:
        advice = (
            "在线模型触发限流。请稍后重试、减少同时选择的目标语言，"
            "或切换本地模型/OpenAI 继续。"
        )
    elif "local translation model is not cached" in normalized:
        advice = "所选本地翻译模型尚未安装。请按页面环境区给出的下载命令安装，或切换在线翻译。"
    elif "download" in normalized and "failed" in normalized:
        advice = (
            "视频下载失败。请确认链接可以公开播放；如果网站需要登录、Cookie 或 DRM，"
            "请先下载视频后通过上传功能处理。"
        )
    else:
        return detail
    return f"{advice} 技术信息：{detail}"
