#!/usr/bin/env python3
"""Opt-in: reapply unchanged ASR, toggle LLM on/off without submitting audio."""

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import coe_config as config
from ui_live import run, show, focus, key, inspect, rpc, EVIDENCE


def ready():
    for _ in range(100):
        state = json.loads(run("omarchy-shell", "cc.coe-enhance", "status"))
        if not state["busy"] and state["state"] == "idle":
            return
        time.sleep(0.05)
    raise AssertionError("Timed out applying settings")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reapply-current", action="store_true", required=True)
    parser.parse_args()
    assert not config.read_store()["llm"]["enabled"], "Test requires LLM initially off"
    assert len(config.active_profile()["name"]) < 80
    paths = [config.CONFIG, config.ENV, config.STORE, config.ROOT / "last-good.yaml"]
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    ime = run("fcitx5-remote")
    report = {}
    run("fcitx5-remote", "-c")
    try:
        show("asr")
        focus("配置名称")
        key("-k", "End")
        key(" ")
        key("-k", "Tab")
        assert inspect()["dirty"]
        focus("保存并应用")
        key("-k", "Return")
        ready()
        assert not inspect()["dirty"] and not inspect()["feedbackError"]
        report["save_apply_same_profile_normalized_whitespace"] = True
        show("home")
        focus("AI 文本纠错开关")
        key("-k", "Return")
        ready()
        assert (
            config.read_store()["llm"]["enabled"]
            and config.yaml_load()[1]["llm"]["provider"] == "openai"
        )
        focus("AI 文本纠错开关")
        key("-k", "Return")
        ready()
        assert (
            not config.read_store()["llm"]["enabled"]
            and config.yaml_load()[1]["llm"]["provider"] == "stub"
        )
        report["llm_toggle_real_backend_on_then_off"] = True
        report["cloud_requests"] = 0
    finally:
        if config.read_store()["llm"]["enabled"]:
            rpc("preferences", llm_enabled=False)
        run("omarchy-shell", "shell", "hide", "cc.coe-enhance")
        if ime == "2":
            run("fcitx5-remote", "-o")
        report["all_user_config_bytes_unchanged"] = all(
            hashlib.sha256(p.read_bytes()).hexdigest() == h for p, h in before.items()
        )
        (EVIDENCE / "ui-apply.json").write_text(json.dumps(report, indent=2) + "\n")
    assert report["all_user_config_bytes_unchanged"]
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
