from pathlib import Path
from contextlib import nullcontext
from dataclasses import replace
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from subtitle_tool.errors import CancellationError, ProviderRateLimitError, ProcessTimeoutError
from subtitle_tool.pipeline import PipelineOptions, _translate_target, _TranslationRunState
from subtitle_tool.srt import SubtitleSegment
from subtitle_tool.translation_scheduler import classify_translation_failure


class BatchTokenizer:
    def __call__(self, texts, **kwargs):
        return {"input_ids": texts}

    def convert_tokens_to_ids(self, value):
        return 42

    def batch_decode(self, outputs, **kwargs):
        return outputs


class BatchTorch:
    def no_grad(self):
        return nullcontext()


class BatchModel:
    def __init__(self, operation):
        self.operation = operation
        self.calls = 0

    def eval(self):
        pass

    def generate(self, input_ids, **kwargs):
        self.calls += 1
        return self.operation(self.calls, input_ids)


class TranslationSchedulerTests(unittest.TestCase):
    def setUp(self):
        self.options = PipelineOptions("video", [], "en", Path("out"), "audio", "srt", translator="z-ai")
        self.segments = [SubtitleSegment(1, 0, 1000, "Hello"), SubtitleSegment(2, 1000, 2000, "Bye")]

    def test_local_engines_stop_before_next_batch_after_cancellation(self):
        for translator in ("local-transformer", "local-nllb-quality"):
            with self.subTest(translator=translator):
                cancelled = []
                def generate(call, texts):
                    cancelled.append(True)
                    return ["こんにちは"]
                model = BatchModel(generate)
                options = replace(self.options, translator=translator, cancel_check=lambda: bool(cancelled))
                with patch("subtitle_tool.local_translate._load_model", return_value=(BatchTokenizer(), model, BatchTorch())), patch("subtitle_tool.local_translate._local_translation_batch_size", return_value=1):
                    with self.assertRaises(CancellationError):
                        _translate_target(options, self.segments, "ja", 60)
                self.assertEqual(model.calls, 1)

    def test_fast_local_checkpoint_survives_later_batch_failure(self):
        checkpoints = []
        def generate(call, texts):
            if call == 2:
                raise RuntimeError("second batch failed")
            return ["こんにちは"]
        model = BatchModel(generate)
        def nllb(segments, *args, **kwargs):
            return {**(kwargs.get("initial_translations") or {}), 2: "さようなら"}
        with patch("subtitle_tool.pipeline.translate_segments_with_zai", side_effect=TimeoutError("offline")), patch("subtitle_tool.local_translate._load_model", return_value=(BatchTokenizer(), model, BatchTorch())), patch("subtitle_tool.local_translate._local_translation_batch_size", return_value=1), patch("subtitle_tool.pipeline.translate_segments_with_nllb", side_effect=nllb), patch("subtitle_tool.pipeline.translate_segments", return_value={1: "retranslated", 2: "retranslated"}):
            result, engine = _translate_target(self.options, self.segments, "ja", 60, checkpoint_callback=checkpoints.append)
        self.assertEqual(result, {1: "こんにちは", 2: "さようなら"})
        self.assertEqual(checkpoints[0], {1: "こんにちは"})
        self.assertEqual(engine, "本地快速模型 + 本地 NLLB 1.3B")

    def test_typed_failure_takes_precedence_over_error_message(self):
        self.assertEqual(classify_translation_failure(ProviderRateLimitError("z.ai", "timeout waiting for quota")), "rate-limit")
        self.assertEqual(classify_translation_failure(ProcessTimeoutError("execution expired")), "timeout")

    def test_circuit_skip_is_reported_with_success(self):
        attempts = []
        state = _TranslationRunState(zai_circuit_open=True, zai_failure_reason="429")
        with patch("subtitle_tool.pipeline.translate_segments_locally", return_value={1: "a", 2: "b"}):
            result, _ = _translate_target(self.options, self.segments, "ja", 60, run_state=state, attempt_callback=attempts.append)
        self.assertEqual(result, {1: "a", 2: "b"})
        self.assertEqual([a.outcome for a in attempts], ["skipped", "success"])

    def test_each_local_fallback_propagates_cancellation(self):
        for engine in ("translate_segments_locally", "translate_segments_with_nllb"):
            with self.subTest(engine=engine), patch("subtitle_tool.pipeline.translate_segments_with_zai", side_effect=TimeoutError("offline")), patch("subtitle_tool.pipeline.translate_segments_locally", side_effect=RuntimeError("unavailable")), patch("subtitle_tool.pipeline.translate_segments_with_nllb", side_effect=RuntimeError("unavailable")), patch("subtitle_tool.pipeline." + engine, side_effect=CancellationError("cancelled")), patch("subtitle_tool.pipeline.translate_segments", side_effect=AssertionError("called after cancellation")):
                with self.assertRaises(CancellationError):
                    _translate_target(self.options, self.segments, "ja", 60)

    def test_partial_results_survive_all_provider_failures(self):
        checkpoints = []
        state = _TranslationRunState()
        def zai(_, **kwargs):
            kwargs["checkpoint_callback"]({1: "first"})
            raise TimeoutError("offline")
        def nllb(_, *args, **kwargs):
            self.assertEqual(kwargs["initial_translations"], {1: "first"})
            raise RuntimeError("model missing")
        def openai(pending, **kwargs):
            self.assertEqual([s.index for s in pending], [2])
            return {2: "second"}
        with patch("subtitle_tool.pipeline.translate_segments_with_zai", side_effect=zai), patch("subtitle_tool.pipeline.translate_segments_locally", side_effect=RuntimeError("missing")), patch("subtitle_tool.pipeline.translate_segments_with_nllb", side_effect=nllb), patch("subtitle_tool.pipeline.translate_segments", side_effect=openai):
            result, engine = _translate_target(self.options, self.segments, "ja", 60, checkpoint_callback=checkpoints.append, run_state=state)
        self.assertEqual(result, {1: "first", 2: "second"})
        self.assertEqual(checkpoints[-1], result)
        self.assertEqual(engine, "z.ai + OpenAI")
        self.assertEqual(state.checkpoint_engine, "z.ai + OpenAI")

    def test_direct_failure_records_failed_attempt(self):
        from dataclasses import replace
        attempts = []
        with patch("subtitle_tool.pipeline.translate_segments", side_effect=TimeoutError("offline")):
            with self.assertRaises(TimeoutError):
                _translate_target(replace(self.options, translator="openai"), self.segments, "ja", 60, attempt_callback=attempts.append)
        self.assertEqual([(a.engine, a.outcome, a.category) for a in attempts], [("OpenAI", "failed", "timeout")])
