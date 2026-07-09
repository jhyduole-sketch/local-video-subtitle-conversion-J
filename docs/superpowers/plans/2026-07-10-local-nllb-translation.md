# Local NLLB Translation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an optional local multilingual NLLB translation engine while making z.ai the recommended default in the Web UI.

**Architecture:** Keep the existing local fast model path for zh/ja/en. Add a separate `local-nllb` translator path that uses `facebook/nllb-200-distilled-600M`, explicit language-code mapping, Hugging Face cache detection, and clear download hints.

**Tech Stack:** Python, transformers, torch, Hugging Face local cache, vanilla HTML/CSS/JS.

## Global Constraints

- Do not auto-download the NLLB model.
- Keep z.ai as the Web UI recommended default.
- Keep the existing local fast model available for offline zh/ja/en rough translation.
- Restart the local Web service after code changes.

---

### Task 1: NLLB Core

**Files:**
- Modify: `src/subtitle_tool/local_translate.py`
- Test: `tests/test_local_translate.py`

**Interfaces:**
- Produces: `translate_segments_with_nllb(segments, source_lang, target_lang) -> dict[int, str]`
- Produces: `nllb_model_status(cache_root=None) -> dict[str, object]`

- [ ] Add NLLB language-code mapping for common UI languages.
- [ ] Add source-language inference for zh/ja/en and simple script-based languages.
- [ ] Add cached model loading with `tokenizer.src_lang` and `forced_bos_token_id`.
- [ ] Test language mapping, missing-language errors, and model status.

### Task 2: Pipeline, CLI, Web

**Files:**
- Modify: `src/subtitle_tool/pipeline.py`
- Modify: `src/subtitle_tool/cli.py`
- Modify: `src/subtitle_tool/web.py`
- Modify: `src/subtitle_tool/web_assets/index.html`
- Test: `tests/test_cli.py`
- Test: `tests/test_web.py`

**Interfaces:**
- Consumes: `translate_segments_with_nllb`
- Adds translator choice: `local-nllb`

- [ ] Allow `local-nllb` in validation and CLI choices.
- [ ] Route `local-nllb` to the NLLB translator.
- [ ] Make Web default translator `z-ai`.
- [ ] Add NLLB environment status with download command.

### Task 3: Docs And Verification

**Files:**
- Modify: `README.md`

- [ ] Document the four translator options and NLLB tradeoffs.
- [ ] Run unit tests and JS syntax check.
- [ ] Restart `127.0.0.1:7860`.
