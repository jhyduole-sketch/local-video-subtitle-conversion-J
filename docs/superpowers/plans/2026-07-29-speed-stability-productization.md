# 字幕工具速度、稳定性与易用性升级 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让字幕任务能够预测耗时、可靠选择字幕来源和翻译引擎，并通过更清晰的下载、设置、缓存和诊断体验支持普通本地用户。

**Architecture:** 在既有 `PipelineOptions` 与 `PipelineResult` 上增加可选诊断字段，通过独立的性能估算、字幕质量评分、下载能力和设置模块减轻 `pipeline.py` 与 `web.py` 的职责。原有 CLI 参数、Web API 及任务数据库字段保持向后兼容；新增字段缺失时使用默认值。

**Tech Stack:** Python 3.9+、unittest、SQLite、FFmpeg/ffprobe、yt-dlp、vanilla JavaScript。

## 实施状态（2026-07-29）

- [x] 处理预估、结果序列化与页面/CLI展示。
- [x] 自动字幕来源质量评分与低质量自动回退。
- [x] 翻译回退尝试记录、失败分类与结果展示。
- [x] 公开下载失败能力分类（不读取 Cookie、不绕过 DRM）。
- [x] 非敏感本地偏好、缓存上限提醒、首次使用指导接口。
- [x] 诊断脱敏、中文主文档和英文摘要更新。
- [x] 输入解析器已在 2026-09-28 收尾中抽取为 `input_resolution.py`，来源与翻译流程也已拆分。

下方细分步骤保留为当时的实施设计；当前实现与验收状态以 [可靠性优化收尾计划](2026-09-27-reliability-completion.md) 为准。

## Global Constraints

- 不绕过 DRM，不自动读取或保存浏览器 Cookie。
- API Key 仅由环境变量或本地 `.env` 提供，Web 不回显或持久化密钥。
- 手动选择 `embedded`、`audio` 或 `screen-ocr` 时不自动替换字幕来源。
- 所有缓存和任务数据继续保存在本机；自动清理不触碰 `output/` 成品。
- 本轮不制作安装包、账号系统或服务器多租户功能。
- 仅在用户明确要求时提交或推送 GitHub。

---

### Task 1: 性能预估与结果诊断

**Files:**
- Create: `src/subtitle_tool/processing_estimate.py`
- Modify: `src/subtitle_tool/pipeline.py`
- Modify: `src/subtitle_tool/web.py`
- Modify: `src/subtitle_tool/web_assets/app.js`
- Test: `tests/test_processing_estimate.py`
- Test: `tests/test_pipeline.py`
- Test: `tests/test_web.py`

**Interfaces:**
- Produces: `ProcessingEstimate(seconds: int | None, factors: list[str])`.
- Produces: `estimate_processing(options, video_path, duration_seconds, cache_state) -> ProcessingEstimate`.
- Adds optional `PipelineResult.processing_estimate_seconds` and `PipelineResult.processing_estimate_factors`.

- [ ] **Step 1: Write failing estimate tests**

```python
def test_estimate_increases_for_hard_subtitles_and_multiple_languages():
    soft = estimate_processing(options_for("soft", ["ja"]), Path("clip.mp4"), 600, {})
    hard = estimate_processing(options_for("fixed", ["ja", "en"]), Path("clip.mp4"), 600, {})
    self.assertGreater(hard.seconds, soft.seconds)
    self.assertIn("固定位置硬字幕", hard.factors)
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `python3 -m unittest tests.test_processing_estimate -v`

Expected: failure because `subtitle_tool.processing_estimate` does not exist.

- [ ] **Step 3: Implement deterministic estimate helper**

```python
@dataclass(frozen=True)
class ProcessingEstimate:
    seconds: int | None
    factors: list[str]

def estimate_processing(options, video_path, duration_seconds, cache_state):
    base = max(10, int(duration_seconds * 0.12))
    if options.subtitle_video_mode == "fixed":
        base += int(duration_seconds * 0.8)
    base += max(0, len(options.target_langs) - 1) * int(duration_seconds * 0.08)
    return ProcessingEstimate(base, factors)
```

- [ ] **Step 4: Attach estimate at pipeline start and serialize it**

Use cached duration metadata when available, otherwise leave `seconds=None`. Include the estimate in `result_to_dict()` and render it in the task panel before work begins.

- [ ] **Step 5: Run focused tests and full regression test**

Run: `python3 -m unittest tests.test_processing_estimate tests.test_pipeline tests.test_web -v`

Expected: pass.

### Task 2: 字幕来源质量评分

**Files:**
- Create: `src/subtitle_tool/source_quality.py`
- Modify: `src/subtitle_tool/pipeline.py`
- Test: `tests/test_source_quality.py`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Produces: `SourceQuality(score: int, reasons: list[str])`.
- Produces: `score_source_segments(segments, expected_language, ocr_confidence=None) -> SourceQuality`.
- Adds optional `PipelineResult.source_quality` payload.

- [ ] **Step 1: Write failing quality tests**

```python
def test_repeated_short_transcript_scores_lower_than_varied_subtitles():
    repeated = score_source_segments(repeat("请上汤。", 20), "zh-CN")
    varied = score_source_segments([segment("第一句"), segment("第二句")], "zh-CN")
    self.assertLess(repeated.score, varied.score)
    self.assertIn("重复比例过高", repeated.reasons)
