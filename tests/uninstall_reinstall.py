#!/usr/bin/env python3
"""Opt-in: remove/redeploy only this plugin, assert all credentials/config survive."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from live_e2e import rpc, ROOT


def run(args):
    return subprocess.run(
        args, capture_output=True, text=True, check=True, timeout=30
    ).stdout


def pid():
    return run(
        ["systemctl", "--user", "show", "coe.service", "-p", "MainPID", "--value"]
    ).strip()


assert rpc("get")["state"] == "idle"
paths = [
    Path.home() / ".config/coe/config.yaml",
    Path.home() / ".config/coe/env",
    Path.home() / ".config/omarchy-coe-enhance/profiles.json",
]
before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
original_pid = pid()
run([sys.executable, "-B", str(ROOT / "scripts/uninstall.py")])
assert not (Path.home() / ".config/omarchy/plugins/cc.coe-enhance").exists()
assert not (Path(os.environ["XDG_RUNTIME_DIR"]) / "coe-enhance/bridge.sock").exists()
assert not any(
    b.get("description") == "Coe Enhance 语音输入"
    for b in json.loads(run(["hyprctl", "-j", "binds"]))
)
assert pid() == original_pid
assert before == {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
run([sys.executable, "-B", str(ROOT / "scripts/deploy.py")])
for _ in range(80):
    try:
        if rpc("get")["state"] == "idle":
            break
    except (OSError, RuntimeError):
        pass
    time.sleep(0.1)
else:
    raise AssertionError("Bridge failed to recover after reinstall")
assert pid() == original_pid
assert before == {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
report = {
    "uninstall": "PASS: own plugin/binding/socket removed",
    "user_data": "PASS: config/env/Profiles byte-identical",
    "coe": "PASS: same service PID",
    "reinstall": "PASS: existing Shell restored widget/bridge, idle",
}
(ROOT / ".runtime/uninstall.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=2) + "\n"
)
print(json.dumps(report, ensure_ascii=False, indent=2))
