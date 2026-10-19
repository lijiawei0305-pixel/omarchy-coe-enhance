from pathlib import Path
import json
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import coe_output as o
import coe_hotkey as h

TARGET = {"address": "0x1234", "pid": 222, "class": "foot", "tags": ["terminal*"]}


class OutputTests(unittest.TestCase):
    def setUp(self):
        probe = patch.object(h, "native_hotkey_conflict", return_value=False)
        probe.start()
        self.addCleanup(probe.stop)

    def test_terminal_classification_without_titles(self):
        for cls in ["kitty", "Alacritty", "foot", "com.mitchellh.ghostty"]:
            self.assertEqual(
                o.shortcut({"class": cls, "title": "Codex / Claude Code"}),
                ("SHIFT", "Insert"),
            )
        self.assertEqual(
            o.shortcut({"class": "other", "tags": ["terminal*"]}), ("SHIFT", "Insert")
        )
        for cls in [
            "google-chrome",
            "chrome-chatgpt.com__-Default",
            "code",
            "org.gnome.TextEditor",
        ]:
            self.assertEqual(
                o.shortcut({"class": cls, "title": "terminal"}), ("CTRL", "V")
            )

    def test_complete_chinese_via_stdin_once(self):
        text = "我正在使用 Omarchy，需要在 VS Code 里面配置 GitHub。"

        def run(cmd, **kw):
            return subprocess.CompletedProcess(
                cmd,
                0,
                stdout=text.encode() if cmd[0] == "wl-paste" else b"",
                stderr=b"",
            )

        with (
            patch.object(o, "run", side_effect=run) as calls,
            patch.object(o, "active_window", return_value=TARGET),
        ):
            self.assertEqual(o.deliver(text, TARGET), "pasted")
        self.assertEqual(calls.call_args_list[0].kwargs["input"], text.encode())
        self.assertEqual(
            len([c for c in calls.call_args_list if c.args[0][0] == "hyprctl"]), 1
        )
        self.assertNotIn(text, str(calls.call_args_list[-1]))

    def test_empty_never_touches_clipboard_or_keys(self):
        with patch.object(o, "run") as r:
            self.assertEqual(o.deliver("  ", TARGET), "empty")
            r.assert_not_called()

    def test_changed_focus_copies_without_keys(self):
        with (
            patch.object(o, "run") as r,
            patch.object(o, "active_window", return_value={**TARGET, "pid": 999}),
        ):
            self.assertEqual(o.deliver("中文", TARGET), "copied")
            self.assertEqual(r.call_count, 1)

    def test_no_target_panel_open_or_switch_and_return_never_pastes(self):
        for target, safe in [({}, True), (TARGET, False)]:
            with (
                patch.object(o, "run") as r,
                patch.object(o, "active_window", return_value=TARGET),
            ):
                self.assertEqual(o.deliver("中文", target, safe=lambda: safe), "copied")
                self.assertEqual(r.call_count, 1)

    def test_old_clipboard_cannot_be_inserted(self):
        with (
            patch.object(
                o, "run", return_value=subprocess.CompletedProcess([], 0, stdout=b"old")
            ) as r,
            patch.object(o, "active_window", return_value=TARGET),
        ):
            self.assertEqual(o.deliver("新的中文", TARGET), "clipboard-changed")
            self.assertEqual(r.call_count, 2)

    def test_copy_failure_does_not_send_key(self):
        with patch.object(o, "run", side_effect=RuntimeError("copy failed")) as r:
            with self.assertRaises(RuntimeError):
                o.deliver("中文", TARGET)
            self.assertEqual(r.call_count, 1)

    def test_hotkey_conflict_and_parser(self):
        with patch.object(
            h,
            "run",
            return_value='[{"modmask":68,"key":"X","description":"Toggle dictation"}]',
        ):
            self.assertTrue(h.conflict("SUPER + CTRL + X"))
            self.assertFalse(h.conflict("F9"))
        for value in ["A", "F9; rm -rf ~", "CTRL + CTRL + D", "SUPER + $(id)"]:
            with self.assertRaises(ValueError):
                h.normalize(value)

    def test_right_alt_toggle_and_conflicts(self):
        self.assertEqual(h.normalize(" alt_r "), "Alt_R")
        for mask, release in [(0, False), (8, True)]:
            with patch.object(
                h,
                "run",
                return_value=json.dumps(
                    [
                        {
                            "modmask": mask,
                            "key": "Alt_R",
                            "release": release,
                            "description": "Voxtype dictation",
                        }
                    ]
                ),
            ):
                self.assertTrue(h.conflict("Alt_R"))
        with patch.object(
            h,
            "run",
            return_value=json.dumps(
                [
                    {
                        "modmask": 0,
                        "key": "Alt_R",
                        "description": "Coe Enhance 语音输入",
                    },
                    {"modmask": 0, "key": "Alt_L", "description": "Other shortcut"},
                ]
            ),
        ):
            self.assertFalse(h.conflict("Alt_R"))
        with (
            patch.object(h, "conflict", return_value=False),
            patch.object(h, "run") as run,
        ):
            h.install("Alt_R", "/safe/coe-toggle", "test-owner")
            self.assertIn('hl.bind("Alt_R"', run.call_args.args[0][-1])
            self.assertNotIn("release=true", run.call_args.args[0][-1])

    def test_right_alt_hold_has_separate_owned_press_release_bindings(self):
        with (
            patch.object(h, "conflict", return_value=False),
            patch.object(h, "run") as run,
        ):
            h.install("Alt_R", "/safe/toggle", "owner", "hold", "/safe/hold")
            lua = run.call_args.args[0][-1]
            self.assertIn('hl.bind("Alt_R", _G.cc_coe_press', lua)
            self.assertIn('hl.bind("ALT + Alt_R", _G.cc_coe_release', lua)
            self.assertIn("release=true,ignore_mods=true", lua)
            self.assertIn("cc_coe_down then return", lua)
            h.remove("owner")
            self.assertIn("cc_coe_release_binding:unbind()", run.call_args.args[0][-1])
        with self.assertRaises(ValueError):
            h.validate_mode("F9", "hold")

    def test_late_conflict_removes_only_owned_handles(self):
        with (
            patch.object(h, "conflict", return_value=True),
            patch.object(h, "run") as run,
        ):
            with self.assertRaisesRegex(ValueError, "未接管"):
                h.install("Alt_R", "/safe/toggle", "owner", "hold", "/safe/hold")
            lua = run.call_args.args[0][-1]
            self.assertIn('_G.cc_coe_owner == "owner"', lua)
            self.assertNotIn("hl.unbind", lua)
            self.assertNotIn("hl.bind(", lua)

    def test_stock_omarchy_bindings_are_compatible(self):
        bindings = [
            {"modmask": 68, "key": "X", "description": "Toggle dictation"},
            {"modmask": 0, "key": "F9", "description": "Start dictation"},
            {
                "modmask": 0,
                "key": "F9",
                "release": True,
                "description": "Stop dictation",
            },
        ]
        with patch.object(h, "run", return_value=json.dumps(bindings)):
            self.assertFalse(h.conflict("Alt_R"))

    def test_native_right_alt_blocks_without_hyprland_binding(self):
        with (
            patch.object(h, "native_hotkey_conflict", return_value=True),
            patch.object(h, "run") as run,
        ):
            self.assertTrue(h.conflict("Alt_R"))
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
