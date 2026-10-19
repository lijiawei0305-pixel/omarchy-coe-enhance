"""Capability-driven language selection; never edit the desktop's real config."""

import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import coe_languages as languages
import coe_config as config


class LanguageTests(unittest.TestCase):
    def profile(self, preset, **changes):
        return dict(copy.deepcopy(config.PRESETS[preset]), **changes)

    def test_model_capabilities_are_not_just_provider_capabilities(self):
        qwen = self.profile("aliyun")
        fun = self.profile("aliyun", model="fun-asr-flash-2026-06-15")
        self.assertEqual(languages.capabilities(qwen)["max_hints"], 4)
        self.assertEqual(languages.capabilities(fun)["max_hints"], 1)
        self.assertEqual(languages.capabilities(fun)["mode"], "single")
        for p in (qwen, fun):
            for code in ("", "auto", "zh", "en", "ja"):
                languages.validate(dict(p, language=code))
        languages.validate(dict(qwen, language="zh,en,ja,ko"))
        with self.assertRaises(ValueError):
            languages.validate(dict(fun, language="zh,en"))

    def test_auto_only_adapters_reject_ignored_language_fields(self):
        for preset in ("doubao", "qwen"):
            p = self.profile(preset)
            self.assertEqual(languages.capabilities(p)["codes"], [])
            self.assertEqual(languages.capabilities(p)["mode"], "none")
            languages.validate(p)
            with self.assertRaises(ValueError):
                languages.validate(dict(p, language="zh"))

    def test_sensevoice_has_only_its_five_spoken_languages(self):
        p = self.profile("sensevoice")
        self.assertEqual(
            languages.capabilities(p)["codes"], ["zh", "en", "yue", "ja", "ko"]
        )
        for code in ("ru", "fr", "zh,en", "nospeech"):
            with self.assertRaises(ValueError):
                languages.validate(dict(p, language=code))

    def test_custom_server_does_not_inherit_official_model_languages(self):
        for changes in (
            {"endpoint": "https://custom.example/v1/audio/transcriptions"},
            {"model": "unknown-model"},
            {"endpoint": "https://api.openai.com.evil.example/v1/audio/transcriptions"},
        ):
            cap = languages.capabilities(self.profile("openai", **changes))
            self.assertFalse(cap["verified"])
            self.assertEqual(cap["codes"], [])
        self.assertTrue(languages.capabilities(self.profile("openai"))["verified"])

    def test_unknown_aliyun_model_does_not_claim_four_hints(self):
        cap = languages.capabilities(self.profile("aliyun", model="unknown-model"))
        self.assertFalse(cap["verified"])
        self.assertEqual(cap["codes"], [])
        self.assertEqual(cap["max_hints"], 1)

    def test_wrong_protocol_and_malformed_hints_rejected(self):
        cap = languages.capabilities(self.profile("aliyun", protocol="chat-audio"))
        self.assertEqual(cap["mode"], "none")
        for language in ("zh,,en", "zh,en,", "zh,en,ja,ko,fr", "zh,unknown", "zh\nen"):
            with self.assertRaises(ValueError):
                languages.validate(self.profile("aliyun", language=language))

    def test_catalog_copies_are_isolated(self):
        a = languages.catalog()
        a["rules"][0]["codes"].clear()
        self.assertIn("zh", languages.catalog()["rules"][0]["codes"])
        cap = languages.capabilities(self.profile("aliyun"))
        cap["codes"].clear()
        self.assertIn("zh", languages.capabilities(self.profile("aliyun"))["codes"])


if __name__ == "__main__":
    unittest.main()
