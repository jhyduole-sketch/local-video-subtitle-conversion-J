"""协调翻译回退、断点与实际引擎记录，取消信号直接向上传播。
Coordinate translation fallback, checkpoints, and engine provenance; propagate cancellation.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .errors import CancellationError, ProcessTimeoutError, ProviderRateLimitError, SubtitleToolError
from .srt import SubtitleSegment
from .translation_engines import canonical_translator_id, translator_label


@dataclass(frozen=True)
class TranslationAttempt:
    engine: str
    outcome: str
    detail: str | None = None
    category: str | None = None

    def to_dict(self) -> dict[str, str]:
        value = {"engine": self.engine, "outcome": self.outcome}
        if self.detail:
            value["detail"] = self.detail
        if self.category:
            value["category"] = self.category
        return value


def classify_translation_failure(error: Exception | str) -> str:
    if isinstance(error, ProviderRateLimitError):
        return "rate-limit"
    if isinstance(error, (TimeoutError, ProcessTimeoutError)):
        return "timeout"
    detail = str(error).lower()
    if "timeout" in detail or "timed out" in detail:
        return "timeout"
    if "429" in detail or "rate limit" in detail or "速率限制" in detail:
        return "rate-limit"
    if "repetitive" in detail or "quality" in detail:
        return "quality-rejected"
    return "failed"


def _deduplicate_translation_segments(
    segments: list[SubtitleSegment],
) -> tuple[list[SubtitleSegment], dict[int, int]]:
    representatives: dict[str, int] = {}
    representative_indexes: dict[int, int] = {}
    unique_segments: list[SubtitleSegment] = []
    for segment in segments:
        normalized_text = " ".join(segment.text.split())
        representative_index = representatives.get(normalized_text)
        if representative_index is None:
            representative_index = segment.index
            representatives[normalized_text] = representative_index
            unique_segments.append(segment)
        representative_indexes[segment.index] = representative_index
    return unique_segments, representative_indexes


def _collapse_initial_translations(
    translations: dict[int, str] | None,
    representative_indexes: dict[int, int],
) -> dict[int, str] | None:
    if not translations:
        return None
    collapsed: dict[int, str] = {}
    for index, text in translations.items():
        representative_index = representative_indexes.get(index)
        if representative_index is not None and text.strip():
            collapsed.setdefault(representative_index, text)
    return collapsed or None


def _expand_deduplicated_translations(
    translations: dict[int, str],
    representative_indexes: dict[int, int],
) -> dict[int, str]:
    return {
        index: translations[representative_index]
        for index, representative_index in representative_indexes.items()
        if representative_index in translations
    }


def schedule_translation(
    options, source_segments, target_lang, progress_percent, *,
    dependencies, run_state, initial_translations=None, checkpoint_callback=None,
    final_progress_percent=None, attempt_callback=None, initial_engine=None,
):
    """引擎尝试共享已完成翻译，后续回退只增加完成结果。

    缓存名称标识请求策略；引擎名称标识实际产出者，包括混合结果和恢复的断点。

    Execute provider attempts with shared, monotonic completed translations.

    Cache provider names identify the requested strategy. Engine labels identify
    the actual producers, including mixed output and resumed checkpoints.
    """
    d = dependencies
    unique, indexes = _deduplicate_translation_segments(source_segments)
    completed = _collapse_initial_translations(initial_translations, indexes) or {}
    producers = [initial_engine or "恢复的翻译断点"] if completed else []
    valid_indexes = {s.index for s in unique}
    live_progress = progress_percent
    progress_end = max(progress_percent, final_progress_percent or progress_percent)
    active_engine = ""
    if len(unique) != len(source_segments):
        d._progress(options, f"重复字幕复用: {len(source_segments)} 条合并为 {len(unique)} 条翻译，复用 {len(source_segments) - len(unique)} 条", progress_percent)

    def check_cancel():
        if options.cancel_check and options.cancel_check():
            raise CancellationError("Task cancelled")

    def checkpoint(values):
        nonlocal live_progress
        check_cancel()
        # 已有成功结果不覆盖；失败引擎已完成的批次可由后续引擎继续复用。
        # Never overwrite completed results; later engines reuse successful batches from failed attempts.
        new = {i: text for i, text in values.items() if i in valid_indexes and isinstance(text, str) and text.strip() and i not in completed}
        if new:
            completed.update(new)
            if active_engine not in producers:
                producers.append(active_engine)
        run_state.checkpoint_engine = " + ".join(producers) or active_engine
        expanded = _expand_deduplicated_translations(completed, indexes)
        if checkpoint_callback:
            checkpoint_callback(expanded)
        if source_segments:
            live_progress = max(live_progress, progress_percent + round((progress_end - progress_percent) * len(expanded) / len(source_segments)))
        d._progress(options, f"翻译进度: {target_lang} · {len(expanded)}/{len(source_segments)}", live_progress)

    def record(engine, outcome, error=None):
        if attempt_callback:
            attempt_callback(TranslationAttempt(engine, outcome, str(error) if error else None, classify_translation_failure(error) if isinstance(error, Exception) else None))

    translator = canonical_translator_id(options.translator)
    engines = [translator] if translator != "z-ai" else ["z-ai", "local-transformer", "local-nllb-quality", "openai"]
    last_error = None
    for engine_id in engines:
        check_cancel()
        active_engine = translator_label(engine_id)
        if engine_id == "z-ai" and run_state.zai_circuit_open:
            record(active_engine, "skipped", run_state.zai_failure_reason or "前一目标语言请求失败")
            d._progress(options, "z.ai 已熔断，本语言直接使用本地模型", live_progress)
            continue
        if set(completed) == valid_indexes:
            break
        pending = [s for s in unique if s.index not in completed]
        try:
            if engine_id == "z-ai":
                result = d.translate_segments_with_zai(
                    unique, target_lang=target_lang, source_lang=options.source_lang,
                    **({"cancel_check": options.cancel_check} if options.cancel_check else {}),
                    initial_translations=dict(completed) or None, checkpoint_callback=checkpoint,
                    progress_callback=lambda message: d._progress(options, message, live_progress),
                )
            elif engine_id == "local-nllb-quality":
                result = d._heavy_call(options, f"本地 NLLB 翻译 {target_lang}", lambda: d.translate_segments_with_nllb(
                    unique, options.source_lang, target_lang,
                    model_name=d.NLLB_QUALITY_MODEL_NAME,
                    initial_translations=dict(completed) or None, checkpoint_callback=checkpoint,
                    progress_callback=lambda message: d._progress(options, message, live_progress),
                ))
            elif engine_id == "local-transformer":
                result = d._heavy_call(options, f"本地快速翻译 {target_lang}", lambda: d.translate_segments_locally(
                    pending, options.source_lang, target_lang,
                    checkpoint_callback=checkpoint,
                    progress_callback=lambda message: d._progress(options, message, live_progress),
                ))
            else:
                result = d.translate_segments(pending, target_lang=target_lang, source_lang=options.source_lang,
                    **({"cancel_check": options.cancel_check} if options.cancel_check else {}))
            check_cancel()
            checkpoint(result)
            if set(completed) != valid_indexes:
                raise SubtitleToolError(f"{active_engine} returned incomplete translations")
            record(active_engine, "success")
            break
        # 取消是任务终止信号，不能被当成引擎失败而继续回退。
        # Cancellation terminates the job and must not trigger provider fallback.
        except CancellationError:
            raise
        except Exception as exc:
            check_cancel()
            last_error = exc
            record(active_engine, "failed", exc)
            if engine_id == "z-ai":
                run_state.zai_circuit_open = True
                run_state.zai_failure_reason = str(exc)
            if engine_id == "z-ai":
                d._progress(options, "已自动切换本地模型，保留已完成翻译", live_progress)
            elif engine_id == "local-nllb-quality" and translator == "z-ai":
                d._progress(options, "已自动切换 OpenAI，保留已完成翻译", live_progress)
            if engine_id != engines[-1]:
                d._progress(options, f"{active_engine} 翻译未完成，保留已完成字幕并尝试下一引擎: {exc}", live_progress)
    if set(completed) != valid_indexes:
        raise last_error or SubtitleToolError("No translation provider completed the subtitles")
    check_cancel()
    engine = " + ".join(producers) or active_engine
    # z.ai 策略全部使用本地快速模型时，保留已有的对外名称。
    # Retain the public legacy label for wholly local output in the z.ai strategy.
    if engine == "本地快速模型" and translator == "z-ai":
        engine = "本地模型"
    return _expand_deduplicated_translations(completed, indexes), engine
