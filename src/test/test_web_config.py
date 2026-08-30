import tempfile
import unittest
from pathlib import Path

from src.webapp.config import SettingsError, load_app_settings


class WebConfigTests(unittest.TestCase):
    def test_default_settings_use_auto_translation_without_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = load_app_settings(root)

            self.assertEqual(settings.web.host, "127.0.0.1")
            self.assertEqual(settings.web.port, 8766)
            self.assertEqual(settings.translation.mode, "auto")
            self.assertFalse(settings.translation.has_api_key)
            self.assertEqual(settings.x.cookies_dir, (root / "cookies").resolve())

    def test_yaml_settings_are_loaded_and_paths_resolved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config.yaml").write_text(
                """
web:
  host: 0.0.0.0
  port: 9001
  open_browser: false
x:
  monitor_config: conf/monitor.json
  cookies_dir: auth-cookies
translation:
  mode: required
  model: gemini-test
  batch_size: 7
  max_attempts_per_batch: 2
  gemini_api_keys:
    key2: second
    key1: first
""".strip(),
                encoding="utf-8",
            )

            settings = load_app_settings(root)

            self.assertEqual(settings.web.host, "0.0.0.0")
            self.assertEqual(settings.web.port, 9001)
            self.assertFalse(settings.web.open_browser)
            self.assertEqual(settings.x.monitor_config, (root / "conf/monitor.json").resolve())
            self.assertEqual(settings.x.cookies_dir, (root / "auth-cookies").resolve())
            self.assertEqual(settings.translation.mode, "required")
            self.assertEqual(settings.translation.model, "gemini-test")
            self.assertEqual(settings.translation.batch_size, 7)
            self.assertEqual(settings.translation.api_keys, ("first", "second"))

    def test_invalid_translation_mode_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config.yaml").write_text(
                "translation:\n  mode: sometimes\n",
                encoding="utf-8",
            )
            with self.assertRaises(SettingsError):
                load_app_settings(root)


if __name__ == "__main__":
    unittest.main()
