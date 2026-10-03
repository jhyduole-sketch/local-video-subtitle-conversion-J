# Remaining Hardening Implementation Plan

> Execution: superpowers:executing-plans, inline with a final independent review.

**Goal:** Complete the seven improvements approved in the conversation.
**Architecture:** Keep existing process, cache, job-store and browser boundaries. Add explicit cache identity, bounded in-memory views and retained-input management; use durable SQLite/JSON data for full history.
**Tech Stack:** Python >=3.9, unittest, SQLite, vanilla JavaScript, Node test runner.
**Spec:** The seven-item analysis and user's instruction to execute autonomously in this conversation.

## Global Constraints
- Chinese comments before English; preserve existing public calls with optional arguments.
- Do not delete actual user inputs, outputs, history or caches while implementing/testing.
- Retained input cleanup is an explicit UI action and protects files referenced by retained jobs.
- Full job logs remain available from SQLite; a missing database cannot recreate evicted log text.
- No live paid API requests or model downloads for regression tests.

## Review Focus
- Callback exceptions and closed output pipes must still reap child processes.
- Malformed cache structures, model changes and concurrent checkpoint writers.
- Symlinks and references from resumed/render jobs during input cleanup.
- Absolute log cursors after trimming, persistence failure and database recreation.
- UI stale responses and downloading a complete log after limiting the visible window.

## Tasks
1. Process lifecycle: tests for callback failure and pipe EOF timeout; cleanup on every exceptional exit; bounded optional streaming capture.
2. Cache validation: malformed mapping, indexes, values and engine tests; treat invalid files as misses.
3. Cache identity: configured translation model/endpoint/prompt version and local transcription model file signature; explicit force regeneration UI/CLI option.
4. Retained inputs: reference-aware summary and explicit unreferenced-file cleanup, API/UI and symlink tests.
5. Memory: job log tail with absolute cursors, terminal-job eviction, bounded browser log window and full-log download, bounded diagnostic subprocess capture.
6. CI/reproducibility: checked-in tested core dependency constraints and Python/Node automated regression workflow.
7. Checkpoints: bound cache session computes identity once; merge under a process-safe lock; avoid duplicate reads; benchmark operation counts.

For each task: add regression tests, observe RED, implement, observe GREEN and record results below. Run the full Python and Node suite, syntax checks, independent review, and update user/developer docs before delivery.

## Execution Ledger
- Start: clean main at 9f0995b. Ruling: use a dedicated branch in the existing clean checkout to keep changes directly available in this workspace; no unrelated edits present.
- Ruling: user explicitly authorized execution and routine decisions, so no additional skill approval checkpoints.
- Task 1 complete: callback failures and pipe EOF timeout RED→GREEN; 9 process tests pass. Streaming captures default to a 1 MiB tail; full-output callers can retain unlimited capture explicitly.
- Task 2 complete: malformed mapping/value/engine cases RED→GREEN; 4 cache tests pass.
- Baseline sandbox blocked local HTTP ports; re-running regression with approved loopback access.
- Task 3 implemented: cache keys include effective model/endpoint and policy revision; local model stat signature includes ctime/inode. Explicit force regeneration wired to UI/CLI and pipeline. Identity tests 4/4; pipeline 34/34.
- Task 7 complete: bound per-target SQLite checkpoint sessions; one identity calculation and changed-row UPSERT. Independent session merge and reset tests RED→GREEN; cache 6/6. Ruling: move checkpoint writes to per-identity SQLite to avoid growing JSON rewrites; old configuration-incomplete cache identities are intentionally cold.
- Task 4 implemented: reference-aware retained input totals and explicit cleanup API/UI. Descriptor-based non-following traversal; protects all retained job references, including render/resume. Tests 3/3; actual user files untouched.
- Task 5 implemented: 1000-entry memory/browser windows, durable log cursor, recent finished-job eviction, streaming log download; diagnostic subprocess output capped. Backend 3/3, history 5/5, Node 17/17. Database recreation explicitly reports lost evicted history.
- Task 6 implemented: Python 3.9/3.12 + Node 24 CI, pinned core runtime dependencies; clean-environment validation pending.
- Clean core-only Python 3.11 environment exposed an old fake-local-translator signature mismatch; updated the mock to accept current callback keyword arguments. Fresh environment then passed all 345 Python tests without optional model packages.
- Browser smoke (synthetic data only): 1250 log entries render exactly the last 1000; downloaded file has all 1250 entries in order. Retained-input summary shows 9 B reclaimable; confirmation opens/cancels correctly; no console errors. Temporary server/tab stopped; no real files cleaned.
- Independent whole-change review found three P2 recovery gaps. All accepted: SQLite data-page corruption during read/write, completed-job memory logs after external DB deletion, descendant process cleanup after leader exit.
- Final fixes: each regression first failed, then passed (cache 9/9, log memory 5/5, process 10/10); full suite rerun pending.
- Final: Ruling: hosted CI execution will be verified after push if available; real provider/model quality is outside this regression scope because no paid calls or model downloads are authorized for tests. Cost: functional mocks cannot assess translation quality.

- Final verification: Python 3.9 350/350 (12.469 s); clean Python 3.11 350/350 (12.092 s); Node 17/17; compileall, JS syntax, YAML parse and git diff --check pass. Real dual-process checkpoint merging, recovery downloads and positional option compatibility covered.
- Final review: all 3 accepted P2 findings fixed with RED→GREEN regressions; no deferred minor findings. Seven tasks complete locally.
- Integration: user previously authorized commit/push to the same remote. Use a fast-forward to main after final validation; no history rewriting.
- 2026-10-03 resume: previous commit attempt never executed because automatic approval review hit its usage limit. Staged content unchanged; remote/main still 9f0995b. Fresh Python 350/350 (12.651 s), Node 17/17 and compile checks pass. Retrying delivery through normal approval.
