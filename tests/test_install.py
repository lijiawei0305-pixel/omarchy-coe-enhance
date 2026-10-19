import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_backend as build

spec = importlib.util.spec_from_file_location(
    "public_installer", Path(__file__).resolve().parents[1] / "scripts/install.py"
)
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class InstallationTests(unittest.TestCase):
    def test_build_refuses_output_overlapping_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            source.mkdir()
            for output in (source, source / "build", source.parent):
                with self.subTest(output=output), patch.object(build, "run") as run:
                    with self.assertRaisesRegex(ValueError, "outside"):
                        build.build_backend(output, "/fake/go", plugin_source=source)
                    run.assert_not_called()

    def test_missing_go_does_not_create_build_directory(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(build, "run") as run:
            output = Path(tmp) / "not-created"
            with self.assertRaisesRegex(ValueError, "Go is required"):
                build.build_backend(output, None)
            self.assertFalse(output.exists())
            run.assert_not_called()

    def test_installer_rejects_source_inside_deployment(self):
        with (
            patch.object(sys, "argv", ["install.py"]),
            patch.object(installer.shutil, "which", return_value="/mock/tool"),
            patch.object(installer.hotkey, "conflict", return_value=False),
            patch.object(installer, "PLUGIN", installer.SOURCE),
            patch.object(installer, "build_backend") as build_call,
        ):
            with self.assertRaisesRegex(SystemExit, "源码克隆到插件目录之外"):
                installer.main()
            build_call.assert_not_called()

    def test_unknown_coe_unit_is_preserved_before_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            unit = home / ".config/systemd/user/coe.service"
            unit.parent.mkdir(parents=True)
            original = "[Service]\nExecStart=/other/coe serve\n"
            unit.write_text(original)
            with (
                patch.object(sys, "argv", ["install.py"]),
                patch.object(installer.shutil, "which", return_value="/mock/tool"),
                patch.object(installer.hotkey, "conflict", return_value=False),
                patch.object(installer, "HOME", home),
                patch.object(installer, "DATA", home / "not-created"),
                patch.object(installer, "build_backend") as build_call,
            ):
                with self.assertRaisesRegex(SystemExit, "已有其他 coe.service"):
                    installer.main()
                self.assertEqual(unit.read_text(), original)
                self.assertFalse(installer.DATA.exists())
                build_call.assert_not_called()


if __name__ == "__main__":
    unittest.main()
