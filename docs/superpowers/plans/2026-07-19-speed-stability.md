# Subtitle Speed and Stability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce avoidable subtitle video processing time and make every generated artifact recoverable, measurable, and safe against partial failures.

**Architecture:** Add small reusable boundaries for stage timing, atomic files, and preflight checks. Keep the existing pipeline and cache identities, then replace per-language soft-subtitle muxing with one multi-track mux while preserving separate SRT files and single-language compatibility.

**Tech Stack:** Python 3.9+, FFmpeg/ffprobe, SQLite job history, unittest, vanilla JavaScript.

## Global Constraints

- Existing CLI arguments and single-language output names remain compatible.
- Existing translation, transcript, OCR, and checkpoint caches remain readable.
- Heavy local model inference and hard-subtitle encoding do not run concurrently.
- No Whisper chunking, model replacement, quantization, desktop packaging, or public-server work is included.
- New result fields are optional so old persisted jobs remain readable.
- Do not commit or push until the user explicitly requests it.

---

### Task 1: Stage Timing and Result Diagnostics

**Files:**
- Create: `src/subtitle_tool/performance.py`
- Modify: `src/subtitle_tool/pipeline.py`
- Modify: `src/subtitle_tool/web.py`
- Modify: `src/subtitle_tool/web_assets/app.js`
- Test: `tests/test_performance.py`
- Test: `tests/test_pipeline.py`
- Test: `tests/test_web.py`

**Interfaces:**
- Produces: `StageTimer`, `PipelineResult.stage_durations`, and `PipelineResult.total_duration_seconds`.

- [ ] Write tests for monotonic stage durations, nested language timing, optional result serialization, and old job payload compatibility.
- [ ] Run focused tests and verify the missing timing API fails.
- [ ] Implement the timer with `time.monotonic()` and explicit `finish(stage)` calls.
- [ ] Instrument input, source extraction, translation per language, subtitle writing, and video output.
- [ ] Render a concise timing summary in Web output and CLI output.
- [ ] Run focused tests and verify success.

### Task 2: Atomic Artifacts

**Files:**
- Create: `src/subtitle_tool/atomic_files.py`
- Modify: `src/subtitle_tool/srt.py`
- Modify: `src/subtitle_tool/subtitle_layout.py`
- Modify: `src/subtitle_tool/media.py`
- Modify: `src/subtitle_tool/asset_cache.py`
- Modify: `src/subtitle_tool/translation_cache.py`
- Test: `tests/test_atomic_files.py`
- Test: `tests/test_media.py`
- Test: `tests/test_translation_cache.py`

**Interfaces:**
- Produces: `atomic_write_text(path, text)`, `temporary_output_path(path)`, and `commit_output(temp, final)`.

- [ ] Write tests proving failed writes retain an older good file and failed FFmpeg output never replaces the final path.
- [ ] Implement same-directory temporary files and `os.replace()` commits.
- [ ] Route SRT, ASS, cache JSON, soft mux, and hard burn outputs through atomic helpers.
- [ ] Remove temporary artifacts on cancellation and failure.
- [ ] Run focused tests and verify success.

### Task 3: Disk and Input Preflight

**Files:**
- Create: `src/subtitle_tool/preflight.py`
- Modify: `src/subtitle_tool/pipeline.py`
- Modify: `src/subtitle_tool/errors.py`
- Test: `tests/test_preflight.py`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Produces: `PreflightReport`, `estimate_required_bytes()`, and `validate_processing_space()`.

- [ ] Write tests for soft, hard, subtitle-only, unwritable output, missing video stream, and insufficient-space failures.
- [ ] Implement estimates based on input size, output mode, and target count with a fixed safety reserve.
- [ ] Run preflight after local input resolution and before source extraction.
- [ ] Include required and available space in actionable errors and logs.
- [ ] Run focused tests and verify success.

### Task 4: One-Pass Multi-Language Soft Subtitle Video

**Files:**
- Modify: `src/subtitle_tool/media.py`
- Modify: `src/subtitle_tool/pipeline.py`
- Modify: `src/subtitle_tool/web.py`
- Modify: `src/subtitle_tool/web_assets/app.js`
- Test: `tests/test_media.py`
- Test: `tests/test_pipeline.py`
- Test: `tests/test_web.py`

**Interfaces:**
- Produces: `mux_subtitle_tracks(video_path, tracks, output_path, cancel_check)` and optional `PipelineResult.multilingual_subtitled_video_path`.

- [ ] Write command-construction tests for two subtitle tracks, language metadata, default disposition, and optional audio.
- [ ] Implement one FFmpeg invocation for all translated SRT files.
- [ ] Keep the existing single-language mux path and filename unchanged.
- [ ] For two or more successful languages, emit one `.multilingual.default-sub.mp4` and separate SRT files.
- [ ] Show the multilingual video once in Web results without duplicate cards.
- [ ] Run focused tests and verify success.

### Task 5: Resource-Aware Pipeline Coordination

**Files:**
- Create: `src/subtitle_tool/resource_scheduler.py`
- Modify: `src/subtitle_tool/pipeline.py`
- Modify: `src/subtitle_tool/web.py`
- Test: `tests/test_resource_scheduler.py`
- Test: `tests/test_pipeline.py`
- Test: `tests/test_web.py`

**Interfaces:**
- Produces: `ResourceScheduler`, `heavy_local_stage()`, and `light_io_stage()`.

- [ ] Write tests showing heavy stages serialize, waiting stages report status, cancellation works while waiting, and light I/O remains available.
- [ ] Implement an in-process scheduler with a single heavy-stage permit and cancellation-aware polling.
- [ ] Guard local Whisper, OCR, NLLB, and hard-subtitle encoding with the heavy permit.
- [ ] Keep cloud translation and stream-copy soft mux outside the heavy permit.
- [ ] Reuse the Web single-worker rule and report `等待本地资源` instead of appearing stalled.
- [ ] Run focused tests and verify success.

### Task 6: Conservative OCR Sampling Guard

**Files:**
- Modify: `src/subtitle_tool/macos_vision_ocr.py`
- Test: `tests/test_macos_vision_ocr.py`

**Interfaces:**
- Produces: duration-aware `effective_sample_interval_ms()` with a configurable maximum frame count.

- [ ] Write tests for short-video unchanged sampling, long-video frame caps, explicit environment overrides, and logged effective intervals.
- [ ] Probe duration before extraction and increase the interval only when the configured frame cap would be exceeded.
- [ ] Keep the normal 500 ms interval for short videos and avoid scene-change-only sampling.
- [ ] Run focused OCR tests and verify success.

### Task 7: Verification, Baseline Comparison, and Documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/使用指南.md`
- Modify: `docs/更新记录.md`

**Interfaces:**
- Consumes: stage metrics and all optimized output paths.
- Produces: user-facing behavior and validation notes.

- [ ] Run all focused tests after each task.
- [ ] Run `python3 -m unittest discover -s tests`.
- [ ] Run compileall, JavaScript syntax checks, and `git diff --check`.
- [ ] Run the existing short OCR sample and one multi-language soft-subtitle sample.
- [ ] Compare first-run, cached rerun, single-language soft, multi-language soft, and hard-subtitle stage timings.
- [ ] Document the timing panel, one-pass multilingual video, disk preflight, atomic outputs, and resource-wait logs.
- [ ] Restart `0.0.0.0:7860` and verify `/api/health`.