```

- [ ] **Step 2: Run focused test and verify RED**

Run: `python3 -m unittest tests.test_source_quality -v`

Expected: failure because `score_source_segments` is unavailable.

- [ ] **Step 3: Implement scoring with explicit penalties**

Score valid text, segment count and average text length; deduct for empty text, high normalized-text repetition, unusually short segments and low OCR confidence. Clamp the result to `0..100` and return user-readable reasons.

- [ ] **Step 4: Apply scoring only to auto source selection**

Keep manual `embedded`, `audio`, and `screen-ocr` selections fixed. In auto mode, log each candidate score and use a higher quality fallback when the initially selected candidate is below the minimum threshold.

- [ ] **Step 5: Run focused and full source-selection tests**

Run: `python3 -m unittest tests.test_source_quality tests.test_pipeline -v`

Expected: existing OCR fallback tests and new quality tests pass.

### Task 3: 云端翻译调度与快速回退

**Files:**
- Create: `src/subtitle_tool/translation_scheduler.py`
- Modify: `src/subtitle_tool/pipeline.py`
- Modify: `src/subtitle_tool/openai_client.py`
- Test: `tests/test_translation_scheduler.py`
- Test: `tests/test_pipeline.py`
- Test: `tests/test_openai_client.py`

**Interfaces:**
- Produces: `TranslationAttempt(engine: str, outcome: str, reason: str | None)`.
- Produces: `translate_with_fallback(target_lang, translate, fallbacks, checkpoint_callback) -> TranslationAttempt`.
- Adds `PipelineResult.translation_attempts: dict[str, list[dict[str, str]]]`.

- [ ] **Step 1: Write failing fallback-order test**

```python
def test_timeout_skips_remaining_zai_retries_and_uses_local_fallback():
    attempts = []
    result = translate_with_fallback("ja", failing_zai_timeout, [local_success], attempts.append)
    self.assertEqual(result.engine, "local-nllb-quality")
    self.assertEqual([item.engine for item in attempts], ["z-ai", "local-nllb-quality"])
```

- [ ] **Step 2: Run focused test and verify RED**

Run: `python3 -m unittest tests.test_translation_scheduler -v`

Expected: failure because the scheduler module does not exist.

- [ ] **Step 3: Implement typed outcome classification**

Treat rate limit, timeout, invalid output and unavailable-key errors as explicit outcomes. Preserve existing z.ai retry policy for rate limits; bypass additional retries after a terminal timeout and move to local / OpenAI fallback. Reuse partial translation cache before any new provider call.

- [ ] **Step 4: Integrate scheduler into `_translate_target`**

Keep target languages independent, append every provider switch to logs and `translation_attempts`, and ensure checkpoint callbacks preserve completed segment indexes.

- [ ] **Step 5: Run translation regression tests**

Run: `python3 -m unittest tests.test_translation_scheduler tests.test_openai_client tests.test_pipeline -v`

Expected: cache-resume, rate-limit fallback and timeout fallback tests pass.

### Task 4: 流程与下载适配边界

**Files:**
- Create: `src/subtitle_tool/input_resolution.py`
- Create: `src/subtitle_tool/download_capabilities.py`
- Modify: `src/subtitle_tool/pipeline.py`
- Modify: `src/subtitle_tool/youtube.py`
- Modify: `src/subtitle_tool/web.py`
- Test: `tests/test_input_resolution.py`
- Test: `tests/test_download_capabilities.py`
- Test: `tests/test_youtube.py`

**Interfaces:**
- Produces: `DownloadCapability(kind: str, user_message: str, technical_detail: str | None)`.
- Produces: `classify_download_error(message: str) -> DownloadCapability`.
- Produces: `resolve_input(options, cache, progress_callback) -> ResolvedInput`.

- [ ] **Step 1: Write failing download classification tests**

```python
def test_classify_download_error_marks_drm_as_unsupported():
    result = classify_download_error("This video is DRM protected")
    self.assertEqual(result.kind, "drm")
    self.assertIn("受 DRM 保护", result.user_message)
