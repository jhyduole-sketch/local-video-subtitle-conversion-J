# Stage One Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make local transcription and long-running media operations recover automatically when possible, stop clearly when they are genuinely stalled, and present actionable Chinese error messages.

**Architecture:** Keep fallback policy close to the operation that owns it: Whisper validates both process status and generated SRT content, while the shared process runner owns deadlines, inactivity detection, termination, and heartbeat callbacks. Download and subtitle encoding pass operation-specific limits into that shared layer. A small error-advice formatter converts known technical failures into user actions without hiding the original diagnostic detail.

**Tech Stack:** Python 3.9, `unittest`, `subprocess`, `selectors`, whisper.cpp, yt-dlp, FFmpeg, existing local Web job callbacks.

## Global Constraints

- Do not add a new runtime dependency.
- Preserve task cancellation and process-group termination.
- Time limits must be configurable and conservative enough for long videos.
- Keep the original technical error available after the Chinese recovery advice.
- Do not commit or push until the user confirms the result.

---

### Task 1: Whisper result-aware fallback

**Files:**
- Modify: `src/subtitle_tool/local_whisper.py`
- Test: `tests/test_local_whisper.py`

**Interfaces:**
- Consumes: `run_process(command, cancel_check=...)` and generated `.srt` files.
- Produces: `transcribe_with_whisper_cpp(...)` that treats a missing, empty, or unparseable SRT as an unsuccessful attempt and retries CPU/no-VAD as appropriate.

- [ ] Add a failing test where GPU returns exit code 0 but writes an empty SRT; verify CPU with VAD is attempted.
- [ ] Add a failing test where CPU+VAD returns exit code 0 but writes an empty SRT; verify CPU without VAD produces the final segments.
- [ ] Run `python3 -m unittest tests.test_local_whisper` and confirm the new assertions fail because only non-zero exit codes trigger fallback.
- [ ] Add a result-validation helper and use it after each Whisper attempt.
- [ ] Run `python3 -m unittest tests.test_local_whisper` and confirm all Whisper tests pass.

### Task 2: Shared timeout, inactivity, and heartbeat controls

**Files:**
- Modify: `src/subtitle_tool/errors.py`
- Modify: `src/subtitle_tool/process_control.py`
- Test: `tests/test_process_control.py`

**Interfaces:**
- Produces: `ProcessTimeoutError(SubtitleToolError)`.
- Extends: `run_process(..., timeout_seconds=None, heartbeat_interval_seconds=None, heartbeat_callback=None, operation_name=None)`.
- Extends: `run_process_streaming(..., timeout_seconds=None, inactivity_timeout_seconds=None, heartbeat_interval_seconds=None, heartbeat_callback=None, operation_name=None)`.

- [ ] Add failing tests for overall timeout termination, streaming inactivity termination, and periodic heartbeat messages.
- [ ] Run `python3 -m unittest tests.test_process_control` and confirm the new keyword arguments are unsupported.
- [ ] Implement monotonic deadline tracking, process-group termination, and actionable timeout text.
- [ ] Run `python3 -m unittest tests.test_process_control` and confirm all process-control tests pass.

### Task 3: Wire operation-specific safety policies and advice

**Files:**
- Modify: `src/subtitle_tool/local_whisper.py`
- Modify: `src/subtitle_tool/youtube.py`
- Modify: `src/subtitle_tool/media.py`
- Modify: `src/subtitle_tool/errors.py`
- Modify: `src/subtitle_tool/web.py`
- Test: `tests/test_local_whisper.py`
- Test: `tests/test_youtube.py`
- Test: `tests/test_media.py`
- Test: `tests/test_web.py`

**Interfaces:**
- Produces: conservative per-operation timeout values configurable through environment variables.
- Produces: `actionable_error_message(exc)` for Web task logs and error fields.

- [ ] Add failing tests that download, Whisper, and hard-subtitle calls pass timeout/inactivity controls.
- [ ] Add failing Web tests for VAD/timeout/download/API error advice.
- [ ] Run the focused tests and confirm failures describe the missing safety arguments and advice.
- [ ] Wire configurable limits and heartbeat callbacks to existing progress logs.
- [ ] Use actionable advice in both normal jobs and edited-subtitle render jobs.
- [ ] Run the focused tests and confirm they pass.

### Task 4: Documentation and full verification

**Files:**
- Modify: `README.md`
- Modify: `docs/使用指南.md`
- Modify: `docs/更新记录.md`

**Interfaces:**
- Documents the exact automatic fallback order, timeout behavior, environment overrides, and user-visible recovery messages.

- [ ] Update Chinese-first documentation without claiming unsupported behavior.
- [ ] Run `python3 -m unittest discover -s tests` and require zero failures.
- [ ] Run `env PYTHONPYCACHEPREFIX=/private/tmp/subtitle-tool-pycache python3 -m compileall src tests` and require exit code 0.
- [ ] Run `node --check src/subtitle_tool/web_assets/app.js` and require exit code 0.
- [ ] Run `git diff --check` and inspect `git diff --stat`.
- [ ] Restart the Web service on `0.0.0.0:7860`, verify `/api/health`, and wait for user confirmation without committing.
