from pathlib import Path
import json
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from subtitle_tool.openai_client import (  # noqa: E402
    DEFAULT_API_TIMEOUT_SECONDS,
    DEFAULT_ZAI_REQUEST_DELAY_SECONDS,
    _api_timeout_seconds,
    _chunk_segments_by_budget,
    _float_env,
    _parse_translation_json,
    translate_segments_with_zai,
)
from subtitle_tool.srt import SubtitleSegment  # noqa: E402


class OpenAIClientTests(unittest.TestCase):
    def test_dynamic_zai_batches_respect_count_and_character_budgets(self):
        segments = [
            SubtitleSegment(index=index, start_ms=0, end_ms=1000, text="x" * 30)
            for index in range(1, 9)
        ]

        batches = _chunk_segments_by_budget(
            segments, max_segments=4, max_characters=90
        )

        self.assertEqual([len(batch) for batch in batches], [3, 3, 2])
        self.assertTrue(all(len(batch) <= 4 for batch in batches))
        self.assertTrue(
            all(sum(len(segment.text) for segment in batch) <= 90 for batch in batches)
        )

    def test_parse_translation_json_returns_indexed_text(self):
        segments = [
            SubtitleSegment(index=1, start_ms=0, end_ms=1000, text="你好"),
            SubtitleSegment(index=2, start_ms=1000, end_ms=2000, text="世界"),
        ]

        translations = _parse_translation_json(
            '{"items":[{"index":1,"text":"こんにちは"},{"index":2,"text":"世界"}]}',
            "ja",
            segments,
            "z.ai",
        )

        self.assertEqual(translations, {1: "こんにちは", 2: "世界"})

    def test_zai_translation_retries_missing_indexes(self):
        segments = [
            SubtitleSegment(index=index, start_ms=index * 1000, end_ms=(index + 1) * 1000, text=f"text {index}")
            for index in range(1, 31)
        ]
        call_count = 0

        def fake_chat_json_object(client, model, system_prompt, user_prompt):
            nonlocal call_count
            call_count += 1
            payload = json.loads(user_prompt)
            indexes = [item["index"] for item in payload["subtitles"]]
            if 25 in indexes and call_count <= 3:
                indexes = [index for index in indexes if index < 25]
            return json.dumps(
                {
                    "items": [
                        {"index": index, "text": f"ja {index}"}
                        for index in indexes
                    ]
                }
            )

        progress_messages = []

        with patch.dict("subtitle_tool.openai_client.os.environ", {"ZAI_REQUEST_DELAY_SECONDS": "0"}), patch(
            "subtitle_tool.openai_client.build_zai_client", return_value=object()
        ), patch("subtitle_tool.openai_client._chat_json_object", side_effect=fake_chat_json_object):
            translations = translate_segments_with_zai(
                segments, "ja", progress_callback=progress_messages.append
            )

        self.assertEqual(len(translations), 30)
        self.assertEqual(translations[25], "ja 25")
        self.assertGreater(call_count, 3)
        self.assertIn("z.ai 翻译 ja: 第 1/2 批", progress_messages)
        self.assertTrue(
            any(message.startswith("z.ai 补翻 ja:") for message in progress_messages)
        )

    def test_api_timeout_uses_default_for_invalid_env_value(self):
        with patch.dict("subtitle_tool.openai_client.os.environ", {"ZAI_TIMEOUT_SECONDS": "bad"}):
            self.assertEqual(_api_timeout_seconds("ZAI_TIMEOUT_SECONDS"), DEFAULT_API_TIMEOUT_SECONDS)

    def test_api_timeout_reads_env_value(self):
        with patch.dict("subtitle_tool.openai_client.os.environ", {"ZAI_TIMEOUT_SECONDS": "12.5"}):
            self.assertEqual(_api_timeout_seconds("ZAI_TIMEOUT_SECONDS"), 12.5)

    def test_zai_translation_waits_and_retries_on_rate_limit(self):
        segments = [
            SubtitleSegment(index=1, start_ms=0, end_ms=1000, text="hello"),
        ]
        progress_messages = []
        calls = 0

        def fake_chat_json_object(client, model, system_prompt, user_prompt):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError(
                    "Error code: 429 - {'error': {'code': '1302', 'message': '您的账户已达到速率限制，请您控制请求频率'}}"
                )
            return '{"items":[{"index":1,"text":"こんにちは"}]}'

        with patch.dict(
            "subtitle_tool.openai_client.os.environ",
            {
                "ZAI_REQUEST_DELAY_SECONDS": "0",
                "ZAI_RATE_LIMIT_RETRY_SECONDS": "0.01",
                "ZAI_RATE_LIMIT_RETRY_LIMIT": "2",
            },
        ), patch("subtitle_tool.openai_client.build_zai_client", return_value=object()), patch(
            "subtitle_tool.openai_client._chat_json_object",
            side_effect=fake_chat_json_object,
        ), patch("subtitle_tool.openai_client.time.sleep") as sleep:
            translations = translate_segments_with_zai(
                segments, "ja", progress_callback=progress_messages.append
            )

        self.assertEqual(translations, {1: "こんにちは"})
        self.assertEqual(calls, 2)
        sleep.assert_called_once_with(1.0)
        self.assertTrue(
            any(message.startswith("z.ai 触发限流") for message in progress_messages)
        )

    def test_zai_translation_raises_typed_error_after_rate_limit_retries(self):
        segments = [
            SubtitleSegment(index=1, start_ms=0, end_ms=1000, text="hello"),
        ]

        with patch.dict(
            "subtitle_tool.openai_client.os.environ",
            {
                "ZAI_RATE_LIMIT_RETRY_SECONDS": "0.01",
                "ZAI_RATE_LIMIT_RETRY_LIMIT": "1",
            },
        ), patch(
            "subtitle_tool.openai_client.build_zai_client", return_value=object()
        ), patch(
            "subtitle_tool.openai_client._chat_json_object",
            side_effect=RuntimeError("Error code: 429 - code 1302 速率限制"),
        ), patch("subtitle_tool.openai_client.time.sleep"):
            with self.assertRaises(Exception) as raised:
                translate_segments_with_zai(segments, "ja")

        self.assertEqual(type(raised.exception).__name__, "ProviderRateLimitError")

    def test_zai_request_delay_reads_env_value(self):
        with patch.dict("subtitle_tool.openai_client.os.environ", {"ZAI_REQUEST_DELAY_SECONDS": "4.5"}):
            self.assertEqual(
                _float_env(
                    "ZAI_REQUEST_DELAY_SECONDS",
                    DEFAULT_ZAI_REQUEST_DELAY_SECONDS,
                    minimum=0.0,
                ),
                4.5,
            )

    def test_zai_resume_requests_only_missing_indexes_and_checkpoints(self):
        segments = [
            SubtitleSegment(index=index, start_ms=0, end_ms=1000, text=f"text {index}")
            for index in range(1, 4)
        ]
        requested_indexes = []
        checkpoints = []

        def fake_chat(client, model, system_prompt, user_prompt):
            payload = json.loads(user_prompt)
            indexes = [item["index"] for item in payload["subtitles"]]
            requested_indexes.extend(indexes)
            return json.dumps(
                {"items": [{"index": index, "text": f"ja {index}"} for index in indexes]}
            )

        with patch.dict(
            "subtitle_tool.openai_client.os.environ", {"ZAI_REQUEST_DELAY_SECONDS": "0"}
        ), patch(
            "subtitle_tool.openai_client.build_zai_client", return_value=object()
        ), patch(
            "subtitle_tool.openai_client._chat_json_object", side_effect=fake_chat
        ):
            translations = translate_segments_with_zai(
                segments,
                "ja",
                initial_translations={1: "ja 1"},
                checkpoint_callback=lambda values: checkpoints.append(dict(values)),
            )

        self.assertEqual(requested_indexes, [2, 3])
        self.assertEqual(translations, {1: "ja 1", 2: "ja 2", 3: "ja 3"})
        self.assertEqual(checkpoints[-1], translations)


if __name__ == "__main__":
    unittest.main()
