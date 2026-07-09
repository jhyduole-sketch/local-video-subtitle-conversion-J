class SubtitleToolError(Exception):
    """Base error for user-facing subtitle tool failures."""


class DependencyError(SubtitleToolError):
    """Raised when a required external dependency is missing."""


class MediaError(SubtitleToolError):
    """Raised when media probing or extraction fails."""


class OpenAIConfigError(SubtitleToolError):
    """Raised when OpenAI configuration is missing or invalid."""

