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
