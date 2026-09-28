"""只保存允许的非敏感设置，并逐字段恢复损坏的偏好。
Persist only allowed non-sensitive settings and recover damaged preferences field by field.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .atomic_files import atomic_write_text


DEFAULT_SETTINGS: dict[str, object] = {
    "outputDir": "output",
    "whisperModel": "models/ggml-base.bin",
    "whisperUseGpu": True,
    "whisperUseVad": True,
    "subtitleVideoMode": "soft",
    "subtitlePosition": "auto",
    "subtitleEncodingProfile": "auto",
    "cacheLimitGb": 10,
}
_ALLOWED_KEYS = frozenset(DEFAULT_SETTINGS)
_ENUM_VALUES = {
    "subtitleVideoMode": {"soft", "hard"},
    "subtitlePosition": {"auto", "above-bottom", "bottom", "top"},
    "subtitleEncodingProfile": {"auto", "hardware", "fast", "quality"},
}
_FORBIDDEN_PARTS = ("key", "token", "secret", "cookie", "authorization", "password")


def default_settings_path(project_root: Path) -> Path:
    return project_root / ".subtitle-tool-state" / "settings.json"


def load_user_settings(path: Path) -> dict[str, object]:
    values = dict(DEFAULT_SETTINGS)
    if not path.exists():
        return values
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return values
    if isinstance(raw, dict):
        for key, value in raw.items():
            try:
                values.update(validate_setting_values({key: value}))
            except ValueError:
                # 单个偏好损坏不应阻止启动，也不应丢弃其他有效设置。
                # A damaged preference should not prevent startup or discard other settings.
                continue
    return values


def save_user_settings(values: dict[str, Any], path: Path) -> dict[str, object]:
    safe = validate_setting_values(values)
    merged = dict(DEFAULT_SETTINGS)
    merged.update(safe)
    atomic_write_text(path, json.dumps(merged, ensure_ascii=False, sort_keys=True))
    return merged


def parse_boolean(value: object, name: str) -> bool:
    """只接受布尔值和明确的 true/false 字符串，避免隐式真值转换。
    Accept JSON booleans and explicit true/false strings, never truthy coercion.
    """
    if isinstance(value, str) and value.strip().lower() in {"true", "false"}:
        value = value.strip().lower() == "true"
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be true or false")
    return value


def validate_setting_values(values: dict[str, Any]) -> dict[str, object]:
    """校验已知设置，丢弃未知或敏感字段，不补入默认值。
    Validate known settings, dropping unknown/sensitive keys; do not add defaults.
    """
    if not isinstance(values, dict):
        raise ValueError("settings must be an object")
    safe: dict[str, object] = {}
    for key, value in values.items():
        normalized = str(key).lower()
        if key not in _ALLOWED_KEYS or any(part in normalized for part in _FORBIDDEN_PARTS):
            continue
        if key == "cacheLimitGb":
            if isinstance(value, str) and value.strip().isascii() and value.strip().isdigit():
                value = int(value.strip())
            if type(value) is not int or not 1 <= value <= 500:
                raise ValueError("cacheLimitGb must be an integer between 1 and 500")
            safe[key] = value
        elif key in {"whisperUseGpu", "whisperUseVad"}:
            safe[key] = parse_boolean(value, key)
        elif key in _ENUM_VALUES:
            if not isinstance(value, str) or value not in _ENUM_VALUES[key]:
                raise ValueError(f"{key} must be one of: {', '.join(sorted(_ENUM_VALUES[key]))}")
            safe[key] = value
        else:
            if not isinstance(value, str) or not value.strip() or any(ord(char) < 32 for char in value):
                raise ValueError(f"{key} must be a non-empty path string without control characters")
            safe[key] = value.strip()
    return safe


# 保留私有兼容入口，避免影响现有调用方。
# Preserve the private compatibility entry point for existing callers.
_safe_settings = validate_setting_values
