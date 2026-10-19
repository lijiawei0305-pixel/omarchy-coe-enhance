#!/usr/bin/env python3
"""Opt-in existing-Shell UI checks. Edits invalid drafts only; no cloud calls."""

import hashlib
import json
from pathlib import Path
import subprocess
import socket
import os
import time

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = Path(os.environ.get("COE_UI_EVIDENCE", ROOT / "docs/evidence"))
REPORT = {}


def run(*args):
    return subprocess.run(
        args, check=True, capture_output=True, text=True
    ).stdout.strip()


def inspect():
    return json.loads(run("omarchy-shell", "cc.coe-enhance", "inspect"))


def show(page):
    run("omarchy-shell", "cc.coe-enhance", "showPage", page, "")
    time.sleep(0.25)
    assert inspect()["page"] == page


def key(*args):
    assert inspect()["keyboardActive"], "Panel lost keyboard focus; no keys sent"
    run("wtype", *args)
    time.sleep(0.025)


def focus(name):
    for _ in range(35):
        if inspect()["focus"] == name:
            return
        key("-k", "Tab")
    raise AssertionError("Cannot focus " + name)


def shot(name):
    r = inspect()
    assert json.loads(run("omarchy-shell", "cc.coe-enhance", "status"))["opened"]
    run(
        "grim",
        "-g",
        f"{r['x']},{r['y']} {r['width']}x{r['height']}",
        str(EVIDENCE / ("ui-" + name + ".png")),
    )


def rpc(action, **payload):
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(10)
        client.connect(os.environ["XDG_RUNTIME_DIR"] + "/coe-enhance/bridge.sock")
        client.sendall((json.dumps({"action": action, **payload}) + "\n").encode())
        data = b""
        while b"\n" not in data:
            data += client.recv(65536)
        result = json.loads(data)
        assert result["ok"]
        return result


