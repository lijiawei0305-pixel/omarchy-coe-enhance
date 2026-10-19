"""Small hotkey RPC client: no YAML, D-Bus, GI or daemon initialization."""

import json
import os
from pathlib import Path
import socket
import sys


def main(argv=None):
    argv = argv or sys.argv[1:]
    if len(argv) == 5 and argv[0] == "hold":
        req = dict(
            action="hold", owner=argv[1], gesture=argv[2] + ":" + argv[4], event=argv[3]
        )
    elif argv and argv[0] == "json":
        req = json.load(sys.stdin)
    else:
        req = {"action": argv[1] if len(argv) > 1 else "get"}
    # Kernel-wide monotonic timestamp, harmless and never user content.
    import time

    req["client_started_ns"] = time.monotonic_ns()
    path = (
        Path(os.environ.get("XDG_RUNTIME_DIR", "/run/user/" + str(os.getuid())))
        / "coe-enhance/bridge.sock"
    )
    try:
        with socket.socket(socket.AF_UNIX) as c:
            c.settimeout(660)
            c.connect(str(path))
            c.sendall((json.dumps(req) + "\n").encode())
            data = bytearray()
            while b"\n" not in data:
                chunk = c.recv(65536)
                if not chunk:
                    raise OSError("incomplete response")
                data.extend(chunk)
                if len(data) > 1024 * 1024:
                    raise OSError("response too large")
            print(data.decode().strip())
        return 0
    except OSError:
        print(
            json.dumps(
                {"ok": False, "error": "插件未启用或桥接层未连接"}, ensure_ascii=False
            )
        )
        return 1
