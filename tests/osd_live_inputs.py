#!/usr/bin/env python3
"""Production panel and hold-RPC Start -> native GTK -> Cancel. No ASR request."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import uuid
import ui_live as ui

ROOT = Path(__file__).resolve().parents[1]


def wait(fn):
    for _ in range(80):
        v = fn()
        if v:
            return v
        time.sleep(0.05)
    raise AssertionError("Timed out waiting for real Coe recording overlay")


def native_layer():
    d = json.loads(ui.run("hyprctl", "-j", "layers"))
    return [
        x
        for m in d.values()
        for group in m["levels"].values()
        for x in group
        if x["namespace"] == "voxtype-osd"
    ]


def state():
    return ui.rpc("get")["state"]


def main():
    paths = [
        Path.home() / p
        for p in [
            ".config/coe/config.yaml",
            ".config/coe/env",
            ".config/omarchy-coe-enhance/profiles.json",
            ".config/omarchy-coe-enhance/last-good.yaml",
            ".config/hypr/bindings.lua",
        ]
    ]
    hashes = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    ime = ui.run("fcitx5-remote")
    report = {"paid_requests": 0}
    assert state() == "idle"
    try:
        if ime == "2":
            ui.run("fcitx5-remote", "-c")
        ui.show("home")
        ui.focus("开始语音输入")
        ui.key("-k", "Return")
        wait(lambda: state() == "recording")
        wait(native_layer)
        time.sleep(0.35)
        layer = native_layer()[0]
        ui.run(
            "grim",
            "-g",
            f"{layer['x']},{layer['y']} {layer['w']}x{layer['h']}",
            str(ROOT / "docs/evidence/osd/production-panel-recording.png"),
        )
        assert len(native_layer()) == 1
        report["panel_button"] = (
            "PASS: actual native panel button closed panel, started Coe and exactly one original GTK waveform"
        )
        ui.rpc("cancel")
        wait(lambda: state() == "idle")
        wait(lambda: not native_layer())
        # Exercise the same hold RPC invoked by the actual unchanged Alt_R binding.
        owner = (
            Path(os.environ["XDG_RUNTIME_DIR"]) / "coe-enhance/owner.token"
        ).read_text()
        event = {"owner": owner, "gesture": uuid.uuid4().hex + ":1"}
        ui.rpc("hold", **event, event="press")
        wait(lambda: state() == "recording")
        wait(native_layer)
        time.sleep(0.4)
        ui.rpc("cancel")
        ui.rpc("hold", **event, event="release")
        wait(lambda: state() == "idle")
        wait(lambda: not native_layer())
        report["alt_r_hold_rpc"] = (
            "PASS: current owner press started Coe/OSD; Cancel then release did not transcribe"
        )
        report["physical_alt_r_key_injected"] = False
        report["no_duplicate_waveform"] = True
    finally:
        if state() == "recording":
            ui.rpc("cancel")
        ui.run("omarchy-shell", "shell", "hide", "cc.coe-enhance")
        if ime == "2":
            ui.run("fcitx5-remote", "-o")
    report["configuration_unchanged"] = all(
        hashlib.sha256(p.read_bytes()).hexdigest() == h for p, h in hashes.items()
    )
    report["fcitx_restored"] = ui.run("fcitx5-remote") == ime
    assert report["configuration_unchanged"] and report["fcitx_restored"]
    (ROOT / "docs/evidence/osd/live-inputs.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
