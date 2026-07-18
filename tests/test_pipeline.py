from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from subtitle_tool.pipeline import (  # noqa: E402
    PipelineOptions,
    _load_source_segments,
    _resolve_input,
    render_edited_subtitle_video,
    run_pipeline,
)
from subtitle_tool.asset_cache import AssetCache  # noqa: E402
from subtitle_tool.youtube import DownloadedVideo  # noqa: E402
from subtitle_tool.errors import MediaError, SubtitleToolError  # noqa: E402
from subtitle_tool.media import EncodingProgress  # noqa: E402
from subtitle_tool.srt import SubtitleSegment, read_srt  # noqa: E402
from subtitle_tool.translation_cache import TranslationCacheEntry  # noqa: E402
from subtitle_tool.video_subtitle_detection import SubtitleRegionDetection  # noqa: E402


class PipelineTests(unittest.TestCase):
    def test_explicit_screen_ocr_uses_available_engine(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video = root / "video.mp4"
            video.write_bytes(b"video")
            expected = [SubtitleSegment(1, 0, 1_000, "画面字幕")]
            engine = unittest.mock.Mock(
                engine_id="macos-vision",
                recognize_video=unittest.mock.Mock(return_value=expected),
            )
            options = PipelineOptions(
                input_value=str(video),
                target_langs=[],
                source_lang="ja",
                out_dir=root / "output",
                source="screen-ocr",
                output_format="srt",
            )

            with patch(
                "subtitle_tool.pipeline.get_screen_ocr_engine", return_value=engine
            ), patch("subtitle_tool.pipeline.find_subtitle_streams") as find_streams:
                segments, source_kind = _load_source_segments(
                    options, video, AssetCache(root / "cache")
                )

        self.assertEqual(segments, expected)
        self.assertEqual(source_kind, "screen-ocr-macos-vision")
        engine.recognize_video.assert_called_once()
        find_streams.assert_not_called()

    def test_auto_falls_back_to_screen_ocr_for_repeated_whisper_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video = root / "video.mp4"
            video.write_bytes(b"video")
            repeated = [
                SubtitleSegment(index, index * 1_000, index * 1_000 + 900, "请上汤。")
                for index in range(1, 30)
            ]
            expected = [SubtitleSegment(1, 0, 1_000, "ただでさえ暑いのに")]
            engine = unittest.mock.Mock(
                engine_id="macos-vision",
                recognize_video=unittest.mock.Mock(return_value=expected),
            )
            options = PipelineOptions(
                input_value=str(video),
                target_langs=[],
                source_lang="ja",
                out_dir=root / "output",
                source="auto",
                output_format="srt",
                transcriber="local-whisper",
                whisper_model=root / "model.bin",
            )

            def fake_extract(_video, audio, _cancel=None):
                audio.parent.mkdir(parents=True, exist_ok=True)
                audio.write_bytes(b"audio")

            with patch(
                "subtitle_tool.pipeline.find_subtitle_streams", return_value=[]
            ), patch("subtitle_tool.pipeline.extract_audio", side_effect=fake_extract), patch(
                "subtitle_tool.pipeline.transcribe_with_whisper_cpp",
                return_value=repeated,
            ), patch(
                "subtitle_tool.pipeline.get_screen_ocr_engine", return_value=engine
            ):
                segments, source_kind = _load_source_segments(
                    options, video, AssetCache(root / "cache")
                )

        self.assertEqual(segments, expected)
        self.assertEqual(source_kind, "screen-ocr-macos-vision")

    def test_auto_rejects_repeated_cached_transcript_and_uses_ocr(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video = root / "video.mp4"
            video.write_bytes(b"video")
            cache = AssetCache(root / "cache")
            fingerprint = cache.file_fingerprint(video)
            audio_path = cache.audio_path(fingerprint)
            audio_path.parent.mkdir(parents=True, exist_ok=True)
            audio_path.write_bytes(b"audio")
            transcript_path = cache.transcript_path(
                fingerprint, "local-whisper", "ja", root / "model.bin", "standard"
            )
            transcript_path.parent.mkdir(parents=True, exist_ok=True)
            repeated = [
                SubtitleSegment(index, index * 1_000, index * 1_000 + 900, "請上湯。")
                for index in range(1, 20)
            ]
            from subtitle_tool.srt import write_srt

            write_srt(transcript_path, repeated)
            expected = [SubtitleSegment(1, 0, 1_000, "料理で発散")]
            engine = unittest.mock.Mock(
                engine_id="macos-vision",
                recognize_video=unittest.mock.Mock(return_value=expected),
            )
            options = PipelineOptions(
                input_value=str(video),
                target_langs=[],
                source_lang="ja",
                out_dir=root / "output",
                source="auto",
                output_format="srt",
                transcriber="local-whisper",
                whisper_model=root / "model.bin",
                whisper_use_vad=False,
            )

            with patch(
                "subtitle_tool.pipeline.find_subtitle_streams", return_value=[]
            ), patch(
                "subtitle_tool.pipeline.transcribe_with_whisper_cpp"
            ) as transcribe, patch(
                "subtitle_tool.pipeline.get_screen_ocr_engine", return_value=engine
            ):
                segments, source_kind = _load_source_segments(options, video, cache)

        self.assertEqual(segments, expected)
        self.assertEqual(source_kind, "screen-ocr-macos-vision")
        transcribe.assert_not_called()

    def test_explicit_screen_ocr_reports_unavailable_engine(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video = root / "video.mp4"
            video.write_bytes(b"video")
            options = PipelineOptions(
                input_value=str(video),
                target_langs=[],
                source_lang=None,
                out_dir=root / "output",
                source="screen-ocr",
                output_format="srt",
            )

            with patch(
                "subtitle_tool.pipeline.get_screen_ocr_engine", return_value=None
            ):
                with self.assertRaisesRegex(MediaError, "OCR.*不可用"):
                    _load_source_segments(options, video, AssetCache(root / "cache"))

    def test_unknown_https_url_uses_generic_downloader(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cached_video = root / "cache" / "videos" / "clip-42.mp4"
            cached_video.parent.mkdir(parents=True)
            cached_video.write_bytes(b"video")
            task_dir = root / "output" / "task"
            options = PipelineOptions(
                input_value="https://media.example/videos/42",
                target_langs=[],
                source_lang=None,
                out_dir=root / "output",
                source="auto",
                output_format="srt",
                download_only=True,
                progress_callback=lambda message, percent: progress_messages.append(
                    (message, percent)
                ),
            )
            progress_messages = []

            with patch(
                "subtitle_tool.pipeline.download_generic_video",
                return_value=DownloadedVideo("clip-42", cached_video),
            ) as download_generic:
                input_path, downloaded_path = _resolve_input(
                    options,
                    task_dir,
                    "202607121200001",
                    AssetCache(root / "cache"),
                )

        download_generic.assert_called_once()
        download_callback = download_generic.call_args.kwargs["progress_callback"]
        download_callback("通用网址下载仍在进行，已用时 01:00")
        self.assertEqual(input_path.name, "clip-42.202607121200001.mp4")
        self.assertEqual(downloaded_path, input_path)
        self.assertTrue(any("下载仍在进行" in message for message, _ in progress_messages))

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
        self.assertEqual(
            translate_segments_with_nllb.call_args.kwargs["model_name"],
            "facebook/nllb-200-distilled-1.3B",
        )
        self.assertIn("vi", result.translated_paths)

    def test_local_nllb_quality_routes_to_1_3b_with_progress_logs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "input.mp4"
            input_path.write_bytes(b"video")
            progress_messages = []

            with patch(
                "subtitle_tool.pipeline._load_source_segments",
                return_value=(
                    [SubtitleSegment(index=1, start_ms=0, end_ms=1000, text="こんにちは")],
                    "audio-local-whisper",
                ),
            ), patch(
                "subtitle_tool.pipeline.translate_segments_with_nllb",
                return_value={1: "你好"},
            ) as translate_segments_with_nllb:
                result = run_pipeline(
                    PipelineOptions(
                        input_value=str(input_path),
                        target_langs=["zh-CN"],
                        source_lang="ja",
                        out_dir=Path(tmpdir),
                        source="audio",
                        output_format="srt",
                        translator="local-nllb-quality",
                        progress_callback=lambda message, percent: progress_messages.append(message),
                    )
                )

        self.assertIn("zh-CN", result.translated_paths)
        self.assertEqual(
            translate_segments_with_nllb.call_args.kwargs["model_name"],
            "facebook/nllb-200-distilled-1.3B",
        )
        self.assertIsNotNone(
            translate_segments_with_nllb.call_args.kwargs["progress_callback"]
        )

    def test_local_nllb_resumes_partial_cache_and_uses_shared_provider(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "input.mp4"
            input_path.write_bytes(b"video")
            source_segments = [
                SubtitleSegment(index=1, start_ms=0, end_ms=1000, text="こんにちは"),
                SubtitleSegment(index=2, start_ms=1000, end_ms=2000, text="世界"),
            ]
            partial = TranslationCacheEntry(
                translations={1: "Hello"}, engine="本地 NLLB 1.3B", complete=False
            )

            with patch(
                "subtitle_tool.pipeline._load_source_segments",
                return_value=(source_segments, "audio-local-whisper"),
            ), patch(
                "subtitle_tool.pipeline.TranslationCache"
            ) as cache_class, patch(
                "subtitle_tool.pipeline.translate_segments_with_nllb",
                return_value={1: "Hello", 2: "World"},
            ) as nllb_translate:
                cache = cache_class.return_value
                cache.load.return_value = None
                cache.load_partial.return_value = partial
                run_pipeline(
                    PipelineOptions(
                        input_value=str(input_path),
                        target_langs=["en"],
                        source_lang="ja",
                        out_dir=Path(tmpdir),
                        source="audio",
                        output_format="srt",
                        translator="local-nllb",
                    )
                )

        self.assertEqual(cache.load_partial.call_args.args[-1], "local-nllb-quality")
        self.assertEqual(
            nllb_translate.call_args.kwargs["initial_translations"], {1: "Hello"}
        )
        self.assertTrue(callable(nllb_translate.call_args.kwargs["checkpoint_callback"]))

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

    def test_zai_failure_opens_circuit_for_remaining_target_languages(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "input.mp4"
            input_path.write_bytes(b"video")
            source_segments = [
                SubtitleSegment(index=1, start_ms=0, end_ms=1000, text="hello"),
            ]
            progress_messages = []

            def fake_local(segments, source_lang, target_lang):
                return {segment.index: f"{target_lang}: {segment.text}" for segment in segments}

            with patch(
                "subtitle_tool.pipeline._load_source_segments",
                return_value=(source_segments, "audio-local-whisper"),
            ), patch(
                "subtitle_tool.pipeline.translate_segments_with_zai",
                side_effect=SubtitleToolError("Request timed out"),
            ) as zai_translate, patch(
                "subtitle_tool.pipeline.translate_segments_locally",
                side_effect=fake_local,
            ):
                result = run_pipeline(
                    PipelineOptions(
                        input_value=str(input_path),
                        target_langs=["ja", "de"],
                        source_lang="en",
                        out_dir=Path(tmpdir),
                        source="audio",
                        output_format="srt",
                        translator="z-ai",
                        progress_callback=lambda message, percent: progress_messages.append(
                            message
                        ),
                    )
                )

        zai_translate.assert_called_once()
        self.assertEqual(set(result.translated_paths), {"ja", "de"})
        self.assertTrue(any("熔断" in message for message in progress_messages))

    def test_nllb_checkpoint_updates_real_translation_progress(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "input.mp4"
            input_path.write_bytes(b"video")
            source_segments = [
                SubtitleSegment(
                    index=index,
                    start_ms=(index - 1) * 1000,
                    end_ms=index * 1000,
                    text=f"text {index}",
                )
                for index in range(1, 5)
            ]
            progress_updates = []

            def fake_nllb(segments, source_lang, target_lang, **kwargs):
                kwargs["checkpoint_callback"]({1: "one", 2: "two"})
                return {
                    segment.index: f"translated {segment.index}"
                    for segment in segments
                }

            with patch(
                "subtitle_tool.pipeline._load_source_segments",
                return_value=(source_segments, "audio-local-whisper"),
            ), patch(
                "subtitle_tool.pipeline.translate_segments_with_nllb",
                side_effect=fake_nllb,
            ):
                run_pipeline(
                    PipelineOptions(
                        input_value=str(input_path),
                        target_langs=["ja"],
                        source_lang="en",
                        out_dir=Path(tmpdir),
                        source="audio",
                        output_format="srt",
                        translator="local-nllb-quality",
                        progress_callback=lambda message, percent: progress_updates.append(
                            (message, percent)
                        ),
                    )
                )

        matching = [
            (message, percent)
            for message, percent in progress_updates
            if "翻译进度: ja · 2/4" in message
        ]
        self.assertEqual(len(matching), 1)
        self.assertGreater(matching[0][1], 56)
        self.assertLess(matching[0][1], 76)

    def test_duplicate_subtitles_are_translated_once_and_expanded_to_timeline(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "input.mp4"
            input_path.write_bytes(b"video")
            source_segments = [
                SubtitleSegment(index=1, start_ms=0, end_ms=1000, text="Hello"),
                SubtitleSegment(index=2, start_ms=1000, end_ms=2000, text="Hello"),
                SubtitleSegment(index=3, start_ms=2000, end_ms=3000, text="World"),
            ]
            progress_messages = []

            def fake_translate(segments, target_lang, source_lang=None):
                return {
                    segment.index: {"Hello": "こんにちは", "World": "世界"}[
                        segment.text
                    ]
                    for segment in segments
                }

            with patch(
                "subtitle_tool.pipeline._load_source_segments",
                return_value=(source_segments, "audio-local-whisper"),
            ), patch(
                "subtitle_tool.pipeline.translate_segments",
                side_effect=fake_translate,
            ) as translate:
                result = run_pipeline(
                    PipelineOptions(
                        input_value=str(input_path),
                        target_langs=["ja"],
                        source_lang="en",
                        out_dir=Path(tmpdir),
                        source="audio",
                        output_format="srt",
                        translator="openai",
                        progress_callback=lambda message, percent: progress_messages.append(
                            message
                        ),
                    )
                )

            translated = read_srt(result.translated_paths["ja"])

        requested_segments = translate.call_args.args[0]
        self.assertEqual([segment.index for segment in requested_segments], [1, 3])
        self.assertEqual(
            [segment.text for segment in translated],
            ["こんにちは", "こんにちは", "世界"],
        )
        self.assertTrue(any("复用 1 条" in message for message in progress_messages))

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
            ) as nllb_translate, patch(
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

        self.assertEqual(
            nllb_translate.call_args.kwargs["model_name"],
            "facebook/nllb-200-distilled-1.3B",
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
            progress_messages = []

            def fake_burn(video, ass, output, cancel_check=None, **kwargs):
                kwargs["status_callback"]("使用 Apple VideoToolbox 硬件编码")
                kwargs["progress_callback"](
                    EncodingProgress(5.0, 10.0, 50, 2.0, 2.5)
                )
                return output

            with patch(
                "subtitle_tool.pipeline._load_source_segments",
                return_value=(source_segments, "audio-local-whisper"),
            ), patch(
                "subtitle_tool.pipeline.translate_segments",
                return_value={1: "Hello"},
            ), patch(
                "subtitle_tool.pipeline.write_ass"
            ) as write_ass, patch(
                "subtitle_tool.pipeline.burn_subtitle_track", side_effect=fake_burn
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
                        subtitle_encoding_profile="auto",
                        progress_callback=lambda message, percent: progress_messages.append(
                            (message, percent)
                        ),
                    )
                )

        write_ass.assert_called_once()
        self.assertEqual(write_ass.call_args.args[2], "above-bottom")
        burn.assert_called_once()
        self.assertEqual(burn.call_args.kwargs["encoding_profile"], "auto")
        self.assertTrue(any("50%" in message for message, _ in progress_messages))
        self.assertTrue(any("预计剩余" in message for message, _ in progress_messages))
        self.assertTrue(any(percent > 93 for _, percent in progress_messages))
        mux.assert_not_called()
        self.assertRegex(result.subtitled_video_paths["en"].name, r"\.en\.fixed-sub\.mp4$")

    def test_avoid_overlap_promotes_soft_video_to_stable_hard_subtitles(self):
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
                return_value={1: "Hello"},
            ), patch(
                "subtitle_tool.pipeline.write_ass"
            ), patch(
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
                        subtitle_video_mode="soft",
                        subtitle_position="auto",
                        progress_callback=lambda message, percent: progress_messages.append(message),
                    )
                )

        burn.assert_called_once()
        mux.assert_not_called()
        self.assertTrue(any("自动切换稳定硬字幕" in item for item in progress_messages))
        self.assertTrue(
            any(
                "实际字幕模式: 稳定硬字幕 · 原底部字幕上方" in item
                for item in progress_messages
            )
        )
        self.assertTrue(result.subtitled_video_paths["en"].name.endswith(".fixed-sub.mp4"))

    def test_auto_position_uses_video_detection_and_avoids_top_subtitles(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "input.mp4"
            input_path.write_bytes(b"video")
            source_segments = [SubtitleSegment(1, 0, 1000, "hello")]
            detection = SubtitleRegionDetection("top", 0.91, 8, 0.2, 0.01)

            with patch(
                "subtitle_tool.pipeline._load_source_segments",
                return_value=(source_segments, "audio-local-whisper"),
            ), patch(
                "subtitle_tool.pipeline.translate_segments", return_value={1: "Hello"}
            ), patch(
                "subtitle_tool.pipeline.detect_video_subtitle_region",
                return_value=detection,
            ) as detect, patch(
                "subtitle_tool.pipeline.write_ass"
            ) as write_ass, patch(
                "subtitle_tool.pipeline.burn_subtitle_track"
            ):
                run_pipeline(
                    PipelineOptions(
                        input_value=str(input_path),
                        target_langs=["en"],
                        source_lang="ja",
                        out_dir=Path(tmpdir) / "output",
                        source="audio",
                        output_format="srt",
                        translator="openai",
                        embed_subtitles=True,
                        avoid_subtitle_overlap=True,
                        subtitle_video_mode="hard",
                        subtitle_position="auto",
                    )
                )

        detect.assert_called_once()
        self.assertNotIn(str(Path(tmpdir) / "output"), str(detect.call_args.args[1]))
        self.assertEqual(write_ass.call_args.args[2], "bottom")

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
                    whisper_use_gpu=False,
                    whisper_use_vad=False,
                    whisper_vad_model=Path(tmpdir) / "vad.bin",
                )
                first = run_pipeline(options)
                second = run_pipeline(options)
                first_text = first.source_subtitle_path.read_text(encoding="utf-8")
                second_text = second.source_subtitle_path.read_text(encoding="utf-8")

        extract_audio.assert_called_once()
        transcribe.assert_called_once()
        self.assertFalse(transcribe.call_args.kwargs["use_gpu"])
        self.assertFalse(transcribe.call_args.kwargs["use_vad"])
        self.assertEqual(transcribe.call_args.kwargs["vad_model_path"].name, "vad.bin")
        self.assertEqual(first_text, second_text)

    def test_render_edited_hard_subtitle_video_uses_saved_srt(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            video = root / "video.mp4"
            subtitle = root / "subtitle.en.srt"
            output = root / "subtitle.en.edited.fixed-sub.mp4"
            video.write_bytes(b"video")
            subtitle.write_text(
                "1\n00:00:00,000 --> 00:00:01,000\nEdited\n", encoding="utf-8"
            )
            with patch("subtitle_tool.pipeline.write_ass") as write_ass, patch(
                "subtitle_tool.pipeline.burn_subtitle_track", return_value=output
            ) as burn:
                result = render_edited_subtitle_video(
                    video, subtitle, output, "hard", "above-bottom"
                )

        write_ass.assert_called_once()
        burn.assert_called_once()
        self.assertEqual(result, output)


if __name__ == "__main__":
    unittest.main()
