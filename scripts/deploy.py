#!/usr/bin/env python3
from pathlib import Path
import shutil
import subprocess
import tempfile
from package_plugin import version_qml

root = Path(__file__).resolve().parent.parent
destination = Path.home() / ".config/omarchy/plugins/cc.coe-enhance"
subprocess.run(["omarchy", "plugin", "validate", str(root)], check=True)
subprocess.run(["python3", str(root / "scripts/lint.py")], check=True)
# Disable destroys the one bridge and removes its own hotkey before files change.
if destination.exists():
    subprocess.run(["omarchy", "plugin", "disable", "cc.coe-enhance"], check=True)
with tempfile.TemporaryDirectory(prefix="coe-deploy-") as t:
    stage = Path(t) / "plugin"
    shutil.copytree(
        root,
        stage,
        ignore=shutil.ignore_patterns(
            ".git", ".runtime", "__pycache__", "test-results", ".ruff_cache"
        ),
    )
    version_qml(stage)
    subprocess.run(["omarchy", "plugin", "validate", str(stage)], check=True)
    if destination.exists():
        shutil.rmtree(destination)
    shutil.move(stage, destination)
subprocess.run(["omarchy-shell", "shell", "rescanPlugins"], check=True)
subprocess.run(
    ["omarchy", "plugin", "enable", "cc.coe-enhance", "--section", "right"], check=True
)

# Registry rescan and Loader completion are asynchronous. Wait for the actual
# bridge handshake before reporting a successful deployment.
import json
import time

for _ in range(100):
    result = subprocess.run(
        ["omarchy-shell", "cc.coe-enhance", "status"], capture_output=True, text=True
    )
    try:
        if result.returncode == 0 and json.loads(result.stdout).get("connected"):
            break
    except ValueError:
        pass
    time.sleep(0.1)
else:
    raise SystemExit("插件已复制，但桥接层未就绪，请检查 Shell 日志。")
