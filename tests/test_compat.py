import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import coe_compat as c


class CompatibilityTests(unittest.TestCase):
    def test_running_daemon_config_override_and_stale_pid(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root / "voxtype"
            runtime.mkdir()
            proc = root / "proc" / "4321"
            proc.mkdir(parents=True)
            proc.joinpath("comm").write_text("voxtype\n")
            launch = root / "launch"
            launch.mkdir()
            proc.joinpath("cwd").symlink_to(launch, target_is_directory=True)
            runtime.joinpath("voxtype.lock").write_text("4321\n")

            def mapped_path(value):
                return root / "proc" if str(value) == "/proc" else Path(value)

            with (
                patch.dict(c.os.environ, {"XDG_RUNTIME_DIR": tmp}),
                patch.object(c, "Path", side_effect=mapped_path),
            ):
                for args, expected in [
                    (
                        b"voxtype\0--config\0/private/config.toml\0",
                        Path("/private/config.toml"),
                    ),
                    (b"voxtype\0-c\0relative.toml\0", launch / "relative.toml"),
                    (
                        b"voxtype\0--config=/private/other.toml\0",
                        Path("/private/other.toml"),
                    ),
                ]:
                    proc.joinpath("cmdline").write_bytes(args)
                    self.assertEqual(c.config_override(), expected)
                proc.joinpath("comm").write_text("unrelated\n")
                self.assertIsNone(c.config_override())
                runtime.joinpath("voxtype.lock").write_text("-1\n")
                self.assertIsNone(c.config_override())

    def test_absent_voxtype_needs_no_process(self):
        with (
            patch.object(c.shutil, "which", return_value=None),
            patch.object(c.subprocess, "run") as run,
        ):
            self.assertEqual(c.probe_voxtype(), "not-installed")
            self.assertFalse(c.native_hotkey_conflict())
            c.require_available("not-installed")
            run.assert_not_called()

    def test_native_status_states_and_bounded_read_only_command(self):
        for state in sorted(c.BUSY_STATES | {"idle", "stopped"}):
            with (
                self.subTest(state=state),
                patch.object(c.shutil, "which", return_value="/usr/bin/voxtype"),
                patch.object(c, "config_override", return_value=None),
                patch.object(
                    c.subprocess,
                    "run",
                    return_value=Mock(returncode=0, stdout=state + "\n"),
                ) as run,
            ):
                self.assertEqual(c.probe_voxtype(), state)
                self.assertEqual(
                    run.call_args.args[0],
                    ["/usr/bin/voxtype", "status", "--format", "text"],
                )
                self.assertEqual(run.call_args.kwargs["timeout"], 1)
                if state in c.BUSY_STATES:
                    with self.assertRaises(ValueError):
                        c.require_available(state)
                else:
                    c.require_available(state)

    def test_failure_and_unknown_stdout_are_sanitized_and_fail_closed(self):
        cases = [
            Mock(returncode=1, stdout="secret-key transcript"),
            Mock(returncode=0, stdout="future-protocol"),
            subprocess.TimeoutExpired("voxtype", 1),
            OSError("secret-key"),
        ]
        for case in cases:
            with (
                self.subTest(case=type(case).__name__),
                patch.object(c.shutil, "which", return_value="voxtype"),
                patch.object(c, "config_override", return_value=None),
                patch.object(c.subprocess, "run") as run,
            ):
                if isinstance(case, Exception):
                    run.side_effect = case
                else:
                    run.return_value = case
                state = c.probe_voxtype()
                self.assertEqual(state, "unknown")
                with self.assertRaises(ValueError) as error:
                    c.require_available(state)
                self.assertNotIn("secret-key", str(error.exception))

    def test_daemon_custom_config_used_for_native_status(self):
        with (
            patch.object(c.shutil, "which", return_value="voxtype"),
            patch.object(
                c, "config_override", return_value=Path("/private/voice.toml")
            ),
            patch.object(
                c.subprocess, "run", return_value=Mock(returncode=0, stdout="idle")
            ) as run,
        ):
            self.assertEqual(c.probe_voxtype(), "idle")
            self.assertEqual(
                run.call_args.args[0][1:3], ["--config", "/private/voice.toml"]
            )

    def test_native_evdev_config_conflicts_and_disabled_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            for body, expected in [
                ('[hotkey]\nkey="RIGHTALT"\n', True),
                ('[hotkey]\nkey="RIGHTALT"\nenabled=false\n', False),
                ('[hotkey]\nkey="SCROLLLOCK"\n', False),
                ("[hotkey]\nenabled=false\n", False),
                ('state_file="auto"\n', False),
            ]:
                with (
                    self.subTest(body=body),
                    patch.object(c.shutil, "which", return_value="voxtype"),
                    patch.object(c, "config_override", return_value=path),
                ):
                    path.write_text(body)
                    self.assertEqual(c.native_hotkey_conflict(), expected)
                    self.assertEqual(path.read_text(), body)

    def test_invalid_native_config_is_not_overwritten_or_exposed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            body = "invalid config with secret-key"
            path.write_text(body)
            with (
                patch.object(c.shutil, "which", return_value="voxtype"),
                patch.object(c, "config_override", return_value=path),
            ):
                with self.assertRaises(ValueError) as error:
                    c.native_hotkey_conflict()
                self.assertNotIn("secret-key", str(error.exception))
                self.assertEqual(path.read_text(), body)

    def test_installer_conflict_stops_before_writes_or_services(self):
        spec = importlib.util.spec_from_file_location(
            "coe_installer", Path(__file__).resolve().parents[1] / "scripts/install.py"
        )
        installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(installer)
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "not-created"
            with (
                patch.object(installer, "DATA", data),
                patch.object(sys, "argv", ["install.py"]),
                patch.object(installer.shutil, "which", return_value="/mock/tool"),
                patch.object(installer.hotkey, "conflict", return_value=True),
                patch.object(installer.subprocess, "run") as run,
            ):
                with self.assertRaisesRegex(SystemExit, "未更改官方语音输入"):
                    installer.main()
                self.assertFalse(data.exists())
                run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
