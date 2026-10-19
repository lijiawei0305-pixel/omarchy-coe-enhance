#!/usr/bin/env python3
"""Own the unmodified GTK4 frontend and its private, activation-free session bus.

No rendering, microphone access, transcript or credentials belong in this host.
"""

import argparse
import ctypes
import fcntl
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
from xml.sax.saxutils import escape


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--parent", type=int, required=True)
    ap.add_argument("--socket", type=Path, required=True)
    ap.add_argument("--binary", type=Path, required=True)
    args = ap.parse_args()
    os.umask(0o077)
    libc = ctypes.CDLL(None, use_errno=True)

    # The host has no threads. Children arm their own death signal before exec.
    def death_signal(parent, sig):
        if libc.prctl(1, int(sig), 0, 0, 0) != 0 or os.getppid() != parent:
            os._exit(1)

    def terminate(*_):
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, terminate)
    signal.signal(signal.SIGINT, terminate)
    death_signal(args.parent, signal.SIGTERM)
    runtime = args.socket.parent
    runtime.mkdir(mode=0o700, parents=True, exist_ok=True)
    st = runtime.lstat()
    if (
        not runtime.is_dir()
        or runtime.is_symlink()
        or st.st_uid != os.getuid()
        or st.st_mode & 0o077
    ):
        return 1
    lock = os.open(runtime / "host.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return 1
    # Only display/session/theme variables; never forward API credentials.
    env = {
        k: v
        for k, v in os.environ.items()
        if k
        in (
            "HOME",
            "USER",
            "LOGNAME",
            "PATH",
            "LANG",
            "XDG_CONFIG_HOME",
            "XDG_DATA_DIRS",
            "XDG_CURRENT_DESKTOP",
            "XDG_SESSION_TYPE",
            "GDK_BACKEND",
            "GDK_SCALE",
            "GDK_DPI_SCALE",
            "GTK_THEME",
            "HYPRLAND_INSTANCE_SIGNATURE",
        )
        or k.startswith("LC_")
    }
    display = os.environ.get("WAYLAND_DISPLAY", "wayland-0")
    if not display.startswith("/"):
        display = str(Path(os.environ["XDG_RUNTIME_DIR"]) / display)
    env.update(
        WAYLAND_DISPLAY=display,
        XDG_RUNTIME_DIR=str(runtime),
        GTK_A11Y="none",
        NO_AT_BRIDGE="1",
        RUST_LOG="error",
    )
    config = runtime / "bus.conf"
    bus_path = runtime / "session-bus"
    # A SIGKILL can leave our private bus socket behind. The lifetime lock
    # proves no other host owns it; refuse replacing any unrelated file.
    if bus_path.exists() or bus_path.is_symlink():
        st = bus_path.lstat()
        import stat

        if st.st_uid != os.getuid() or not stat.S_ISSOCK(st.st_mode):
            return 1
        bus_path.unlink()
    config.write_text(
        """<busconfig><type>session</type><listen>unix:path="""
        + escape(str(bus_path))
        + """</listen>
<auth>EXTERNAL</auth><policy context="default"><allow send_destination="*"/>
<allow receive_sender="*"/><allow own="*"/></policy></busconfig>"""
    )
    os.chmod(config, 0o600)
    children = []
    parent = os.getpid()

    def child_setup():
        death_signal(parent, signal.SIGKILL)

    try:
        bus = subprocess.Popen(
            [
                "dbus-daemon",
                "--nofork",
                "--config-file=" + str(config),
                "--print-address=1",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=env,
            preexec_fn=child_setup,
        )
        children.append(bus)
        if not select.select([bus.stdout], [], [], 3)[0]:
            return 1
        address = bus.stdout.readline().decode().strip()
        if not address.startswith("unix:"):
            return 1
        os.chmod(bus_path, 0o600)
        env["DBUS_SESSION_BUS_ADDRESS"] = address
        # Reuse the user's original Voxtype OSD style/theme settings, read-only.
        gtk = subprocess.Popen(
            [str(args.binary), "--socket", str(args.socket), "--log-every", "0"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
            preexec_fn=child_setup,
        )
        children.append(gtk)
        return gtk.wait()
    finally:
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
        for path in (bus_path, config):
            path.unlink(missing_ok=True)
        os.close(lock)


if __name__ == "__main__":
    sys.exit(main())
