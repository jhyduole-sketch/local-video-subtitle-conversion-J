from pathlib import Path
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from subtitle_tool.asset_cache import AssetCache
from subtitle_tool.translation_cache import TranslationCache
from subtitle_tool.srt import SubtitleSegment
from subtitle_tool.web import options_from_payload


class CacheIdentityTests(unittest.TestCase):
    def test_model_and_endpoint_change_translation_key(self):
        cache = TranslationCache(Path('/tmp/identity-test'))
        segments = [SubtitleSegment(1, 0, 1000, 'hello')]
        for provider, key in [('openai', 'SUBTITLE_TOOL_TRANSLATE_MODEL'),
                              ('openai', 'OPENAI_BASE_URL'), ('z-ai', 'ZAI_MODEL'),
                              ('z-ai', 'ZAI_API_BASE')]:
            with self.subTest(key=key), patch.dict(os.environ, {key: 'first'}):
                before = cache._path(segments, 'en', 'ja', provider)
                with patch.dict(os.environ, {key: 'second'}):
                    self.assertNotEqual(before, cache._path(segments, 'en', 'ja', provider))

    def test_local_model_replacement_changes_transcript_key(self):
        with tempfile.TemporaryDirectory() as directory:
            model = Path(directory) / 'model.bin'
            model.write_bytes(b'first')
            cache = AssetCache(Path(directory) / 'cache')
            before = cache.transcript_path('video', 'local-whisper', 'en', model)
            model.write_bytes(b'second')
            self.assertNotEqual(before, cache.transcript_path('video', 'local-whisper', 'en', model))

    def test_cloud_transcription_model_changes_key(self):
        cache = AssetCache(Path('/tmp/identity-test'))
        with patch.dict(os.environ, {'SUBTITLE_TOOL_TRANSCRIBE_MODEL': 'first'}):
            before = cache.transcript_path('video', 'openai', 'en', None)
        with patch.dict(os.environ, {'SUBTITLE_TOOL_TRANSCRIBE_MODEL': 'second'}):
            self.assertNotEqual(before, cache.transcript_path('video', 'openai', 'en', None))

    def test_existing_positional_download_flag_keeps_its_meaning(self):
        from subtitle_tool.pipeline import PipelineOptions
        options = PipelineOptions('video.mp4', [], None, Path('output'), 'auto', 'srt', True)
        self.assertTrue(options.force_download)
        self.assertFalse(options.force_regenerate)

    def test_web_force_regeneration_is_explicit_and_defaults_off(self):
        self.assertFalse(options_from_payload({'input': 'video.mp4'}).force_regenerate)
        self.assertTrue(options_from_payload({'input': 'video.mp4', 'forceRegenerate': True}).force_regenerate)


class ForceRegenerationTests(unittest.TestCase):
    def test_force_regeneration_bypasses_a_complete_translation_cache(self):
        from subtitle_tool.pipeline import PipelineOptions, run_pipeline
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = root / 'video.mp4'
            video.write_bytes(b'video')
            source = [SubtitleSegment(1, 0, 1000, 'hello')]
            options = dict(input_value=str(video), target_langs=['ja'], source_lang='en',
                           out_dir=root / 'output', source='embedded', output_format='srt')
            with patch('subtitle_tool.pipeline._load_source_segments', return_value=(source, 'embedded')), \
                 patch('subtitle_tool.pipeline._translate_target', return_value=({1: 'first'}, 'test')) as translate:
                run_pipeline(PipelineOptions(**options))
                run_pipeline(PipelineOptions(**options))
                self.assertEqual(translate.call_count, 1)
                translate.return_value = ({1: 'second'}, 'test')
                result = run_pipeline(PipelineOptions(**options, force_regenerate=True))
                self.assertEqual(translate.call_count, 2)
                self.assertIn('second', result.translated_paths['ja'].read_text())

    def test_force_regeneration_bypasses_transcription_cache(self):
        from subtitle_tool.pipeline import PipelineOptions, _load_source_segments
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = root / 'video.mp4'
            video.write_bytes(b'video')
            cache = AssetCache(root / 'cache')
            options = dict(input_value=str(video), target_langs=[], source_lang='en', out_dir=root,
                           source='audio', output_format='srt', transcriber='openai')
            def extract(source, target, *args):
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b'audio')
            with patch('subtitle_tool.pipeline.extract_audio', side_effect=extract), \
                 patch('subtitle_tool.pipeline.transcribe_audio', return_value=[SubtitleSegment(1, 0, 1000, 'first')]) as transcribe:
                _load_source_segments(PipelineOptions(**options), video, cache)
                _load_source_segments(PipelineOptions(**options), video, cache)
                self.assertEqual(transcribe.call_count, 1)
                _load_source_segments(PipelineOptions(**options, force_regenerate=True), video, cache)
                self.assertEqual(transcribe.call_count, 2)