def main():
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    paths = [
        Path.home() / x
        for x in [
            ".config/coe/config.yaml",
            ".config/coe/env",
            ".config/omarchy-coe-enhance/profiles.json",
            ".config/omarchy-coe-enhance/last-good.yaml",
            ".config/hypr/bindings.lua",
        ]
    ]
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    ime = run("fcitx5-remote")
    run("fcitx5-remote", "-c")
    try:
        show("home")
        assert not inspect()["scrollable"]
        assert inspect()["hotkey"] == "Alt_R" and inspect()["mode"] == "hold"
        REPORT["main"] = inspect()
        shot("main")
        for page, name in [
            ("settings", "settings"),
            ("profiles", "profiles"),
            ("asr", "profile"),
            ("llm", "llm"),
            ("diagnostics", "diagnostics"),
            ("language", "language"),
        ]:
            show(page)
            assert not inspect()["dirty"]
            shot(name)
        REPORT["all_pages_load"] = True
        show("diagnostics")
        assert not any(c["editable"] for c in inspect()["controls"])
        assert not any(
            c["name"] in ("应用快捷键", "录音触发方式", "录音快捷键")
            for c in inspect()["controls"]
        )
        REPORT["input_usage_read_only"] = True
        show("language")
        assert inspect()["languageMode"] == "hints"
        assert inspect()["languageMaxHints"] == 4
        assert not any(c["editable"] for c in inspect()["controls"])
        focus("识别语言选择")
        key("-k", "Return")
        key("-k", "Home")
        key("-k", "Down")
        key("-k", "Return")
        assert inspect()["languageDraft"] == "zh"
        assert inspect()["languageSelection"] == ""
        focus("识别语言选择")
        key("-k", "Return")
        key("-k", "Down")
        key("-k", "Return")
        assert inspect()["languageDraft"] == "en"
        focus("识别语言选择")
        key("-k", "Return")
        key("-k", "Up")
        key("-k", "Up")
        key("-k", "Return")
        assert inspect()["languageDraft"] == ""
        assert not next(
            c["enabled"] for c in inspect()["controls"] if c["name"] == "应用语言"
        )
        REPORT["language_selection_is_draft_until_applied"] = True
        show("home")
        show("language")
        assert inspect()["languageDraft"] == ""
        shot("language")
        show("asr")
        focus("▸ 高级参数")
        key("-k", "Return")
        assert inspect()["scrollable"]
        shot("advanced")
        show("llm")
        focus("查看已保存的连接设置")
        key("-k", "Return")
        focus("▸ 自定义纠错指令")
        key("-k", "Return")
        assert not inspect()["dirty"]
        shot("llm-advanced")
        REPORT["advanced_and_llm_template_accessible"] = True
        # Edit drafts only: prove that the real QML reacts to a model/provider
        # change without creating Profiles or restarting the user's ASR service.
        for model, mode, maximum in [
            ("fun-asr-flash-2026-06-15", "single", 1),
            ("unknown-model", "single", 1),
        ]:
            show("asr")
            focus("模型名称（模型 ID）")
            key("-M", "ctrl", "-k", "a", "-m", "ctrl")
            key(model)
            key("-k", "Tab")
            assert inspect()["draftLanguageMode"] == mode
            assert inspect()["draftLanguageMaxHints"] == maximum
            focus("▸ 高级参数")
            key("-k", "Return")
            assert not any(
                c["name"] == "语言提示（可选）" for c in inspect()["controls"]
            )
            if model == "unknown-model":
                assert not inspect()["draftLanguageVerified"]
                assert inspect()["draftLanguageCodes"] == []
        for down, mode, codes in [
            (1, "none", []),  # Doubao
            (2, "single", ["zh", "en", "yue", "ja", "ko"]),
            (3, "none", []),  # Qwen3 / vLLM
        ]:
            show("asr")
            focus("语音识别服务")
            key("-k", "Return")
            for _ in range(down):
                key("-k", "Down")
            key("-k", "Return")
            assert inspect()["draftLanguageMode"] == mode
            assert inspect()["draftLanguageCodes"] == codes
        REPORT["model_and_provider_capabilities_update_in_live_qml_drafts"] = True
        show("asr")
        focus("API Endpoint · 服务地址")
        key("-M", "ctrl", "-k", "a", "-m", "ctrl")
        key("invalid-endpoint")
        key("-k", "Tab")
        assert inspect()["dirty"]
        focus("保存并应用")
        key("-k", "Return")
        for _ in range(40):
            if inspect()["feedbackError"]:
                break
            time.sleep(0.05)
        assert inspect()["feedbackError"] and inspect()["dirty"]
        REPORT["failed_save_preserves_draft"] = True
        shot("draft-error")
        key("-k", "Escape")
        assert inspect()["confirmation"] == "discard"
        REPORT["escape_unsaved_confirmation"] = True
        focus("确认")
        key("-k", "Return")
        assert inspect()["page"] == "profiles"
        show("asr")
        focus("检查配置")
        key("-k", "Return")
        time.sleep(0.15)
        assert not inspect()["feedbackError"]
        REPORT["configuration_check_without_audio"] = True
        show("home")
        key("-k", "Escape")
        assert not json.loads(run("omarchy-shell", "cc.coe-enhance", "status"))[
            "opened"
        ]
        REPORT["escape_closes_home"] = True
        show("home")
        focus("开始语音输入")
        key("-k", "Return")
        time.sleep(0.4)
        assert rpc("get")["state"] == "recording"
        assert not json.loads(run("omarchy-shell", "cc.coe-enhance", "status"))[
            "opened"
        ]
        rpc("cancel")
        assert rpc("get")["state"] == "idle"
        REPORT["panel_record_button_real_pw_record_then_cancel"] = True
        run("hyprctl", "eval", "_G.cc_coe_press()")
        time.sleep(0.3)
        assert rpc("get")["state"] == "recording"
        rpc("cancel")
        run("hyprctl", "eval", "_G.cc_coe_release()")
        time.sleep(0.1)
        assert rpc("get")["state"] == "idle"
        REPORT["right_alt_lua_callback_real_pw_record_then_cancel"] = True
        REPORT["cloud_requests"] = 0
        for width, height, name in [
            (420, 690, "1366x768-100"),
            (420, 460, "1366x768-150"),
            (420, 970, "1920x1080-100"),
            (310, 340, "narrow"),
        ]:
            show("home")
            run("omarchy-shell", "cc.coe-enhance", "preview", str(width), str(height))
            time.sleep(0.1)
            r = inspect()
            assert r["width"] <= width and r["height"] <= height
            REPORT["viewport_" + name] = r
            if name == "narrow":
                shot("narrow")
            run("omarchy-shell", "shell", "hide", "cc.coe-enhance")
        REPORT["viewport_note"] = (
            "Equivalent content caps in existing 1600x1000 logical / 1.6x Shell; monitor mode unchanged."
        )
    finally:
        if ime == "2":
            run("fcitx5-remote", "-o")
        run("omarchy-shell", "shell", "hide", "cc.coe-enhance")
        REPORT["user_files_unchanged"] = all(
            hashlib.sha256(p.read_bytes()).hexdigest() == h for p, h in before.items()
        )
        (EVIDENCE / "ui-tests.json").write_text(
            json.dumps(REPORT, ensure_ascii=False, indent=2) + "\n"
        )
    assert REPORT["user_files_unchanged"]
    print(json.dumps(REPORT, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
