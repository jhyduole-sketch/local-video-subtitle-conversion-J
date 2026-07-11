from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from subtitle_tool.pipeline import PipelineOptions, run_pipeline  # noqa: E402
from subtitle_tool.errors import SubtitleToolError  # noqa: E402
from subtitle_tool.srt import SubtitleSegment, read_srt  # noqa: E402


class PipelineTests(unittest.TestCase):
    def test_generated_files_include_timestamp_suffix(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "input.mp4"
            input_path.write_bytes(b"video")

            with patch(
                "subtitle_tool.pipeline._load_source_segments",
                return_value=(
                    [SubtitleSegment(index=1, start_ms=0, end_ms=1000, text="hello")],
                    "audio-local-whisper",
                ),
            ), patch(
                "subtitle_tool.pipeline.translate_segments",
                return_value={1: "こんにちは"},
            ):
                result = run_pipeline(
                    PipelineOptions(
                        input_value=str(input_path),
                        target_langs=["ja"],
                        source_lang="en",
                        out_dir=Path(tmpdir),
                        source="audio",
                        output_format="srt",
                        translator="openai",
                    )
                )

        self.assertRegex(result.source_subtitle_path.name, r"input\.\d{15}\.source\.en\.srt")
        self.assertRegex(result.translated_paths["ja"].name, r"input\.\d{15}\.ja\.srt")
        self.assertRegex(result.source_subtitle_path.parent.name, r"input\.\d{15}")
        self.assertEqual(result.source_subtitle_path.parent, result.translated_paths["ja"].parent)

    def test_local_nllb_translator_is_routed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "input.mp4"
            input_path.write_bytes(b"video")

            with patch(
                "subtitle_tool.pipeline._load_source_segments",
                return_value=(
                    [SubtitleSegment(index=1, start_ms=0, end_ms=1000, text="你好")],
                    "audio-local-whisper",
                ),
            ), patch(
                "subtitle_tool.pipeline.translate_segments_with_nllb",
                return_value={1: "Xin chao"},
            ) as translate_segments_with_nllb:
                result = run_pipeline(
                    PipelineOptions(
                        input_value=str(input_path),
                        target_langs=["vi"],
                        source_lang="zh",
                        out_dir=Path(tmpdir),
                        source="audio",
                        output_format="srt",
                        translator="local-nllb",
                    )
                )

        translate_segments_with_nllb.assert_called_once()
        self.assertIn("vi", result.translated_paths)

    def test_same_source_and_target_language_reuses_source_subtitles(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "input.mp4"
            input_path.write_bytes(b"video")
            source_segments = [
                SubtitleSegment(index=1, start_ms=0, end_ms=1000, text="こんにちは"),
            ]

            with patch(
                "subtitle_tool.pipeline._load_source_segments",
                return_value=(source_segments, "audio-local-whisper"),
            ), patch(
                "subtitle_tool.pipeline.translate_segments_locally",
                side_effect=AssertionError("translation should not be called"),
            ):
                result = run_pipeline(
                    PipelineOptions(
                        input_value=str(input_path),
                        target_langs=["ja"],
                        source_lang="ja",
                        out_dir=Path(tmpdir),
                        source="audio",
                        output_format="srt",
                        translator="local-transformer",
                    )
                )

            output_text = result.translated_paths["ja"].read_text(encoding="utf-8")
        self.assertIn("こんにちは", output_text)
        self.assertEqual(result.failed_languages, {})

    def test_chinese_source_and_target_variants_reuse_source_subtitles(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "input.mp4"
            input_path.write_bytes(b"video")
            source_segments = [
                SubtitleSegment(index=1, start_ms=0, end_ms=1000, text="你好"),
            ]

            with patch(
                "subtitle_tool.pipeline._load_source_segments",
                return_value=(source_segments, "audio-local-whisper"),
            ), patch(
                "subtitle_tool.pipeline.translate_segments",
                side_effect=AssertionError("translation should not be called"),
            ):
                result = run_pipeline(
                    PipelineOptions(
                        input_value=str(input_path),
                        target_langs=["zh-CN"],
                        source_lang="zh",
                        out_dir=Path(tmpdir),
                        source="audio",
                        output_format="srt",
                        translator="openai",
                    )
                )

            output_text = result.translated_paths["zh-CN"].read_text(encoding="utf-8")
        self.assertIn("你好", output_text)
        self.assertEqual(result.failed_languages, {})

    def test_zai_rate_limit_falls_back_to_local_and_records_engine(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "input.mp4"
            input_path.write_bytes(b"video")
            source_segments = [
                SubtitleSegment(index=1, start_ms=0, end_ms=1000, text="hello"),
            ]
            progress_messages = []

            with patch(
                "subtitle_tool.pipeline._load_source_segments",
                return_value=(source_segments, "audio-local-whisper"),
            ), patch(
                "subtitle_tool.pipeline.translate_segments_with_zai",
                side_effect=SubtitleToolError("z.ai 429 / 1302 速率限制"),
            ), patch(
                "subtitle_tool.pipeline.translate_segments_locally",
                return_value={1: "こんにちは"},
            ) as local_translate, patch(
                "subtitle_tool.pipeline.translate_segments"
            ) as openai_translate:
                result = run_pipeline(
                    PipelineOptions(
                        input_value=str(input_path),
                        target_langs=["ja"],
                        source_lang="en",
                        out_dir=Path(tmpdir),
                        source="audio",
                        output_format="srt",
                        translator="z-ai",
                        progress_callback=lambda message, percent: progress_messages.append(message),
                    )
                )

        local_translate.assert_called_once()
        openai_translate.assert_not_called()
        self.assertEqual(result.translation_engines["ja"], "本地模型")
        self.assertTrue(any("已自动切换本地模型" in item for item in progress_messages))

    def test_bad_local_fallback_continues_to_openai(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "input.mp4"
            input_path.write_bytes(b"video")
            source_segments = [
                SubtitleSegment(index=1, start_ms=0, end_ms=1000, text="hello"),
            ]
            progress_messages = []

            with patch(
                "subtitle_tool.pipeline._load_source_segments",
                return_value=(source_segments, "audio-local-whisper"),
            ), patch(
                "subtitle_tool.pipeline.translate_segments_with_zai",
                side_effect=SubtitleToolError("z.ai 429 / 1302 速率限制"),
            ), patch(
                "subtitle_tool.pipeline.translate_segments_locally",
                side_effect=SubtitleToolError("Local translation output looks repetitive"),
            ), patch(
                "subtitle_tool.pipeline.translate_segments_with_nllb",
                side_effect=SubtitleToolError("NLLB output contains invalid characters"),
            ), patch(
                "subtitle_tool.pipeline.translate_segments",
                return_value={1: "Hello"},
            ) as openai_translate:
                result = run_pipeline(
                    PipelineOptions(
                        input_value=str(input_path),
                        target_langs=["en"],
                        source_lang="ja",
                        out_dir=Path(tmpdir),
                        source="audio",
                        output_format="srt",
                        translator="z-ai",
                        progress_callback=lambda message, percent: progress_messages.append(message),
                    )
                )

        openai_translate.assert_called_once()
        self.assertEqual(result.translation_engines["en"], "OpenAI")
        self.assertTrue(any("已自动切换 OpenAI" in item for item in progress_messages))

    def test_second_identical_translation_uses_persistent_cache(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "input.mp4"
            input_path.write_bytes(b"video")
            source_segments = [
                SubtitleSegment(index=1, start_ms=0, end_ms=1000, text="hello"),
            ]
            progress_messages = []

            with patch(
                "subtitle_tool.pipeline._load_source_segments",
                return_value=(source_segments, "audio-local-whisper"),
            ), patch(
                "subtitle_tool.pipeline.translate_segments",
                return_value={1: "こんにちは"},
            ) as translate:
                options = PipelineOptions(
                    input_value=str(input_path),
                    target_langs=["ja"],
                    source_lang="en",
                    out_dir=Path(tmpdir),
                    source="audio",
                    output_format="srt",
                    translator="openai",
                    progress_callback=lambda message, percent: progress_messages.append(message),
                )
                run_pipeline(options)
                cached_result = run_pipeline(options)

        translate.assert_called_once()
        self.assertEqual(cached_result.translation_engines["ja"], "OpenAI（缓存）")
        self.assertTrue(any("使用翻译缓存" in item for item in progress_messages))

    def test_soft_subtitle_mux_overlaps_next_language_translation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "input.mp4"
            input_path.write_bytes(b"video")
            source_segments = [
                SubtitleSegment(index=1, start_ms=0, end_ms=1000, text="hello"),
            ]
            second_translation_started = threading.Event()
            mux_observed_overlap = []
            translation_calls = 0

            def fake_translate(segments, target_lang, source_lang=None):
                nonlocal translation_calls
                translation_calls += 1
                if translation_calls == 2:
                    second_translation_started.set()
                return {1: f"translated {target_lang}"}

            def fake_mux(*args, **kwargs):
                if not mux_observed_overlap:
                    mux_observed_overlap.append(
                        second_translation_started.wait(timeout=0.5)
                    )

            with patch(
                "subtitle_tool.pipeline._load_source_segments",
                return_value=(source_segments, "audio-local-whisper"),
            ), patch(
                "subtitle_tool.pipeline.translate_segments",
                side_effect=fake_translate,
            ), patch(
                "subtitle_tool.pipeline.mux_subtitle_track",
                side_effect=fake_mux,
            ) as mux:
                result = run_pipeline(
                    PipelineOptions(
                        input_value=str(input_path),
                        target_langs=["ja", "fr"],
                        source_lang="en",
                        out_dir=Path(tmpdir),
                        source="audio",
                        output_format="srt",
                        translator="openai",
                        embed_subtitles=True,
                    )
                )

        self.assertEqual(mux.call_count, 2)
        self.assertEqual(mux_observed_overlap, [True])
        self.assertEqual(set(result.subtitled_video_paths), {"ja", "fr"})

    def test_translated_srt_is_wrapped_and_timing_overlap_is_repaired(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "input.mp4"
            input_path.write_bytes(b"video")
            source_segments = [
                SubtitleSegment(index=1, start_ms=0, end_ms=3000, text="first"),
                SubtitleSegment(index=2, start_ms=2500, end_ms=5000, text="second"),
            ]
            translations = {
                1: "This translated subtitle is deliberately long enough to wrap across lines",
                2: "Another translated subtitle",
            }

            with patch(
                "subtitle_tool.pipeline._load_source_segments",
                return_value=(source_segments, "audio-local-whisper"),
            ), patch(
                "subtitle_tool.pipeline.translate_segments",
                return_value=translations,
            ):
                result = run_pipeline(
                    PipelineOptions(
                        input_value=str(input_path),
                        target_langs=["en"],
                        source_lang="ja",
                        out_dir=Path(tmpdir),
                        source="audio",
                        output_format="srt",
                        translator="openai",
                    )
                )
                rendered = read_srt(result.translated_paths["en"])

        self.assertTrue(all(len(segment.text.splitlines()) <= 2 for segment in rendered))
        self.assertTrue(
            all(
                previous.end_ms + 40 <= current.start_ms
                for previous, current in zip(rendered, rendered[1:])
            )
        )

    def test_hard_subtitle_mode_writes_ass_and_burns_video(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "input.mp4"
            input_path.write_bytes(b"video")
            source_segments = [
                SubtitleSegment(index=1, start_ms=0, end_ms=1000, text="hello"),
            ]

            with patch(
                "subtitle_tool.pipeline._load_source_segments",
                return_value=(source_segments, "audio-local-whisper"),
            ), patch(
                "subtitle_tool.pipeline.translate_segments",
                return_value={1: "Hello"},
            ), patch(
                "subtitle_tool.pipeline.write_ass"
            ) as write_ass, patch(
                "subtitle_tool.pipeline.burn_subtitle_track"
            ) as burn, patch(
                "subtitle_tool.pipeline.mux_subtitle_track"
            ) as mux:
                result = run_pipeline(
                    PipelineOptions(
                        input_value=str(input_path),
                        target_langs=["en"],
                        source_lang="ja",
                        out_dir=Path(tmpdir),
                        source="audio",
                        output_format="srt",
                        translator="openai",
                        embed_subtitles=True,
                        avoid_subtitle_overlap=True,
                        subtitle_video_mode="hard",
                        subtitle_position="auto",
                    )
                )

        write_ass.assert_called_once()
        self.assertEqual(write_ass.call_args.args[2], "above-bottom")
        burn.assert_called_once()
        mux.assert_not_called()
        self.assertRegex(result.subtitled_video_paths["en"].name, r"\.en\.fixed-sub\.mp4$")

    def test_second_audio_run_reuses_extracted_audio_and_transcript(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "input.mp4"
            input_path.write_bytes(b"video content")
            source_segments = [
                SubtitleSegment(index=1, start_ms=0, end_ms=1000, text="hello"),
            ]

            def fake_extract(video_path, audio_path, cancel_check=None):
                audio_path.parent.mkdir(parents=True, exist_ok=True)
                audio_path.write_bytes(b"audio")
                return audio_path

            with patch(
                "subtitle_tool.pipeline.extract_audio", side_effect=fake_extract
            ) as extract_audio, patch(
                "subtitle_tool.pipeline.transcribe_with_whisper_cpp",
                return_value=source_segments,
            ) as transcribe:
                options = PipelineOptions(
                    input_value=str(input_path),
                    target_langs=[],
                    source_lang="en",
                    out_dir=Path(tmpdir) / "output",
                    source="audio",
                    output_format="srt",
                    transcriber="local-whisper",
                )
                first = run_pipeline(options)
                second = run_pipeline(options)
                first_text = first.source_subtitle_path.read_text(encoding="utf-8")
                second_text = second.source_subtitle_path.read_text(encoding="utf-8")

        extract_audio.assert_called_once()
        transcribe.assert_called_once()
        self.assertEqual(first_text, second_text)


if __name__ == "__main__":
    unittest.main()
