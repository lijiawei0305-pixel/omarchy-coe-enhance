import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import coe_perf


class PerfTests(unittest.TestCase):
    def test_private_bounded_metadata_only(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "trace"
            with patch.dict(os.environ, COE_PERF_TRACE=str(p)):
                coe_perf.mark("session", "T7", duration_ms=1.5)
                self.assertEqual(p.stat().st_mode & 0o777, 0o600)
                before = p.read_bytes()
                coe_perf.mark("session", "private", body="private-text")
                self.assertEqual(before, p.read_bytes())
                link = Path(t) / "link"
                link.symlink_to(p)
                with patch.dict(os.environ, COE_PERF_TRACE=str(link)):
                    coe_perf.mark("s", "bad")
                self.assertEqual(before, p.read_bytes())
                p.chmod(0o644)
                coe_perf.mark("s", "bad")
                self.assertEqual(before, p.read_bytes())
                p.chmod(0o600)
                with p.open("wb") as f:
                    f.truncate(10 * 1024 * 1024)
                coe_perf.mark("s", "bad")
                self.assertEqual(p.stat().st_size, 10 * 1024 * 1024)
