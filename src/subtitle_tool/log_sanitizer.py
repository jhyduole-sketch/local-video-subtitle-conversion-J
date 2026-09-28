"""清理对外展示的诊断信息；功能路径与原始任务记录保持可用。
Sanitize displayed diagnostics while preserving functional paths and original job records.
"""
from __future__ import annotations

from pathlib import Path
import re


_PATTERNS = (
    (re.compile(r"(?i)(authorization\s*:\s*bearer\s+)[^\s,;]+"), r"\1[已隐藏]"),
    (re.compile(r"(?i)((?:api[_-]?key|token|secret|password)\s*=\s*)[^\s,;]+"), r"\1[已隐藏]"),
    (re.compile(r"(?i)(cookie\s*:\s*)[^\s,;]+(?:[ \t]*;[ \t]*[^=;\s]+=[^;\r\n\s]*)*"), r"\1[已隐藏]"),
    (
        re.compile(r"(?i)([?&](?:signature|sig|token|expires|x-amz-signature)=)[^&#\s]+"),
        r"\1[已隐藏]",
    ),
)


def sanitize_diagnostic_text(text: str, home_directory: Path | None = None) -> str:
    result = str(text)
    for pattern, replacement in _PATTERNS:
        result = pattern.sub(replacement, result)
    if home_directory:
        result = result.replace(str(home_directory.expanduser()), "~")
    return result


def sanitize_result_diagnostics(result: dict | None) -> dict | None:
    if not isinstance(result, dict):
        return result
    # 复制诊断字段后脱敏，避免改写持久化记录或破坏可点击的成品路径。
    # Copy and sanitize diagnostic fields without mutating stored records or functional artifact paths.
    clean = dict(result)
    if isinstance(result.get("failedLanguages"), dict):
        clean["failedLanguages"] = {language: sanitize_diagnostic_text(message, Path.home()) for language, message in result["failedLanguages"].items()}
    if isinstance(result.get("translationAttempts"), dict):
        clean["translationAttempts"] = {
            language: [{**attempt, "detail": sanitize_diagnostic_text(attempt["detail"], Path.home())} if attempt.get("detail") else dict(attempt) for attempt in attempts]
            for language, attempts in result["translationAttempts"].items()
        }
    return clean
