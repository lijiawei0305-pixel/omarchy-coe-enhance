import copy
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import coe_config as c


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        p = Path(self.tmp.name)
        self.patch = patch.multiple(
            c,
            ROOT=p / "plugin",
            CONFIG=p / "coe/config.yaml",
            ENV=p / "coe/env",
            STORE=p / "plugin/profiles.json",
        )
        self.patch.start()
        c.initialize()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def req(self, kind="openai"):
        p = copy.deepcopy(c.PRESETS[kind])
        p.update(timeout=3)
        return {"profile": p, "api_key": "test-secret-NEVER-LOG"}

    def test_comment_dictionary_and_permissions(self):
        c.CONFIG.parent.mkdir()
        c.CONFIG.write_text(
            "# user comment\ndictionary: # Keep dictionary\n  file: ./my-terms.yaml\ncustom: {value: 7}\nasr:\n  provider: openai # existing provider comment\n"
        )
        os.chmod(c.CONFIG, 0o640)
        backup = c.save_profile(self.req(), lambda: None)
        raw = c.CONFIG.read_text()
        self.assertIn("# user comment", raw)
        self.assertIn("# Keep dictionary", raw)
        self.assertIn("existing provider comment", raw)
        self.assertIn("my-terms.yaml", raw)
        self.assertEqual(c.yaml_load()[1]["custom"]["value"], 7)
        self.assertEqual(stat.S_IMODE(c.CONFIG.stat().st_mode), 0o640)
        self.assertEqual(stat.S_IMODE(c.ENV.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(Path(backup).stat().st_mode), 0o700)
        self.assertNotIn("test-secret", c.STORE.read_text())
        self.assertNotIn("test-secret", json.dumps(c.public_store()))

    def test_restart_failure_rolls_back_every_file(self):
        c.save_profile(self.req(), lambda: None)
        paths = [c.CONFIG, c.ENV, c.STORE]
        before = {p: p.read_bytes() for p in paths}
        with self.assertRaises(RuntimeError):
            c.save_profile(
                self.req("qwen"),
                lambda: (_ for _ in ()).throw(RuntimeError("service failed")),
            )
        self.assertEqual(before, {p: p.read_bytes() for p in paths})

    def test_aliyun_native_validation_and_profile(self):
        req = self.req("aliyun")
        req["profile"].update(language="zh,en", prompt="VASP, DFT, Cu(111)")
        c.save_profile(req, lambda: None)
        asr = c.yaml_load()[1]["asr"]
        self.assertEqual(asr["provider"], "aliyun-asr")
        self.assertIn("/api/v1/services/", asr["endpoint"])
        self.assertEqual(asr["language"], "zh,en")
        for field, value in [("prompt", "字" * 401), ("language", "zh,en,ja,ko,fr")]:
            bad = copy.deepcopy(req["profile"])
            bad[field] = value
            with self.assertRaises(ValueError):
                c.validate_profile(bad)

    def test_atomic_failure_rolls_back(self):
        c.save_profile(self.req(), lambda: None)
        before = c.CONFIG.read_bytes()
        original = c.atomic

        def fail(path, *args, **kw):
            if (
                path == c.CONFIG
                and args
                and b"new-name"
                in (args[0].encode() if isinstance(args[0], str) else args[0])
            ):
                raise OSError("disk failure")
            return original(path, *args, **kw)

        req = self.req()
        req["profile"]["model"] = "new-name"
        with (
            patch.object(c, "atomic", side_effect=fail),
            self.assertRaises(RuntimeError),
        ):
            c.save_profile(req, lambda: None)
        self.assertEqual(before, c.CONFIG.read_bytes())

    def test_switch_changes_backend_not_only_profile_name(self):
        c.save_profile(self.req(), lambda: None)
        a = c.read_store()["active"]
        c.save_profile(self.req("qwen"), lambda: None)
        s = c.read_store()
        b = s["active"]
        self.assertNotEqual(a, b)
        self.assertEqual(c.yaml_load()[1]["asr"]["provider"], "qwen3-asr-vllm")
        p = next(x for x in s["profiles"] if x["id"] == a)
        c.save_profile({"id": a, "profile": p}, lambda: None)
        self.assertEqual(c.yaml_load()[1]["asr"]["model"], "gpt-4o-mini-transcribe")
        self.assertEqual(c.read_store()["active"], a)

    def test_duplicate_delete_default_and_credential_isolation(self):
        c.save_profile(self.req(), lambda: None)
        s = c.read_store()
        a = s["active"]
        c.profile_action("duplicate", a)
        b = c.read_store()["profiles"][-1]
        self.assertNotEqual(b["key_ref"], c.read_store()["profiles"][-2]["key_ref"])
        self.assertEqual(c.env_values()[b["key_ref"]], "test-secret-NEVER-LOG")
        c.profile_action("default", b["id"])
        self.assertEqual(c.read_store()["default"], b["id"])
        c.profile_action("delete", b["id"])
        self.assertEqual(
            len(c.read_store()["profiles"]), 2
        )  # initial unapplied placeholder + first saved
        self.assertIn(
            b["key_ref"], c.env_values()
        )  # deletion never destroys credentials
        with self.assertRaises(ValueError):
            c.profile_action("delete", a)

    def test_llm_independent_and_disabled_stub(self):
        req = self.req()
        req["llm"] = copy.deepcopy(c.read_store()["llm"])
        req["llm"].update(enabled=True, model="my-llm")
        req["llm_key"] = "independent-secret"
        c.save_profile(req, lambda: None)
        cfg = c.yaml_load()[1]
        self.assertEqual(cfg["llm"]["provider"], "openai")
        self.assertNotEqual(cfg["llm"]["api_key_env"], cfg["asr"]["api_key_env"])
        req["llm"]["enabled"] = False
        c.save_profile(req, lambda: None)
        self.assertEqual(c.yaml_load()[1]["llm"]["provider"], "stub")
        self.assertEqual(c.yaml_load()[1]["asr"]["provider"], "openai")

    def test_reject_unknown_protocol_and_types(self):
        for change in (
            {"protocol": "json-base64"},
            {"timeout": True},
            {"timeout": 0},
            {"timeout": "60"},
            {"endpoint": "https://user:secret@example.org/v1"},
            {"endpoint": "https://example.org?key=secret"},
        ):
            p = copy.deepcopy(self.req()["profile"])
            p.update(change)
            with self.assertRaises(ValueError):
                c.validate_profile(p)

    def test_preserve_prompt_file_per_profile(self):
        req = self.req()
        c.save_profile(req, lambda: None)
        s = c.read_store()
        p = next(x for x in s["profiles"] if x["id"] == s["active"])
        p["prompt_file"] = "/tmp/custom-template"
        c.save_profile({"id": p["id"], "profile": p}, lambda: None)
        c.save_profile(self.req("qwen"), lambda: None)
        self.assertEqual(c.yaml_load()[1]["asr"]["prompt_file"], "")
        c.save_profile({"id": p["id"], "profile": p}, lambda: None)
        self.assertEqual(c.yaml_load()[1]["asr"]["prompt_file"], "/tmp/custom-template")

    def test_import_direct_key_not_in_profile_then_migrate(self):
        c.STORE.unlink()
        c.CONFIG.parent.mkdir()
        c.CONFIG.write_text(
            'asr:\n  provider: openai\n  api_key: old-private-token\n  api_key_env: ""\nllm:\n  provider: stub\n'
        )
        before = c.CONFIG.read_bytes()
        c.initialize()
        self.assertEqual(before, c.CONFIG.read_bytes())
        self.assertNotIn("old-private-token", c.STORE.read_text())
        s = c.read_store()
        p = s["profiles"][0]
        c.save_profile({"id": p["id"], "profile": p}, lambda: None)
        self.assertEqual(c.yaml_load()[1]["asr"]["api_key"], "")
        self.assertIn("old-private-token", c.env_values().values())

    def test_user_restart_last_good_recovery(self):
        c.save_profile(self.req(), lambda: None)
        before = c.CONFIG.read_bytes()
        env = c.ENV.read_bytes()
        c.atomic(c.CONFIG, "broken: [")
        c.restore_good()
        self.assertEqual(c.CONFIG.read_bytes(), before)
        self.assertEqual(c.ENV.read_bytes(), env)

    def test_symlinks_refused(self):
        target = Path(self.tmp.name) / "secret"
        target.write_text("untouched")
        link = Path(self.tmp.name) / "link"
        link.symlink_to(target)
        with self.assertRaises(ValueError):
            c.atomic(link, "new")
        self.assertEqual(target.read_text(), "untouched")

    def test_quick_preferences_preserve_connections_and_template(self):
        req = self.req("aliyun")
        req["llm"] = copy.deepcopy(c.read_store()["llm"])
        req["llm"].update(enabled=True, model="my-llm", prompt="保留 {{.Dictionary}}")
        req["llm_key"] = "independent-secret"
        c.save_profile(req, lambda: None)
        before = copy.deepcopy(c.read_store())
        env = c.ENV.read_bytes()
        c.update_preferences({"llm_enabled": False}, lambda: None)
        after = c.read_store()
        self.assertFalse(after["llm"]["enabled"])
        self.assertEqual(c.yaml_load()[1]["llm"]["provider"], "stub")
        self.assertEqual(before["profiles"], after["profiles"])
        self.assertEqual(before["llm"] | {"enabled": False}, after["llm"])
        self.assertEqual(env, c.ENV.read_bytes())
        c.update_preferences({"llm_enabled": True, "language": "zh"}, lambda: None)
        self.assertEqual(c.yaml_load()[1]["llm"]["provider"], "openai")
        self.assertEqual(c.yaml_load()[1]["asr"]["language"], "zh")
        self.assertEqual(c.read_store()["active"], before["active"])

    def test_output_preference_never_restarts_core(self):
        c.save_profile(self.req(), lambda: None)
        before = {p: p.read_bytes() for p in [c.CONFIG, c.ENV]}
        c.update_preferences({"output": "clipboard"}, lambda: self.fail("restart"))
        self.assertEqual(c.read_store()["output"], "clipboard")
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_unsupported_language_and_missing_llm_key_rejected(self):
        c.save_profile(self.req("qwen"), lambda: None)
        before = c.STORE.read_bytes()
        for req in [{"language": "zh"}, {"llm_enabled": True}, {"llm_enabled": 1}]:
            with self.assertRaises(ValueError):
                c.update_preferences(req, lambda: self.fail("restart"))
        self.assertEqual(before, c.STORE.read_bytes())

    def test_language_preferences_guard_profile_and_preserve_other_settings(self):
        c.save_profile(self.req("aliyun"), lambda: None)
        before = copy.deepcopy(c.read_store())
        env = c.ENV.read_bytes()
        active = c.active_profile()
        for language in ("zh", "en", ""):
            c.update_preferences(
                {"language": language, "language_profile_id": active["id"]},
                lambda: None,
            )
            after = c.read_store()
            self.assertEqual(c.yaml_load()[1]["asr"]["language"], language)
            self.assertEqual(after["llm"], before["llm"])
            self.assertEqual(c.ENV.read_bytes(), env)
            current = c.active_profile()
            self.assertEqual({**current, "language": active["language"]}, active)
            self.assertEqual(after["profiles"][0], before["profiles"][0])
        before_files = {p: p.read_bytes() for p in (c.CONFIG, c.STORE, c.ENV)}
        for req in (
            {"language": "zh", "language_profile_id": "previous-profile"},
            {"language": "zh,en"},
            {"language": "yue"},
        ):
            with self.assertRaises(ValueError):
                c.update_preferences(req, lambda: self.fail("must not restart"))
        self.assertEqual(before_files, {p: p.read_bytes() for p in before_files})

    def test_legacy_language_is_not_changed_by_unrelated_edits(self):
        c.save_profile(self.req("aliyun"), lambda: None)
        s = c.read_store()
        p = next(x for x in s["profiles"] if x["id"] == s["active"])
        p.update(model="fun-asr-flash-2026-06-15", language="zh,en")
        c.write_store(s)  # Imported legacy settings previously allowed four hints.
        p["name"] = "只编辑名称"
        c.save_profile({"id": p["id"], "profile": p}, lambda: None)
        self.assertEqual(c.active_profile()["language"], "zh,en")
        self.assertEqual(c.yaml_load()[1]["asr"]["language"], "zh,en")

    def test_public_capability_metadata_does_not_modify_saved_profiles(self):
        c.save_profile(self.req("aliyun"), lambda: None)
        before = {p: p.read_bytes() for p in (c.CONFIG, c.ENV, c.STORE)}
        public = c.public_store()
        self.assertIn("language_catalog", public)
        self.assertNotIn("language_catalog", c.read_store())
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_explicit_key_removal_isolated_and_empty_keeps_key(self):
        c.save_profile(self.req(), lambda: None)
        first = c.active_profile()
        c.profile_action("duplicate", first["id"])
        second = c.read_store()["profiles"][-1]
        c.save_profile(
            {"id": first["id"], "profile": first, "api_key": ""}, lambda: None
        )
        self.assertTrue(c.public_store()["profiles"][1]["key_present"])
        c.save_profile(
            {"id": first["id"], "profile": first, "delete_api_key": True}, lambda: None
        )
        self.assertEqual(c.env_values()[c.active_profile()["key_ref"]], "")
        self.assertEqual(c.env_values()[second["key_ref"]], "test-secret-NEVER-LOG")

    def test_preference_restart_failure_restores_effective_selection(self):
        c.save_profile(self.req(), lambda: None)
        before = {p: p.read_bytes() for p in [c.CONFIG, c.ENV, c.STORE]}
        with self.assertRaises(RuntimeError):
            c.update_preferences(
                {"language": "zh"}, lambda: (_ for _ in ()).throw(RuntimeError())
            )
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_noop_edit_and_llm_roundtrip_keep_store_bytes(self):
        req = self.req()
        req["llm"] = copy.deepcopy(c.read_store()["llm"])
        req["llm_key"] = "independent-secret"
        c.save_profile(req, lambda: None)
        before = c.STORE.read_bytes()
        p = c.active_profile()
        p["name"] += " "  # GUI draft is dirty; validated name stays unchanged.
        c.save_profile({"id": p["id"], "profile": p}, lambda: None)
        c.update_preferences({"llm_enabled": True}, lambda: None)
        c.update_preferences({"llm_enabled": False}, lambda: None)
        self.assertEqual(before, c.STORE.read_bytes())

    def test_removed_key_not_reported_present_from_stale_shell_env(self):
        c.save_profile(self.req(), lambda: None)
        p = c.active_profile()
        with patch.dict(os.environ, {p["key_ref"]: "stale-test-secret"}):
            c.save_profile(
                {"id": p["id"], "profile": p, "delete_api_key": True}, lambda: None
            )
            current = next(
                x for x in c.public_store()["profiles"] if x["id"] == p["id"]
            )
            self.assertFalse(current["key_present"])

    def test_noop_and_rename_do_not_restart_backend(self):
        c.save_profile(self.req(), lambda: None)
        p = c.active_profile()
        calls = []
        c.save_profile({"id": p["id"], "profile": p}, lambda: calls.append(1))
        p["name"] = "仅重命名"
        c.save_profile({"id": p["id"], "profile": p}, lambda: calls.append(1))
        self.assertEqual(calls, [])
        p["model"] = "new-model"
        c.save_profile({"id": p["id"], "profile": p}, lambda: calls.append(1))
        self.assertEqual(calls, [1])

    def test_public_snapshot_cache_invalidates_and_is_not_mutable(self):
        c.save_profile(self.req(), lambda: None)
        first = c.cached_public_store()
        first["profiles"].clear()
        self.assertTrue(c.cached_public_store()["profiles"])
        p = c.active_profile()
        c.profile_action("duplicate", p["id"])
        self.assertEqual(
            len(c.cached_public_store()["profiles"]), len(c.read_store()["profiles"])
        )


if __name__ == "__main__":
    unittest.main()
