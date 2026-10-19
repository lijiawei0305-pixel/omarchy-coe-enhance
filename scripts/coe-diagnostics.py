#!/usr/bin/env python3
"""Sanitized diagnostics; never dump config/env, remote errors or transcripts."""

import json
from pathlib import Path
import shutil
import socket
import stat
import subprocess
import os
import coe_compat as compat


def output(cmd):
    try:
        return subprocess.run(
            cmd, capture_output=True, text=True, timeout=4
        ).stdout.strip()
    except Exception:
        return "unavailable"


root = Path.home()
r = {
    "commands": {
        x: bool(shutil.which(x))
        for x in ("pw-record", "wl-copy", "wl-paste", "hyprctl", "fcitx5-remote", "qs")
    },
    "omarchy": output(["omarchy", "version"]),
    "quickshell": output(["quickshell", "--version"]),
    "coe": output([str(root / ".local/share/omarchy-coe-enhance/bin/coe"), "version"]),
    "service": output(["systemctl", "--user", "is-active", "coe.service"]),
    "autostart": output(["systemctl", "--user", "is-enabled", "coe.service"]),
    "rime_state": output(["fcitx5-remote"]),
}
env = root / ".config/coe/env"
r["env_mode"] = oct(stat.S_IMODE(env.stat().st_mode)) if env.exists() else "missing"
r["voxtype_state"] = compat.probe_voxtype()
try:
    r["voxtype_native_right_alt_conflict"] = compat.native_hotkey_conflict()
except ValueError:
    r["voxtype_native_right_alt_conflict"] = "unknown"
try:
    with socket.socket(socket.AF_UNIX) as s:
        s.settimeout(4)
        s.connect(os.environ["XDG_RUNTIME_DIR"] + "/coe-enhance/bridge.sock")
        s.sendall(b'{"action":"get"}\n')
        data = b""
        while b"\n" not in data:
            chunk = s.recv(65536)
            if not chunk:
                raise ConnectionError("Bridge closed before complete response")
            data += chunk
        b = json.loads(data)
        r.update(
            dbus_state=b["state"],
            bridge=b.get("diagnostics", {}),
            hotkey=b.get("store", {}).get("hotkey"),
            active_profile=b.get("store", {}).get("active"),
            error=b.get("error", ""),
            hotkey_error=b.get("hotkey_error", ""),
        )
except Exception:
    r["bridge"] = "offline"
print(json.dumps(r, ensure_ascii=False, indent=2))
