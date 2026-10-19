#!/usr/bin/env python3
"""Restore the pre-OSD plugin/core/binary. Profiles, keys and bindings stay intact."""

from pathlib import Path
import subprocess
import sys

backups = sorted(
    (Path.home() / ".local/share/omarchy-coe-enhance/osd-backups").glob(
        "*/manifest.json"
    )
)
if not backups:
    raise SystemExit("找不到 OSD 部署前备份")
backup = Path(sys.argv[1]) if len(sys.argv) > 1 else backups[-1].parent
raise SystemExit(
    subprocess.call(
        [
            sys.executable,
            str(Path(__file__).with_name("rollback-performance.py")),
            str(backup),
        ]
    )
)
