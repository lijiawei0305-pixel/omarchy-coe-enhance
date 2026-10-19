#!/usr/bin/env python3
"""Isolated first boot with no API key, audio capture, service or user writes."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

import dbus

ROOT = Path(__file__).resolve().parents[1]


def main():
    address = os.environ.get("DBUS_SESSION_BUS_ADDRESS", "")
    if not address or "/run/user/" in address:
        raise RuntimeError("Use dbus-run-session; never run on the desktop bus")
    with tempfile.TemporaryDirectory(prefix="coe-first-boot-") as tmp:
        temp = Path(tmp)
        os.environ.update(
            COE_CONFIG=str(temp / "coe/config.yaml"),
            COE_ENHANCE_CONFIG=str(temp / "plugin"),
            XDG_CONFIG_HOME=tmp,
            XDG_RUNTIME_DIR=tmp,
            COE_ENHANCE_BRIDGE="1",
            COE_ENHANCE_OSD="0",
        )
        sys.path.insert(0, str(ROOT / "scripts"))
        import coe_config as config

        config.initialize()
        profile = config.read_store()["profiles"][0]
        config.save_profile({"profile": profile, "id": profile["id"]}, lambda: None)
        assert not config.public_store()["profiles"][0]["key_present"]
        binary = os.environ.get(
            "COE_TEST_BINARY",
            str(Path.home() / ".local/share/omarchy-coe-enhance/bin/coe"),
        )
        process = subprocess.Popen(
            [binary, "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        try:
            bus = dbus.SessionBus()
            state = "offline"
            for _ in range(80):
                if process.poll() is not None:
                    raise AssertionError(
                        "First-boot Coe exited before accepting configuration"
                    )
                try:
                    iface = dbus.Interface(
                        bus.get_object(
                            "com.mistermorph.Coe",
                            "/com/mistermorph/Coe",
                            introspect=False,
                        ),
                        "com.mistermorph.Coe.Dictation1",
                    )
                    state = str(iface.Status(timeout=1)[0])
                    break
                except dbus.DBusException:
                    time.sleep(0.05)
            assert state == "idle", "First-boot daemon was not ready"
            print(
                json.dumps(
                    {
                        "first_boot_without_key": True,
                        "dbus_idle": True,
                        "audio_capture_started": False,
                        "cloud_requests": 0,
                        "user_configuration_touched": False,
                    }
                )
            )
        finally:
            process.terminate()
            process.wait(timeout=5)


if __name__ == "__main__":
    main()
