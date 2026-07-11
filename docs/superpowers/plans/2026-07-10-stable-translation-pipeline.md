# Stable Translation Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make subtitle jobs finish reliably under z.ai rate limits while reducing repeated API, local inference, and subtitle mux work.

**Architecture:** Keep z.ai requests globally serialized and dynamically batch subtitle segments by count and character budget. Route z.ai failures through local translation quality checks and then OpenAI, persist successful translation results in a content-addressed cache, batch local inference, and overlap one soft-subtitle mux operation with translation of the next language.

**Tech Stack:** Python 3.9+, `unittest`, OpenAI-compatible SDK, `transformers`, `torch`, `ffmpeg`, local JSON cache.

## Global Constraints

- Stability is the default priority; z.ai requests must not run concurrently inside one server process.
- After z.ai exhausts three rate-limit retries, automatically try local translation, then OpenAI when local output is unavailable or fails quality checks.
- Every automatic provider switch must appear in task progress logs and final result metadata.
- If OpenAI is not configured or also fails, do not emit a bad subtitle video for that language; preserve other successful languages.
- Do not re-encode video or audio when adding soft subtitles.
- Do not commit or push any change until the user finishes manual testing.

---

### Task 1: Provider fallback and z.ai request scheduling

**Files:**
- Modify: `src/subtitle_tool/errors.py`
- Modify: `src/subtitle_tool/openai_client.py`
- Modify: `src/subtitle_tool/pipeline.py`
- Modify: `src/subtitle_tool/web.py`
- Test: `tests/test_openai_client.py`
- Test: `tests/test_pipeline.py`
- Test: `tests/test_web.py`

**Interfaces:**
- Produces: `ProviderRateLimitError(provider: str, message: str)` for exhausted z.ai retries.
- Produces: `PipelineResult.translation_engines: dict[str, str]` describing the engine that produced each target language.
- Produces: `_translate_with_fallback(...) -> tuple[dict[int, str], str]` with engine labels `z.ai`, `local`, or `OpenAI`.

- [ ] **Step 1: Write failing tests for exhausted rate-limit errors and fallback order**

```python
def test_zai_raises_provider_rate_limit_after_retries():
    # Force every chat request to return 429/1302 and assert the typed error.

def test_zai_falls_back_to_local_and_records_engine():
    # z.ai raises ProviderRateLimitError; local succeeds; OpenAI is not called.

def test_bad_local_fallback_continues_to_openai():
    # z.ai rate-limits; local raises quality error; OpenAI succeeds.
```

- [ ] **Step 2: Run focused tests and confirm the new assertions fail**

Run: `python3 -m unittest tests.test_openai_client tests.test_pipeline tests.test_web`

Expected: FAIL because `ProviderRateLimitError`, fallback routing, and engine metadata do not exist.

- [ ] **Step 3: Implement typed z.ai exhaustion, one-process request serialization, and provider fallback**

```python
class ProviderRateLimitError(SubtitleToolError):
    def __init__(self, provider: str, message: str):
        super().__init__(message)
        self.provider = provider

_ZAI_REQUEST_LOCK = threading.Lock()

def _translate_with_fallback(...):
    try:
        return translate_segments_with_zai(...), "z.ai"
    except ProviderRateLimitError:
        progress("z.ai 连续限流，已自动切换本地模型")
        try:
            return translate_segments_with_nllb(...), "local"
        except Exception as local_error:
            progress(f"本地翻译未通过质量检查，已自动切换 OpenAI: {local_error}")
            return translate_segments(...), "OpenAI"
```

Use the existing local pair model first when supported and cached, then NLLB. Treat any local quality exception as a reason to continue to OpenAI. Keep same-language passthrough ahead of provider routing.

- [ ] **Step 4: Run focused tests and confirm they pass**

Run: `python3 -m unittest tests.test_openai_client tests.test_pipeline tests.test_web`

Expected: PASS.

---

### Task 2: Dynamic z.ai batches and persistent translation cache

**Files:**
- Create: `src/subtitle_tool/translation_cache.py`
- Modify: `src/subtitle_tool/openai_client.py`
- Modify: `src/subtitle_tool/pipeline.py`
- Test: `tests/test_translation_cache.py`
- Test: `tests/test_openai_client.py`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Produces: `chunk_segments_by_budget(segments, max_segments, max_characters) -> list[list[SubtitleSegment]]`.
- Produces: `TranslationCache(root: Path).load(...) -> dict[int, str] | None` and `.store(...) -> None`.
- Cache identity includes source text, source language, target language, and provider; it never includes API keys.

- [ ] **Step 1: Write failing tests for dynamic chunk limits and cache reuse**

