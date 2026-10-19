import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from coe_osd import Osd


class OsdTests(unittest.TestCase):
    def setUp(self):
        # Unit tests must not depend on Voxtype being installed on the host.
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.binary = Path(tmp.name) / "voxtype-osd-gtk4"
        self.binary.touch()
        executable = patch(
            "coe_osd.shutil.which",
            side_effect=lambda command: (
                str(self.binary)
                if command == "voxtype-osd-gtk4"
                else "/usr/bin/dbus-daemon"
            ),
        )
        enabled = patch.dict("os.environ", {"COE_ENHANCE_OSD": "1"})
        for fixture in (executable, enabled):
            fixture.start()
            self.addCleanup(fixture.stop)

    def test_private_socket_and_single_owned_host(self):
        with tempfile.TemporaryDirectory() as d:
            o = Osd(d)
            process = Mock()
            process.poll.return_value = None
            with patch("coe_osd.subprocess.Popen", return_value=process) as p:
                o.start()
                o.start()
                self.assertEqual(p.call_count, 1)
                self.assertIn(str(Path(d) / "osd/audio.sock"), p.call_args.args[0])
                self.assertNotIn("record", p.call_args.args[0])
                o.close()
                process.terminate.assert_called_once()

    def test_bounded_restarts(self):
        o = Osd("/tmp/unused-osd-test")
        p = Mock()
        p.poll.return_value = 1
        with patch("coe_osd.subprocess.Popen", return_value=p) as start:
            for _ in range(10):
                o.start()
            self.assertEqual(start.call_count, 3)

    def test_closed_host_cannot_restart(self):
        o = Osd("/tmp/unused-osd-test")
        o.close()
        with patch("coe_osd.subprocess.Popen") as start:
            o.start()
            start.assert_not_called()

    def test_disabled(self):
        o = Osd("/tmp/unused-osd-test")
        with (
            patch.dict("os.environ", {"COE_ENHANCE_OSD": "0"}),
            patch("coe_osd.subprocess.Popen") as p,
        ):
            o.start()
            p.assert_not_called()

    def test_missing_optional_dependencies_skip_visual_process(self):
        for missing in ("binary", "dbus"):
            with (
                self.subTest(missing=missing),
                patch("coe_osd.Path.is_file", return_value=missing != "binary"),
                patch("coe_osd.shutil.which", return_value=None),
                patch("coe_osd.subprocess.Popen") as start,
            ):
                Osd("/tmp/unused-osd-test").start()
                start.assert_not_called()


if __name__ == "__main__":
    unittest.main()
