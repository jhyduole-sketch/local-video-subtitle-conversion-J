# Route One Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make local subtitle jobs queue safely, survive service restarts, reuse expensive intermediate assets, resume incomplete work, and stop external processes promptly.

**Architecture:** Add focused process-control, SQLite job-store, and asset-cache modules. Keep the existing pipeline API, extend it with a cancellation check and cache root, run Web jobs through one executor, persist every state change, and expose history/cache management through local JSON endpoints and the current Web UI.

**Tech Stack:** Python 3.9+, standard-library `sqlite3`, `concurrent.futures`, `subprocess`, JSON, HTML/CSS/JavaScript, `unittest`.

## Global Constraints

- Stability is the default priority; only one complete Web job runs at a time.
- Existing output folders and completed files are never deleted by cache cleanup.
- Service restart must preserve completed/failed/canceled jobs and mark in-flight jobs as interrupted and resumable.
- Resume reuses completed language translations and cached video/audio/transcription artifacts.
- Stop must terminate active `ffmpeg`, `yt-dlp`, and `whisper-cli` child processes promptly.
- Progress percentages never move backward.
- All route-one changes remain local and uncommitted until the user explicitly asks to submit code.

---

### Task 1: Cancellable external processes and monotonic progress

**Files:**
- Create: `src/subtitle_tool/process_control.py`
- Modify: `src/subtitle_tool/media.py`
- Modify: `src/subtitle_tool/local_whisper.py`
- Modify: `src/subtitle_tool/youtube.py`
- Modify: `src/subtitle_tool/pipeline.py`
- Modify: `src/subtitle_tool/web.py`
- Test: `tests/test_process_control.py`
- Test: `tests/test_web.py`

**Interfaces:**
- Produces: `run_process(command, cancel_check=None) -> subprocess.CompletedProcess[str]`.
- Produces: `PipelineOptions.cancel_check: Callable[[], bool] | None`.
- All external process helpers accept and forward `cancel_check`.

- [ ] Write tests proving cancellation terminates a running child and progress cannot decrease.
- [ ] Run `python3 -m unittest tests.test_process_control tests.test_web` and confirm failure.
- [ ] Implement `Popen.communicate(timeout=0.2)` polling, terminate/kill fallback, and `CancellationError` propagation.
- [ ] Pass the Web job cancellation flag through pipeline, media, download, Whisper, and mux calls.
- [ ] Run the focused tests and confirm they pass.

### Task 2: Single-job executor and persistent SQLite history

**Files:**
- Create: `src/subtitle_tool/job_store.py`
- Modify: `src/subtitle_tool/web.py`
- Test: `tests/test_job_store.py`
- Test: `tests/test_web.py`

**Interfaces:**
- Produces: `JobStore(path).save(record)`, `.get(job_id)`, `.list(limit=50)`, and `.mark_inflight_interrupted()`.
- Produces: Web endpoints `GET /api/jobs` and existing `GET /api/jobs/<id>` backed by memory plus SQLite.
- Uses: one `ThreadPoolExecutor(max_workers=1)` for complete Web jobs.

- [ ] Write tests for SQLite round-trip, startup interruption recovery, and non-overlapping queued jobs.
- [ ] Run focused tests and confirm failure.
- [ ] Implement schema initialization and atomic upsert of job payload, logs, result, progress, status, and timestamps.
- [ ] Replace thread-per-job submission with the single executor and persist every `_update_job` mutation.
- [ ] Load recent jobs at startup and expose history JSON.
- [ ] Run focused tests and confirm they pass.

### Task 3: Resumable jobs and completed-language reuse

**Files:**
- Modify: `src/subtitle_tool/job_store.py`
- Modify: `src/subtitle_tool/web.py`
- Modify: `src/subtitle_tool/pipeline.py`
- Modify: `src/subtitle_tool/translation_cache.py`
- Modify: `src/subtitle_tool/openai_client.py`
- Test: `tests/test_translation_cache.py`
- Test: `tests/test_openai_client.py`
- Test: `tests/test_pipeline.py`
- Test: `tests/test_web.py`

**Interfaces:**
- Produces: `POST /api/jobs/<id>/resume`, creating a new queued job linked by `resumedFrom`.
- Produces: partial translation cache entries containing completed indexes and engine metadata.
- `translate_segments_with_zai` accepts initial translations and a checkpoint callback.

- [ ] Write tests proving successful languages and z.ai batches are skipped after resume.
- [ ] Run focused tests and confirm failure.
- [ ] Store normalized input payload with each job and implement resume submission.
- [ ] Extend translation cache with partial load/store while retaining complete-cache behavior.
- [ ] Checkpoint each successful z.ai batch and continue only missing subtitle indexes.
- [ ] Run focused tests and confirm they pass.

### Task 4: Video, audio, embedded subtitle, and transcript cache

**Files:**
- Create: `src/subtitle_tool/asset_cache.py`
- Modify: `src/subtitle_tool/pipeline.py`
- Modify: `src/subtitle_tool/youtube.py`
- Modify: `src/subtitle_tool/talksmith.py`
- Test: `tests/test_asset_cache.py`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Produces: `AssetCache(root)` with content fingerprints and paths for `videos`, `audio`, `source-subtitles`, and `transcripts`.
- Remote videos download once to a stable cache path; each task gets a hard link when supported and a copy fallback otherwise.
- Transcript identity includes video fingerprint, source strategy, source language, transcriber, and Whisper model path.

- [ ] Write tests proving a second identical run skips download, audio extraction, and transcription.
- [ ] Run focused tests and confirm failure.
- [ ] Implement sampled file fingerprinting and stable cache paths under `<out-dir>/.subtitle-tool-cache/`.
- [ ] Integrate cache-hit logs and ensure `forceDownload` refreshes only the remote video artifact.
- [ ] Run focused tests and confirm they pass.

### Task 5: History and cache management UI

**Files:**
- Modify: `src/subtitle_tool/web.py`
- Modify: `src/subtitle_tool/web_assets/index.html`
- Modify: `src/subtitle_tool/web_assets/app.js`
- Modify: `src/subtitle_tool/web_assets/styles.css`
- Modify: `README.md`
- Test: `tests/test_web.py`

**Interfaces:**
- Produces: `GET /api/cache` with per-category bytes/files and `POST /api/cache/clear` with selected categories.
- Produces: history list with status, created time, targets, view-results action, and resume action for failed/interrupted jobs.
- Produces: cache panel with video/audio/transcript/translation sizes and explicit clear buttons.

- [ ] Write API tests for cache summaries, selective clear, and history payloads.
- [ ] Run Web tests and confirm failure.
- [ ] Implement endpoints and UI controls without nesting cards.
- [ ] Update README with queue, history, resume, cache, and hard-stop behavior.
- [ ] Run full tests, compile checks, JavaScript syntax check, restart `127.0.0.1:7860`, and verify the page in the in-app browser.
- [ ] Leave all route-one changes uncommitted.
