# Pluggable Screen OCR Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate source SRT subtitles from hardcoded on-screen text when audio transcription is unavailable or clearly hallucinates repeated text.

**Architecture:** Add a platform-neutral OCR engine protocol and registry, then implement a macOS Vision adapter behind that boundary. Keep OCR observation filtering and temporal subtitle construction in pure Python so it is portable and testable.

**Tech Stack:** Python 3.9+, FFmpeg, Swift 6, macOS Vision, unittest.

## Global Constraints

- Existing embedded subtitle and audio workflows must remain unchanged for valid inputs.
- Apple Vision is optional and must not prevent Linux or Windows startup.
- No new Python runtime dependency is required.
- All behavior changes are test-first.
- Do not commit or push until the user explicitly requests it.

---

### Task 1: Portable OCR Model and Quality Rules

**Files:**
- Create: `src/subtitle_tool/screen_ocr.py`
- Test: `tests/test_screen_ocr.py`

**Interfaces:**
- Produces: `ScreenOcrEngine`, `OcrAvailability`, `OcrObservation`, `FrameOcrResult`, `build_ocr_subtitle_segments()`, `is_suspicious_transcript()`.

- [ ] Write failing tests for repeated transcript detection, observation filtering, exact-text extension, one-frame gaps, and text changes.
- [ ] Run `python3 -m unittest tests.test_screen_ocr` and verify failures.
- [ ] Implement the pure Python model and algorithms.
- [ ] Re-run the focused tests and verify success.

### Task 2: macOS Vision Adapter

**Files:**
- Create: `src/subtitle_tool/macos_vision_ocr.py`
- Create: `src/subtitle_tool/swift/vision_ocr.swift`
- Modify: `pyproject.toml`
- Test: `tests/test_macos_vision_ocr.py`

**Interfaces:**
- Consumes: portable OCR model from Task 1.
- Produces: `MacVisionOcrEngine` and `available_screen_ocr_engines()`.

- [ ] Write failing tests for availability, cached helper compilation, frame command construction, JSON parsing, and missing-result errors.
- [ ] Verify focused tests fail.
- [ ] Implement helper compilation, frame extraction, streaming Vision execution, and result conversion.
- [ ] Package the Swift source and verify focused tests pass.

### Task 3: Pipeline Integration and Cache

**Files:**
- Modify: `src/subtitle_tool/pipeline.py`
- Modify: `src/subtitle_tool/asset_cache.py`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `get_screen_ocr_engine()` and `is_suspicious_transcript()`.
- Produces: `source=screen-ocr`, `screen-ocr-macos-vision`, and cached OCR source subtitles.

- [ ] Write failing tests for explicit OCR, auto fallback from repeated Whisper output, cached bad transcript rejection, and unavailable OCR errors.
- [ ] Verify tests fail for the intended missing behavior.
- [ ] Implement source routing, cache storage, logs, and actionable errors.
- [ ] Verify pipeline and cache tests pass.

### Task 4: CLI, Web, and Health

**Files:**
- Modify: `src/subtitle_tool/cli.py`
- Modify: `src/subtitle_tool/web_assets/index.html`
- Modify: `src/subtitle_tool/web.py`
- Modify: `src/subtitle_tool/health.py`
- Test: `tests/test_cli.py`
- Test: `tests/test_web.py`
- Test: `tests/test_health.py`

**Interfaces:**
- Produces: user-selectable “画面字幕 OCR” source and optional health result.

- [ ] Write failing tests for the new source value and health status.
- [ ] Add the CLI/Web source option and optional environment check.
- [ ] Run focused UI/API tests.

### Task 5: Real Video Verification and Documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/使用指南.md`
- Modify: `docs/更新记录.md`

- [ ] Run OCR against the local `6bQKTzDHUPY` sample and inspect generated Japanese segments.
- [ ] Confirm “ただでさえ暑いのに” and “料理で発散” appear in the generated source SRT.
- [ ] Run the complete unittest suite, compileall, JavaScript syntax checks, and `git diff --check`.
- [ ] Update Chinese-first documentation and restart `0.0.0.0:7860`.