```

- [ ] **Step 2: Run focused test and verify RED**

Run: `python3 -m unittest tests.test_download_capabilities -v`

Expected: failure because `classify_download_error` does not exist.

- [ ] **Step 3: Implement capability classification and input resolver**

Map `login`, `cookie`, `private`, `DRM`, `unsupported`, `network` and unknown extractor failures to Chinese user messages while retaining sanitized extractor detail. Move `_resolve_input` body to `input_resolution.py`; retain a compatibility wrapper in `pipeline.py` until direct callers migrate.

- [ ] **Step 4: Return capability details through Web errors**

Keep the original error in job logs. Render the concise category and next action in the task panel; do not add any code that imports browser cookies or attempts DRM bypass.

- [ ] **Step 5: Run input and downloader tests**

Run: `python3 -m unittest tests.test_input_resolution tests.test_download_capabilities tests.test_youtube tests.test_pipeline -v`

Expected: existing YouTube, Bilibili and generic-public URL behavior remains compatible.

### Task 5: 本地设置、首次使用引导与资源建议

**Files:**
- Create: `src/subtitle_tool/user_settings.py`
- Modify: `src/subtitle_tool/health.py`
- Modify: `src/subtitle_tool/web.py`
- Modify: `src/subtitle_tool/web_assets/index.html`
- Modify: `src/subtitle_tool/web_assets/app.js`
- Modify: `src/subtitle_tool/web_assets/styles.css`
- Test: `tests/test_user_settings.py`
- Test: `tests/test_web.py`
- Test: `tests/test_health.py`

**Interfaces:**
- Produces: `load_user_settings() -> dict[str, object]` and `save_user_settings(values) -> dict[str, object]`.
- Produces: `first_run_guidance(health, settings) -> list[dict[str, str]]`.
- Produces Web endpoints `GET /api/settings`, `PUT /api/settings`, `GET /api/first-run-guidance`.

- [ ] **Step 1: Write failing settings persistence test**

```python
def test_settings_persist_non_sensitive_defaults_only():
    save_user_settings({"outputDir": "results", "openaiApiKey": "secret"})
    values = load_user_settings()
    self.assertEqual(values["outputDir"], "results")
    self.assertNotIn("openaiApiKey", values)
```

- [ ] **Step 2: Run focused test and verify RED**

Run: `python3 -m unittest tests.test_user_settings -v`

Expected: failure because the settings module does not exist.

- [ ] **Step 3: Implement allowlisted local settings**

Store JSON adjacent to the existing state database. Allow output directory, model selections, performance switches, subtitle mode and cache limit. Reject keys containing `key`, `token`, `secret`, `cookie` or `authorization`.

- [ ] **Step 4: Add guidance and cache-capacity warning**

Use `collect_health()` to identify missing tools/models. Add a `cacheLimitGb` default, show a warning when cache size exceeds it, and never delete outputs automatically. Add a compact first-run/settings section to the existing Web page.

- [ ] **Step 5: Run settings and UI tests**

Run: `python3 -m unittest tests.test_user_settings tests.test_health tests.test_web -v`

Expected: settings reject secret values and Web exposes only safe settings.

### Task 6: 日志脱敏、文档与全量验证

**Files:**
- Create: `src/subtitle_tool/log_sanitizer.py`
- Modify: `src/subtitle_tool/web.py`
- Modify: `src/subtitle_tool/cli.py`
- Modify: `README.md`
- Modify: `README.en.md`
- Modify: `docs/使用指南.md`
- Modify: `docs/更新记录.md`
- Test: `tests/test_log_sanitizer.py`
- Test: `tests/test_web.py`

**Interfaces:**
- Produces: `sanitize_diagnostic_text(text: str, home_directory: Path | None = None) -> str`.
- Applies sanitization only to copied/exported diagnostics and user-facing structured error details.

- [ ] **Step 1: Write failing sanitization tests**

```python
def test_sanitize_hides_api_key_cookie_and_home_directory():
    text = "Authorization: Bearer abc123 OPENAI_API_KEY=secret Cookie: sid=one /Users/name/video.mp4"
    result = sanitize_diagnostic_text(text, Path("/Users/name"))
    self.assertNotIn("abc123", result)
    self.assertNotIn("secret", result)
    self.assertNotIn("sid=one", result)
    self.assertIn("~/video.mp4", result)
```

- [ ] **Step 2: Run focused test and verify RED**

Run: `python3 -m unittest tests.test_log_sanitizer -v`

Expected: failure because `sanitize_diagnostic_text` does not exist.

- [ ] **Step 3: Implement sanitization and wire it to copy/export paths**

Redact bearer tokens, key-value secrets, cookie headers and query-string signature fields. Replace only the current user home prefix with `~`; do not mutate persisted raw task logs used for local debugging.

- [ ] **Step 4: Update Chinese-first documentation**

Document estimate interpretation, automatic source choice, download categories, safe settings, cache warning and diagnostic redaction. Update the English README with concise equivalents.

- [ ] **Step 5: Run final verification**

Run:

```bash
env PYTHONPYCACHEPREFIX=/private/tmp/subtitle-tool-pycache python3 -m unittest discover -s tests
env PYTHONPYCACHEPREFIX=/private/tmp/subtitle-tool-pycache python3 -m compileall -q src
node --check src/subtitle_tool/web_assets/app.js
git diff --check
```

Expected: all tests pass and all static checks exit with code 0. Do not create a Git commit or push without a separate explicit user request.
