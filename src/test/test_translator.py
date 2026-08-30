import unittest

from src.services.translator import (
    GeminiVietnameseTranslator,
    TranslationError,
    _extract_json_array,
    normalize_api_keys,
)


class _Response:
    def __init__(self, text):
        self.text = text


class _Models:
    def __init__(self, callback):
        self.callback = callback

    def generate_content(self, model, contents):
        return self.callback(model, contents)


class _Client:
    def __init__(self, callback):
        self.models = _Models(callback)


class TranslatorTests(unittest.TestCase):
    def test_normalize_api_keys_is_deterministic(self):
        self.assertEqual(
            normalize_api_keys({"key2": "B", "key1": "A", "empty": ""}),
            ["A", "B"],
        )

    def test_extract_json_array_accepts_fenced_output(self):
        self.assertEqual(
            _extract_json_array('```json\n["xin chào", "thế giới"]\n```'),
            ["xin chào", "thế giới"],
        )

    def test_extract_json_array_rejects_non_array(self):
        with self.assertRaises(TranslationError):
            _extract_json_array('{"text":"bad"}')

    def test_batching_progress_and_key_rotation(self):
        used_keys = []
        payloads = [
            '["vi-1", "vi-2"]',
            '["vi-3"]',
        ]

        def factory(key):
            used_keys.append(key)
            index = len(used_keys) - 1
            return _Client(lambda model, contents: _Response(payloads[index]))

        progress = []
        translator = GeminiVietnameseTranslator(
            ["K1", "K2"],
            batch_size=2,
            client_factory=factory,
        )
        result = translator.translate_many(
            ["one", "two", "three"],
            progress_callback=lambda done, total: progress.append((done, total)),
        )

        self.assertEqual(result, ["vi-1", "vi-2", "vi-3"])
        self.assertEqual(used_keys, ["K1", "K2"])
        self.assertEqual(progress, [(2, 3), (3, 3)])

    def test_retry_rotates_key(self):
        used_keys = []

        def factory(key):
            used_keys.append(key)
            if key == "K1":
                return _Client(lambda model, contents: (_ for _ in ()).throw(RuntimeError("quota")))
            return _Client(lambda model, contents: _Response('["ổn"]'))

        translator = GeminiVietnameseTranslator(
            ["K1", "K2"],
            max_attempts_per_batch=2,
            client_factory=factory,
        )
        self.assertEqual(translator.translate_many(["ok"]), ["ổn"])
        self.assertEqual(used_keys, ["K1", "K2"])


if __name__ == "__main__":
    unittest.main()
