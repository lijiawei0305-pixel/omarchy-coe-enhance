#!/usr/bin/env python3
"""Opt-in paid cloud test: public Chinese sample -> real Coe -> isolated terminal.

Credentials are read only from a private file or saved Profile/env, never argv.
Audio fixtures are public test data, not a recording of the user's microphone.
"""

import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import urllib.request
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import coe_config as cfg
import coe_output as output
from live_e2e import rpc, run, focus, window_for, ROOT


def main():
    credential = cfg.ROOT / "aliyun-test-credential.json"
    report = {}
    prior_window = output.active_window()
    prior_rime = run(["fcitx5-remote"]).stdout.decode().strip()
    child = None
    if credential.exists():
        r = json.loads(credential.read_text())
        host = urlsplit(r["endpoint"])
        endpoint = (
            host.scheme
            + "://"
            + host.netloc
            + "/api/v1/services/aigc/multimodal-generation/generation"
        )
        profiles = []
        for model in ("qwen-audio-3.0-asr-flash", "fun-asr-flash-2026-06-15"):
            p = dict(
                cfg.PRESETS["aliyun"],
                name="阿里云 / " + model,
                model=model,
                endpoint=endpoint,
                timeout=60,
            )
            old = next(
                (x for x in cfg.read_store()["profiles"] if x["name"] == p["name"]),
                None,
            )
            rpc(
                "save",
                profile=p,
                id=old["id"] if old else "",
                api_key=r["api_key"],
                make_default=model.startswith("qwen"),
            )
            profiles.append(
                next(x for x in cfg.read_store()["profiles"] if x["name"] == p["name"])
            )
        # Profile-specific env refs now own the retained credentials.
        credential.unlink()
    else:
        profiles = [
            x for x in cfg.read_store()["profiles"] if x["provider"] == "aliyun-asr"
        ]
    if not profiles:
        raise RuntimeError("No saved Aliyun Profile")
    rpc("save", profile=profiles[0], id=profiles[0]["id"], output="smart")
    with tempfile.TemporaryDirectory(prefix="coe-cloud-") as tmp:
        tmp = Path(tmp)
        with urllib.request.urlopen(
            "https://dashscope.oss-cn-beijing.aliyuncs.com/audios/welcome.mp3",
            timeout=20,
        ) as response:
            data = response.read(2_000_001)
        assert len(data) < 2_000_000
        (tmp / "sample.mp3").write_bytes(data)
        run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-i",
                str(tmp / "sample.mp3"),
                "-ar",
                "16000",
                "-ac",
                "1",
                "-f",
                "s16le",
                str(tmp / "sample.pcm"),
            ]
        )
        recorder = tmp / "fixture-recorder"
        recorder.write_text(
            "#!/usr/bin/env python3\nimport sys,signal,time\nsignal.signal(signal.SIGINT,lambda *_:sys.exit(0))\nsys.stdout.buffer.write(open("
            + repr(str(tmp / "sample.pcm"))
            + ", 'rb').read());sys.stdout.buffer.flush()\nwhile True:time.sleep(.1)\n"
        )
        recorder.chmod(0o700)
        capture = tmp / "terminal.txt"
        capture.write_text("")
        helper = tmp / "capture.py"
        helper.write_text(
            "import sys,os,tty\ntty.setraw(sys.stdin.fileno())\nwhile True:\n d=os.read(sys.stdin.fileno(),65536)\n with open(sys.argv[1],'ab') as f:f.write(d)\n"
        )
        try:
            child = subprocess.Popen(
                [
                    "foot",
                    "--title=Coe cloud ASR isolated test",
                    "python3",
                    str(helper),
                    str(capture),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            window = window_for(child.pid)
            run(["fcitx5-remote", "-o"])
            for p in profiles:
                rpc("save", profile=p, id=p["id"], output="smart")
                clean_config = cfg.CONFIG.read_bytes()
                try:
                    y, doc = cfg.yaml_load()
                    doc.setdefault("audio", {})["recorder_binary"] = str(recorder)
                    buf = io.StringIO()
                    y.dump(doc, buf)
                    cfg.atomic(cfg.CONFIG, buf.getvalue())
                    rpc("service", verb="restart")
                    time.sleep(0.4)
                    focus(window)
                    capture.write_text("")
                    rpc("start")
                    time.sleep(0.4)
                    rpc("stop")
                    for _ in range(60):
                        text = capture.read_text()
                        if text.strip():
                            break
                        time.sleep(0.1)
                    assert text.strip() and "阿里云" in text, (p["model"], text)
                    assert text.count("阿里云") == 1, "Duplicate cloud insertion"
                    report[p["model"]] = {
                        "result": "PASS",
                        "public_sample_transcript": text,
                        "matches_expected_phrase": text == "欢迎使用阿里云。",
                        "output": "Shift+Insert, exact once, Rime enabled",
                        "protocol": "DashScope JSON + WAV Data URI",
                    }
                finally:
                    cfg.atomic(cfg.CONFIG, clean_config)
                    rpc("service", verb="restart")
                    time.sleep(0.4)
            rpc("save", profile=profiles[0], id=profiles[0]["id"], output="smart")
            cfg.atomic(cfg.ROOT / "last-good.yaml", cfg.CONFIG.read_bytes(), 0o600)
        finally:
            if child:
                child.terminate()
                child.wait(timeout=4)
            if prior_rime == "1":
                run(["fcitx5-remote", "-c"])
            if output.identity(prior_window):
                focus(prior_window)
    report["microphone_accuracy"] = (
        "NOT TESTED: public speech fixture, not human live speech"
    )
    (ROOT / ".runtime/cloud.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
