import importlib.util
from pathlib import Path
import sys
import threading
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
spec = importlib.util.spec_from_file_location(
    "bridge", Path(__file__).resolve().parents[1] / "scripts/coe-bridge.py"
)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class ImmediateThread:
    def __init__(self, target, **kw):
        self.target = target

    def start(self):
        self.target()


class BridgeTests(unittest.TestCase):
    def bridge(self):
        b = m.Bridge.__new__(m.Bridge)
        b.seen = set()
        b.session = "s1"
        b.expected_session = "s1"
        b.armed = True
        b.target = {"address": "0x123"}
        b.switched = False
        b.panel = False
        b.alive = True
        b.notice = ""
        b.error = ""
        b.state = "idle"
        b.owner = "test-owner"
        b.lock = threading.RLock()
        b.hold_lock = threading.Lock()
        b.hold_id = ""
        b.hold_released = set()
        b.hold_timer = None
        b.voxtype_state = "not-checked"
        b.emit = Mock()
        return b

    def test_official_voice_busy_never_starts_or_arms_coe(self):
        for state in ("recording", "transcribing", "streaming", "unknown"):
            with self.subTest(state=state):
                b = self.bridge()
                b.armed = False
                b.get_status = Mock(return_value=("idle", "s1", ""))
                b.iface = Mock()
                with (
                    patch.object(m.compat, "probe_voxtype", return_value=state),
                    patch.object(m.output, "active_window") as active,
                ):
                    with self.assertRaises(ValueError):
                        b.trigger("start")
                    self.assertEqual(b.voxtype_state, state)
                    self.assertFalse(b.armed)
                    b.iface.assert_not_called()
                    active.assert_not_called()

    def test_official_voice_idle_starts_coe_once(self):
        b = self.bridge()
        b.get_status = Mock(return_value=("idle", "s1", ""))
        b.iface = Mock()
        b.sync = Mock()
        with (
            patch.object(m.compat, "probe_voxtype", return_value="idle") as probe,
            patch.object(m.config, "read_store", return_value={"active": "profile"}),
            patch.object(
                m.config,
                "cached_public_store",
                return_value={
                    "profiles": [
                        {"id": "profile", "provider": "openai", "key_present": True}
                    ]
                },
            ),
            patch.object(m.output, "active_window", return_value={"address": "0x123"}),
        ):
            b.trigger("start")
            probe.assert_called_once()
            b.iface.return_value.Start.assert_called_once_with(timeout=650)
            self.assertTrue(b.armed)

    def test_stop_cancel_do_not_depend_on_official_voice_probe(self):
        for action, method in (
            ("stop", "Stop"),
            ("cancel", "Cancel"),
            ("toggle", "Stop"),
        ):
            with self.subTest(action=action), tempfile.TemporaryDirectory() as tmp:
                b = self.bridge()
                b.get_status = Mock(return_value=("recording", "s1", ""))
                b.iface = Mock()
                b.sync = Mock()
                with (
                    patch.object(m.compat, "probe_voxtype") as probe,
                    patch.object(m, "HELD_FILE", Path(tmp) / "held"),
                ):
                    b.trigger(action)
                    probe.assert_not_called()
                    getattr(b.iface.return_value, method).assert_called_once_with(
                        timeout=650
                    )

    def test_status_updates_without_popup_commands(self):
        b = self.bridge()
        b.osd = Mock()
        with patch.object(m.subprocess, "run") as run:
            for state, detail in [
                ("recording", "recording"),
                ("processing", "processing asr"),
                ("processing", "processing llm; scene=general"),
                ("completed", "completed"),
                ("error", "500"),
            ]:
                b.state_changed(state, "s1", detail)
                self.assertEqual(b.state, state)
            b.error_raised("s1", "500")
            run.assert_not_called()
        self.assertEqual(b.osd.mock_calls, [])
        self.assertEqual(b.emit.call_count, 6)

    def test_output_feedback_stays_in_panel_without_popups(self):
        for result in [
            "pasted",
            "copied",
            "empty",
            "clipboard-changed",
            RuntimeError(),
        ]:
            with self.subTest(
                result=result if isinstance(result, str) else "output-error"
            ):
                b = self.bridge()
                b.osd = Mock()
                deliver = (
                    Mock(side_effect=result)
                    if isinstance(result, Exception)
                    else Mock(return_value=result)
                )
                with (
                    patch.object(m.threading, "Thread", ImmediateThread),
                    patch.object(
                        m.config, "read_store", return_value={"output": "smart"}
                    ),
                    patch.object(m.output, "deliver", deliver),
                    patch.object(m.subprocess, "run") as run,
                ):
                    b.result_ready("s1", "中文")
                    deliver.assert_called_once()
                    run.assert_not_called()
                self.assertTrue(b.notice or b.error)
                self.assertEqual(b.osd.mock_calls, [])
                b.emit.assert_called_once()

    def test_panel_rpc_response_is_valid(self):
        b = self.bridge()
        self.assertEqual(b.dispatch({"action": "panel", "open": True}), {"ok": True})
        self.assertTrue(b.panel)

    def test_duplicate_session_never_inserted_twice(self):
        b = self.bridge()
        with (
            patch.object(m.threading, "Thread", ImmediateThread),
            patch.object(m.config, "read_store", return_value={"output": "smart"}),
            patch.object(m.output, "deliver", return_value="pasted") as deliver,
        ):
            b.result_ready("s1", "中文")
            b.result_ready("s1", "中文")
            self.assertEqual(deliver.call_count, 1)

    def test_old_session_ignored(self):
        b = self.bridge()
        b.result_ready("old", "中文")
        self.assertTrue(b.armed)
        self.assertEqual(b.seen, set())

    def test_idle_status_race_does_not_drop_result(self):
        b = self.bridge()
        b.session = ""
        with (
            patch.object(m.threading, "Thread", ImmediateThread),
            patch.object(m.config, "read_store", return_value={"output": "smart"}),
            patch.object(m.output, "deliver", return_value="pasted") as deliver,
        ):
            b.result_ready("s1", "中文")
            deliver.assert_called_once()

    def test_no_target_after_shell_restart(self):
        b = self.bridge()
        b.armed = False
        with (
            patch.object(m.threading, "Thread", ImmediateThread),
            patch.object(m.config, "read_store", return_value={"output": "smart"}),
            patch.object(m.output, "deliver", return_value="copied") as deliver,
        ):
            b.result_ready("s1", "中文")
            self.assertEqual(deliver.call_args.args[1], {})

    def test_busy_rejects_config_change(self):
        b = self.bridge()
        b.get_status = Mock(return_value=("processing", "s1", ""))
        with self.assertRaises(ValueError):
            b.idle_required()

    def test_remote_error_never_reflected(self):
        for msg in [
            "401 key=private-secret",
            "429 private-secret",
            "500 私人正文",
            "bad response private-secret",
            "model=private-secret",
            "timeout private-secret",
        ]:
            self.assertNotIn("private-secret", m.safe_error(msg))
            self.assertNotIn("私人正文", m.safe_error(msg))

        b = self.bridge()
        b.osd = Mock()
        b.state_changed("error", "s1", "500 私人正文 private-secret")
        b.error_raised("s1", "500 私人正文 private-secret")
        self.assertNotIn("private-secret", b.error)
        self.assertNotIn("私人正文", b.error)
        self.assertEqual(b.osd.mock_calls, [])

    def test_status_names_are_coe_names(self):
        b = self.bridge()
        for state in ["idle", "recording", "processing", "completed", "error"]:
            b.state_changed(state, "s1", "normal detail")
            self.assertEqual(b.state, state)

    def test_hold_press_release_and_duplicate_release(self):
        b = self.bridge()
        b.get_status = Mock(return_value=("idle", "s1", ""))

        def trigger(action):
            b.state = "recording" if action == "start" else "idle"
            b.get_status.return_value = (b.state, "s1", "")

        b.trigger = Mock(side_effect=trigger)
        req = {"action": "hold", "owner": b.owner, "gesture": "a" * 32 + ":1"}
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(m, "HELD_FILE", Path(tmp) / "held.json"),
            patch.object(m.config, "read_store", return_value={"hotkey_mode": "hold"}),
            patch.object(m.threading, "Timer"),
        ):
            b.hold_event({**req, "event": "press"})
            b.hold_event({**req, "event": "press"})
            self.assertEqual(b.hold_id, req["gesture"])
            b.hold_event({**req, "event": "release"})
            b.hold_event({**req, "event": "release"})
            self.assertEqual(
                [c.args[0] for c in b.trigger.call_args_list], ["start", "stop"]
            )
            self.assertFalse(m.HELD_FILE.exists())

    def test_hold_release_arriving_before_press_never_records(self):
        b = self.bridge()
        b.trigger = Mock()
        req = {"action": "hold", "owner": b.owner, "gesture": "b" * 32 + ":1"}
        with patch.object(m.config, "read_store", return_value={"hotkey_mode": "hold"}):
            b.hold_event({**req, "event": "release"})
            b.hold_event({**req, "event": "press"})
        b.trigger.assert_not_called()

    def test_hold_rejects_foreign_owner_and_processing(self):
        b = self.bridge()
        b.trigger = Mock()
        b.state = "processing"
        req = {
            "action": "hold",
            "owner": b.owner,
            "gesture": "c" * 32 + ":1",
            "event": "press",
        }
        with patch.object(m.config, "read_store", return_value={"hotkey_mode": "hold"}):
            b.hold_event(req)
            b.state = "idle"
            b.hold_event({**req, "owner": "old-widget"})
        b.trigger.assert_not_called()

    def test_hold_missing_release_is_cancelled_not_transcribed(self):
        b = self.bridge()
        b.hold_id = "d" * 32 + ":1"
        b.trigger = Mock()
        b.hold_expired(b.hold_id)
        b.trigger.assert_called_once_with("cancel")

    def test_stale_held_recording_recovered_after_shell_kill(self):
        import json

        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / "held.json"
            iface = Mock()
            iface.Status.return_value = ("recording", "held-session", "")
            for state, session, expected in [
                ("recording", "held-session", True),
                ("recording", "different-session", False),
                ("processing", "held-session", False),
            ]:
                marker.write_text(
                    json.dumps({"owner": "old", "session": "held-session"})
                )
                iface.reset_mock()
                iface.Status.return_value = (state, session, "")
                with (
                    patch.object(m, "HELD_FILE", marker),
                    patch.object(m.dbus, "SessionBus"),
                    patch.object(m.dbus, "Interface", return_value=iface),
                ):
                    m.recover_held_recording()
                self.assertEqual(iface.Cancel.called, expected)
                self.assertFalse(marker.exists())

    def test_old_cleanup_does_not_cancel_new_hold_owner(self):
        import json

        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / "held.json"
            marker.write_text(json.dumps({"owner": "new", "session": "s2"}))
            with (
                patch.object(m, "HELD_FILE", marker),
                patch.object(m.dbus, "SessionBus") as bus,
            ):
                m.recover_held_recording("old")
                bus.assert_not_called()
            self.assertTrue(marker.exists())


if __name__ == "__main__":
    unittest.main()
