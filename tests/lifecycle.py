#!/usr/bin/env python3
"""Live lifecycle checks; changes only this plugin and the idle Coe service."""

import json
import os
from pathlib import Path
import socket
import subprocess
import time

R = Path(os.environ["XDG_RUNTIME_DIR"]) / "coe-enhance/bridge.sock"


def run(args):
    return subprocess.run(
        args, capture_output=True, text=True, check=True, timeout=8
    ).stdout.strip()


def state():
    try:
        with socket.socket(socket.AF_UNIX) as s:
            s.settimeout(2)
            s.connect(str(R))
            s.sendall(b'{"action":"get"}\n')
            data = b""
            while b"\n" not in data:
                chunk = s.recv(65536)
                if not chunk:
                    raise ConnectionError("Bridge closed before complete response")
                data += chunk
            return json.loads(data)["state"]
    except OSError:
        return "bridge-offline"


def wait_for(wanted):
    for _ in range(70):
        if state() == wanted:
            return
        time.sleep(0.1)
    raise AssertionError((state(), wanted))


def bindings():
    return [
        b
        for b in json.loads(run(["hyprctl", "-j", "binds"]))
        if b.get("description") in ("Coe Enhance 语音输入", "Coe Enhance 松开识别")
    ]


def pid():
    return run(
        ["systemctl", "--user", "show", "coe.service", "-p", "MainPID", "--value"]
    )


report = {}
assert state() == "idle"
original = pid()
for _ in range(2):
    run(["omarchy", "plugin", "disable", "cc.coe-enhance"])
time.sleep(1.5)
assert not bindings()
assert not R.exists()
assert pid() == original
report["disable_twice"] = "PASS: binding/socket removed, Coe PID unchanged"
for _ in range(2):
    run(["omarchy", "plugin", "enable", "cc.coe-enhance", "--section", "right"])
wait_for("idle")
mode = json.loads(
    (Path.home() / ".config/omarchy-coe-enhance/profiles.json").read_text()
).get("hotkey_mode", "toggle")
assert len(bindings()) == (2 if mode == "hold" else 1)
layout = json.loads((Path.home() / ".config/omarchy/shell.json").read_text())["bar"][
    "layout"
]
assert sum(r["id"] == "cc.coe-enhance" for rows in layout.values() for r in rows) == 1
report["enable_twice"] = (
    "PASS: exactly one widget and the expected owned press/release bindings"
)
run(["omarchy-shell", "shell", "rescanPlugins"])
wait_for("idle")
assert pid() == original
report["shell_reload"] = (
    "PASS: existing Shell reload, Coe PID unchanged, bridge restored"
)
run(["systemctl", "--user", "stop", "coe.service"])
wait_for("offline")
run(["systemctl", "--user", "start", "coe.service"])
wait_for("idle")
report["stop_start"] = "PASS: offline -> idle synchronized by D-Bus"
before_crash = pid()
run(["systemctl", "--user", "kill", "--signal=SIGKILL", "coe.service"])
time.sleep(0.3)
wait_for("idle")
assert pid() != before_crash
report["crash_recovery"] = "PASS: systemd restart and D-Bus reconnect"
report["autostart"] = run(["systemctl", "--user", "is-enabled", "coe.service"])
report["hyprland_configerrors"] = run(["hyprctl", "configerrors"])
print(json.dumps(report, ensure_ascii=False, indent=2))
(Path(__file__).resolve().parents[1] / "docs/evidence/ui-lifecycle.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=2) + "\n"
)
