"""Manage the original Voxtype recording waveform. No status popups or capture."""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading


class Osd:
    def __init__(self, runtime):
        self.runtime = Path(runtime) / "osd"
        self.process = None
        self.attempts = 0
        self.stopped = threading.Event()

    def start(self):
        if self.stopped.is_set() or os.environ.get("COE_ENHANCE_OSD") == "0":
            return
        if self.process is not None and self.process.poll() is None:
            return
        # At most three attempts per bridge lifetime (maintain runs every 10 s).
        if self.attempts >= 3:
            return
        self.attempts += 1
        binary = shutil.which("voxtype-osd-gtk4") or "/usr/lib/voxtype/voxtype-osd-gtk4"
        if not Path(binary).is_file() or not shutil.which("dbus-daemon"):
            return
        try:
            self.process = subprocess.Popen(
                [
                    sys.executable,
                    "-B",
                    str(Path(__file__).with_name("coe_osd_host.py")),
                    "--parent",
                    str(os.getpid()),
                    "--socket",
                    str(self.runtime / "audio.sock"),
                    "--binary",
                    binary,
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            pass

    def available(self):
        return self.process is not None and self.process.poll() is None

    def close(self):
        self.stopped.set()
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