```python
def test_dynamic_chunks_respect_count_and_character_budget():
    batches = chunk_segments_by_budget(segments, max_segments=24, max_characters=120)
    assert all(len(batch) <= 24 for batch in batches)
    assert all(sum(len(item.text) for item in batch) <= 120 for batch in batches)

def test_second_identical_translation_uses_cache():
    # First run stores translated indexes; second run returns them without provider call.
```

- [ ] **Step 2: Run focused tests and confirm they fail**

Run: `python3 -m unittest tests.test_translation_cache tests.test_openai_client tests.test_pipeline`

Expected: FAIL because the cache and dynamic chunk helper do not exist.

- [ ] **Step 3: Implement atomic JSON cache and dynamic batching**

```python
cache_key = sha256(json.dumps({
    "source": source_lang or "auto",
    "target": target_lang,
    "provider": provider,
    "segments": [{"index": s.index, "text": s.text} for s in segments],
}, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
```

Store cache files under `<out-dir>/.subtitle-tool-cache/translations/`. Write to a temporary sibling and replace atomically. Default z.ai limits: 24 segments and 4,000 source characters per batch, both configurable by environment variables. Report cache hits in task logs.

- [ ] **Step 4: Run focused tests and confirm they pass**

Run: `python3 -m unittest tests.test_translation_cache tests.test_openai_client tests.test_pipeline`

Expected: PASS.

---

### Task 3: Batched local inference and stronger quality validation

**Files:**
- Modify: `src/subtitle_tool/local_translate.py`
- Test: `tests/test_local_translate.py`

**Interfaces:**
- Produces: `_translate_batches(...)` shared by pair-specific and NLLB translation.
- Produces: quality checks for Unicode replacement characters, control characters, empty output, extreme length, repetition, and obvious target-script mismatch.

- [ ] **Step 1: Write failing tests for batch tokenization and malformed output rejection**

```python
def test_local_translation_rejects_replacement_characters():
    with self.assertRaisesRegex(SubtitleToolError, "invalid characters"):
        _validate_local_translation(segment, "hello\ufffdworld", "en")

def test_local_translation_tokenizes_multiple_segments_per_call():
    # Fake tokenizer/model and assert one call receives a list of source texts.
```

- [ ] **Step 2: Run local translation tests and confirm failure**

Run: `python3 -m unittest tests.test_local_translate`

Expected: FAIL because malformed Unicode is accepted and inference is per segment.

- [ ] **Step 3: Implement configurable local batches**

Tokenize up to `LOCAL_TRANSLATION_BATCH_SIZE` subtitles together, default `8`, with padding and truncation. Decode with `batch_decode`, validate each result against its original segment, and retain the existing `lru_cache` model reuse. Keep CPU as the stability-first default; allow `LOCAL_TRANSLATION_DEVICE=mps` as an opt-in acceleration path and fall back to CPU with a progress/error message if MPS inference fails.

- [ ] **Step 4: Run local translation tests and confirm they pass**

Run: `python3 -m unittest tests.test_local_translate`

Expected: PASS.

---

### Task 4: Single-worker soft-subtitle mux pipeline and full verification

**Files:**
- Modify: `src/subtitle_tool/pipeline.py`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Uses: `ThreadPoolExecutor(max_workers=1)` only for `mux_subtitle_track` work.
- Keeps: translation provider calls serialized and local model execution outside the mux executor.

- [ ] **Step 1: Write a failing test proving the next language starts before the previous mux finishes**

Use synchronization events in mocked `mux_subtitle_track` and translation functions; assert at most one mux runs and translation can proceed while it is waiting.

- [ ] **Step 2: Run pipeline tests and confirm failure**

Run: `python3 -m unittest tests.test_pipeline`

Expected: FAIL because mux currently blocks the translation loop.

- [ ] **Step 3: Submit successful language mux jobs to one executor and collect results safely**

Do not mark a translated subtitle as failed when only muxing fails. Record mux failures separately in progress logs and `failed_languages` with a clear `video:` prefix while preserving the generated SRT.

- [ ] **Step 4: Run the complete verification suite**

Run: `python3 -m unittest discover -s tests`

Expected: all tests pass.

Run: `env PYTHONPYCACHEPREFIX=/private/tmp/subtitle-tool-pycache python3 -m compileall src tests`

Expected: exit code 0.

Run: `node --check src/subtitle_tool/web_assets/app.js`

Expected: exit code 0.

- [ ] **Step 5: Restart and smoke-test the local Web service**

Restart `env PYTHONPATH=src python3 -m subtitle_tool.web --host 127.0.0.1 --port 7860`, open `http://127.0.0.1:7860/`, verify the health panel loads, and confirm no browser console errors. Do not commit or push.
