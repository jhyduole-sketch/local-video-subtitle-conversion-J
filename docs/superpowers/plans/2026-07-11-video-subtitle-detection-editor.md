# Video Subtitle Detection and Editor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detect hard-subtitle screen regions for automatic avoidance and let users edit generated SRT files and regenerate videos.

**Architecture:** Add a dependency-light PGM frame analyzer and cache its result by video fingerprint. Add constrained subtitle file services and a queued render operation, then expose both through the existing local Web UI.

**Tech Stack:** Python 3.9, FFmpeg/ffprobe, PGM images, SRT/ASS, SQLite job queue, vanilla HTML/CSS/JavaScript, unittest.

## Global Constraints

- Do not commit or push these changes until explicitly requested.
- Do not erase or alter original hard subtitles.
- Do not allow subtitle APIs to access paths outside the selected output directory.
- Keep video rendering cancellable and serialized through the existing executor.

---

### Task 1: Frame analyzer

**Files:** Create `src/subtitle_tool/video_subtitle_detection.py`; create `tests/test_video_subtitle_detection.py`; modify `src/subtitle_tool/media.py` and `tests/test_media.py`.

- [ ] Write failing tests for top, bottom, none and uncertain edge maps.
- [ ] Implement PGM parsing, band scoring and position classification.
- [ ] Add cancellable FFmpeg sampling and verify focused tests.

### Task 2: Pipeline detection and cache

**Files:** Modify `src/subtitle_tool/asset_cache.py`, `src/subtitle_tool/pipeline.py`, `tests/test_asset_cache.py`, and `tests/test_pipeline.py`.

- [ ] Write failing tests for detection cache and auto-position mapping.
- [ ] Store detection JSON by video fingerprint and log confidence/final position.
- [ ] Verify focused tests.

### Task 3: Safe subtitle file service

**Files:** Create `src/subtitle_tool/subtitle_editor.py`; create `tests/test_subtitle_editor.py`; modify `src/subtitle_tool/web.py` and `tests/test_web.py`.

- [ ] Write failing tests for path containment, read, save, validation and backup.
- [ ] Implement constrained SRT read/write helpers and GET/PUT APIs.
- [ ] Verify focused tests.

### Task 4: Queued edited-video rendering

**Files:** Modify `src/subtitle_tool/pipeline.py`, `src/subtitle_tool/web.py`, `tests/test_pipeline.py`, and `tests/test_web.py`.

- [ ] Write failing tests for prepared video path and render job dispatch.
- [ ] Add edited render operation using existing soft/hard media functions and executor.
- [ ] Verify cancellation, result payload and focused tests.

### Task 5: Web editor

**Files:** Modify `src/subtitle_tool/web_assets/index.html`, `app.js`, and `styles.css`.

- [ ] Add a modal editor with editable timing/text rows and save controls.
- [ ] Wire output cards to load, save and regenerate APIs.
- [ ] Validate JavaScript and browser interactions.

### Task 6: Documentation and verification

**Files:** Modify `README.md`.

- [ ] Document detection confidence, editor backups and regeneration output.
- [ ] Run all tests, compile, JavaScript and diff checks.
- [ ] Restart the service and verify the page without committing.
