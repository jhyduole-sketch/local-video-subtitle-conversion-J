# Subtitle Layout and Stable Video Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent translated subtitles from overlapping each other or existing bottom hard subtitles, while offering both lossless soft-subtitle and position-stable hard-subtitle videos.

**Architecture:** Add a pure subtitle layout module between translation and SRT writing. Keep MP4 soft subtitle muxing unchanged, and add an ASS renderer plus a separate FFmpeg burn-in path for stable positioning.

**Tech Stack:** Python 3.9, dataclasses, Unicode display-width rules, SRT/ASS, FFmpeg, vanilla HTML/CSS/JavaScript, unittest.

## Global Constraints

- Route-two changes remain uncommitted until the user explicitly requests a commit.
- Soft subtitle output must keep video and audio streams without re-encoding.
- Hard subtitle output may re-encode video but must copy audio where supported.
- Subtitle text must never be truncated.
- Target subtitles must contain at most two visual lines per cue where timing permits safe splitting.

---

### Task 1: Subtitle layout engine

**Files:**
- Create: `src/subtitle_tool/subtitle_layout.py`
- Create: `tests/test_subtitle_layout.py`

**Interfaces:**
- Produces: `layout_subtitles(segments: list[SubtitleSegment], max_width: int = 42, max_lines: int = 2, min_gap_ms: int = 40) -> list[SubtitleSegment]`

- [ ] Write failing tests for English wrapping, CJK wrapping, long-cue splitting, text preservation, and overlapping cue repair.
- [ ] Run `python3 -m unittest tests.test_subtitle_layout` and verify the missing module/API failures.
- [ ] Implement display-width-aware wrapping, proportional timing split, overlap repair, and sequential indexes.
- [ ] Run the focused tests and verify they pass.

### Task 2: ASS renderer and hard subtitle video

**Files:**
- Modify: `src/subtitle_tool/subtitle_layout.py`
- Modify: `src/subtitle_tool/media.py`
- Modify: `tests/test_subtitle_layout.py`
- Modify: `tests/test_media.py`

**Interfaces:**
- Produces: `write_ass(path: Path, segments: list[SubtitleSegment], position: str) -> None`
- Produces: `burn_subtitle_track(video_path: Path, ass_path: Path, output_path: Path, cancel_check: CancelCheck | None = None) -> Path`

- [ ] Write failing tests for ASS bottom, above-bottom and top styles and FFmpeg burn-in arguments.
- [ ] Verify focused tests fail for the missing behavior.
- [ ] Implement ASS escaping/rendering and FFmpeg H.264 burn-in with copied audio.
- [ ] Verify focused tests pass.

### Task 3: Pipeline integration

**Files:**
- Modify: `src/subtitle_tool/pipeline.py`
- Modify: `tests/test_pipeline.py`

**Interfaces:**
- Extends: `PipelineOptions.subtitle_video_mode: str = "soft"`
- Extends: `PipelineOptions.subtitle_position: str = "auto"`

- [ ] Write failing tests that translated SRT is laid out and that hard mode calls the burn-in path instead of soft muxing.
- [ ] Verify the tests fail for missing integration.
- [ ] Validate mode/position, lay out translated segments, render ASS for hard mode, and preserve per-language video failure isolation.
- [ ] Verify pipeline tests pass.

### Task 4: CLI and Web controls

**Files:**
- Modify: `src/subtitle_tool/cli.py`
- Modify: `src/subtitle_tool/web.py`
- Modify: `src/subtitle_tool/web_assets/index.html`
- Modify: `src/subtitle_tool/web_assets/app.js`
- Modify: `src/subtitle_tool/web_assets/styles.css`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_web.py`

**Interfaces:**
- Adds CLI: `--subtitle-video-mode soft|hard`
- Adds CLI: `--subtitle-position auto|bottom|above-bottom|top`
- Adds Web payload: `subtitleVideoMode`, `subtitlePosition`

- [ ] Write failing CLI/Web tests for defaults and explicit options.
- [ ] Verify the tests fail.
- [ ] Add compact select controls, payload mapping, output labels, and a soft-mode positioning limitation hint.
- [ ] Verify CLI/Web tests and `node --check src/subtitle_tool/web_assets/app.js` pass.

### Task 5: Documentation and end-to-end verification

**Files:**
- Modify: `README.md`

- [ ] Document soft versus hard subtitle video, positioning behavior, quality trade-offs, and output filenames.
- [ ] Run `python3 -m unittest discover -s tests` and verify all tests pass.
- [ ] Run Python compile, JavaScript syntax, and `git diff --check` verification.
- [ ] Restart `http://127.0.0.1:7860/` and verify the controls and browser console.
- [ ] Confirm `git status` shows route-two work as uncommitted.

