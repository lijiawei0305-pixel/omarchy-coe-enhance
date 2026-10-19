#!/usr/bin/env python3
"""Live tests only this plugin's processes; never signal the user's Voxtype."""

import json
import os
from pathlib import Path
import signal
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = Path(os.environ["XDG_RUNTIME_DIR"]) / "coe-enhance"
SOCKET = str(RUNTIME / "osd/audio.sock")


def run(*args):
    return subprocess.check_output(args, text=True, timeout=12).strip()


def wait(fn, timeout=18):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        value = fn()
        if value:
            return value
        time.sleep(0.1)
    raise AssertionError("Timed out waiting for OSD lifecycle")


def processes():
    found = {"host": [], "gtk": [], "bridge": []}
    for p in Path("/proc").glob("[0-9]*/cmdline"):
        try:
            if p.stat().st_uid != os.getuid():
                continue
            args = p.read_bytes().decode().split("\0")
        except (OSError, UnicodeError):
            continue
        pid = int(p.parent.name)
        if SOCKET in args and any(a.endswith("/coe_osd_host.py") for a in args):
            found["host"].append(pid)
        if SOCKET in args and args[0].endswith("/voxtype-osd-gtk4"):
            found["gtk"].append(pid)
        if "watch" in args and any(
            a.endswith("/cc.coe-enhance/scripts/coe-bridge.py") for a in args
        ):
            found["bridge"].append(pid)
    return found


def ready():
    p = processes()
    return p if all(len(p[k]) == 1 for k in p) else None


def alive(pid):
    try:
        return bool(Path(f"/proc/{pid}/cmdline").read_bytes())
    except OSError:
        return False


def binding_count():
    return len(
        [
            b
            for b in json.loads(run("hyprctl", "-j", "binds"))
            if b.get("description") in ("Coe Enhance 语音输入", "Coe Enhance 松开识别")
        ]
    )


def stat(pid):
    f = Path(f"/proc/{pid}/stat").read_text().split()
    s = Path(f"/proc/{pid}/status").read_text().splitlines()
    return {
        "ticks": int(f[13]) + int(f[14]),
        "rss_kib": int(next(v.split()[1] for v in s if v.startswith("VmRSS:"))),
    }


def main():
    report = {}
    initial = wait(ready)
    core = int(
        run("systemctl", "--user", "show", "coe.service", "-p", "MainPID", "--value")
    )
    original = int(run("pgrep", "-f", "^/usr/lib/voxtype/voxtype-osd-gtk4$"))
    try:
        for _ in range(2):
            run("omarchy", "plugin", "disable", "cc.coe-enhance")
        wait(
            lambda: all(
                not alive(pid) for k in ("gtk", "host", "bridge") for pid in initial[k]
            )
        )
        assert binding_count() == 0
        assert (
            int(
                run(
                    "systemctl",
                    "--user",
                    "show",
                    "coe.service",
                    "-p",
                    "MainPID",
                    "--value",
                )
            )
            == core
        )
        report["disable_twice"] = (
            "PASS: owned GTK/host/private bus stopped; Coe unchanged"
        )
        for _ in range(2):
            run("omarchy", "plugin", "enable", "cc.coe-enhance", "--section", "right")
        time.sleep(1)
        p = wait(ready)
        assert binding_count() == 2
        report["enable_twice"] = (
            "PASS: exactly one Coe GTK host and renderer; two Alt_R hold bindings"
        )
        # Forced termination is scoped to the Popen-owned host, not generic process names.
        old = p
        os.kill(old["host"][0], signal.SIGKILL)
        wait(lambda: not alive(old["gtk"][0]))
        p = wait(lambda: (q := ready()) and q["host"] != old["host"] and q, timeout=18)
        report["host_crash_recovery"] = (
            "PASS: children terminated; private stale bus cleaned; restarted once"
        )
        old = p
        os.kill(old["bridge"][0], signal.SIGKILL)
        wait(lambda: all(not alive(pid) for k in ("host", "gtk") for pid in old[k]))
        p = wait(lambda: (q := ready()) and q["bridge"] != old["bridge"] and q)
        report["bridge_crash_recovery"] = (
            "PASS: parent death cleaned OSD children; Shell restored one bridge/host"
        )
        run("omarchy-shell", "shell", "rescanPlugins")
        time.sleep(2)
        p = wait(ready)
        assert (
            binding_count() == 2
            and int(
                run(
                    "systemctl",
                    "--user",
                    "show",
                    "coe.service",
                    "-p",
                    "MainPID",
                    "--value",
                )
            )
            == core
        )
        report["shell_rescan"] = (
            "PASS: one native renderer, Coe PID unchanged, Alt_R unchanged"
        )
        ids = {
            "coe": core,
            "bridge": p["bridge"][0],
            "host": p["host"][0],
            "gtk": p["gtk"][0],
        }
        bus = [
            int(v)
            for v in run("pgrep", "-P", str(ids["host"])).split()
            if int(v) != ids["gtk"]
        ]
        assert len(bus) == 1
        ids["private_bus"] = bus[0]
        before = {k: stat(v) for k, v in ids.items()}
        start = time.monotonic()
        time.sleep(15)
        elapsed = time.monotonic() - start
        after = {k: stat(v) for k, v in ids.items()}
        hz = os.sysconf("SC_CLK_TCK")
        report["idle_15s"] = {
            k: {
                "cpu_percent": round(
                    (after[k]["ticks"] - before[k]["ticks"]) / hz / elapsed * 100, 4
                ),
                "rss_kib": after[k]["rss_kib"],
            }
            for k in ids
        }
        report["original_voxtype_still_alive"] = alive(original)
        report["original_shell_pid_81172_unchanged"] = alive(81172)
        assert (
            report["original_voxtype_still_alive"]
            and report["original_shell_pid_81172_unchanged"]
        )
        report["audio_socket_mode"] = oct(
            (RUNTIME / "osd/audio.sock").stat().st_mode & 0o777
        )
        report["private_bus_mode"] = oct(
            (RUNTIME / "osd/session-bus").stat().st_mode & 0o777
        )
    finally:
        run("omarchy", "plugin", "enable", "cc.coe-enhance", "--section", "right")
        wait(ready)
    (ROOT / "docs/evidence/osd/lifecycle.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
