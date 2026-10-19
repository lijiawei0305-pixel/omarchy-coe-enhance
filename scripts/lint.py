#!/usr/bin/env python3
"""Qt 6 lint with Quickshell's qs namespace mapped as at runtime."""

from pathlib import Path
import json
import subprocess
import sys
import tempfile

root = (
    Path(sys.argv[1]).resolve()
    if len(sys.argv) > 1
    else Path(__file__).resolve().parent.parent
)
manifest = json.loads((root / "manifest.json").read_text())
widget = root / manifest["entryPoints"]["barWidget"]
panel = widget.parent.parent / "CoePanel.qml"
with tempfile.TemporaryDirectory(prefix="coe-qmllint-") as tmp:
    (Path(tmp) / "qs").symlink_to("/usr/share/omarchy/shell", target_is_directory=True)
    # Installed Color/Style expose QObject properties and Loader.item is dynamic.
    # Quickshell's qmltypes also omit QProcess::ExitStatus. Disable only these two
    # metadata categories; syntax, import, type, property override etc remain checked.
    result = subprocess.run(
        [
            "/usr/lib/qt6/bin/qmllint",
            "-I",
            tmp,
            "-I",
            "/usr/share/omarchy/shell",
            "--missing-property",
            "disable",
            "--signal-handler-parameters",
            "disable",
            str(widget),
            str(panel),
        ]
    )
    raise SystemExit(result.returncode)
