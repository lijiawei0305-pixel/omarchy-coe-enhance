#!/usr/bin/env python3
"""Activation-free private D-Bus, real Coe/bridge + local native Aliyun/LLM.
No cloud calls or user config writes. Deterministic PCM, fixed mock transcripts;
not a speech accuracy test. Clipboard is temporarily used and restored.
"""

import argparse
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[1]
PHRASES = [
    "我正在使用 Omarchy，并通过 Qwen Audio 进行中文语音识别。",
    "使用 VASP 和 DFT 计算 Cu(111) 表面的结合能。",
]


def stats(a):
    a = sorted(a)
    return dict(
        n=len(a),
        p50=statistics.median(a),
        p95=a[math.ceil(0.95 * len(a)) - 1],
        minimum=a[0],
        maximum=a[-1],
    )


def wait(fn, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if fn():
            return
        time.sleep(0.002)
    raise AssertionError("isolated test timed out")


def proc(pid):
    fields = Path(f"/proc/{pid}/stat").read_text().split()
    rss = int(
        next(
            l.split()[1]
            for l in Path(f"/proc/{pid}/status").read_text().splitlines()
            if l.startswith("VmRSS:")
        )
    )
    return dict(
        cpu_ticks=int(fields[13]) + int(fields[14]),
        rss_kib=rss,
        threads=int(fields[19]),
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--binary", required=True)
    ap.add_argument("--scripts", default=str(ROOT / "scripts"))
    ap.add_argument("--output", required=True)
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument(
        "--target", choices=["clipboard", "terminal", "gui"], default="clipboard"
    )
    ap.add_argument("--durations", default="1,10,60")
    ap.add_argument("--osd", action="store_true", help="Run the unmodified GTK OSD via the production host")
    args = ap.parse_args()
    if "/run/user/" in os.environ.get(
        "DBUS_SESSION_BUS_ADDRESS", ""
    ) or not os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
        raise RuntimeError("Use tests/dbus-isolated.conf private bus")
    old_clip = subprocess.run(["wl-paste", "--no-newline"], capture_output=True)
    report = {
        "paid_requests": 0,
        "audio": "deterministic 16kHz PCM fixture; mock returns fixed Chinese/technical phrases",
        "completion": "exact UTF-8 clipboard readback, not target-app insertion"
        if args.target == "clipboard"
        else "actual terminal read/Chromium input event acknowledged",
        "groups": {},
    }
    with tempfile.TemporaryDirectory(prefix="coe-perf-") as tmp:
        tmp = Path(tmp)
        os.environ.update(
            COE_CONFIG=str(tmp / "coe/config.yaml"),
            COE_ENHANCE_CONFIG=str(tmp / "plugin"),
            XDG_CONFIG_HOME=str(tmp),
            COE_ENHANCE_BRIDGE="1",
            HTTP_PROXY="http://127.0.0.1:9",
            HTTPS_PROXY="http://127.0.0.1:9",
            NO_PROXY="127.0.0.1,localhost",
            COE_PERF_TRACE=str(tmp / "trace.jsonl"),
        )
        sys.path.insert(0, args.scripts)
        import coe_config as cfg

        spec = importlib.util.spec_from_file_location(
            "perf_bridge", Path(args.scripts) / "coe-bridge.py"
        )
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        m.RUNTIME = tmp / "runtime"
        cfg.private_dir(m.RUNTIME)
        os.environ["COE_ENHANCE_OSD_SOCKET"] = str(m.RUNTIME / "osd/audio.sock")
        m.HELD_FILE = m.RUNTIME / "held.json"
        cfg.initialize()
        children = []
        initial_window = None

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def setup(self):
                super().setup()
                import socket

                self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

            def log_message(self, *a):
                pass

            def do_GET(self):
                body = b"""<!doctype html><meta charset=utf-8><title>Coe performance receiver</title><textarea autofocus style="width:90vw;height:70vh" oninput="fetch('/capture',{method:'POST',body:this.value})"></textarea>"""
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                if self.path == "/capture":
                    self.server.received = self.rfile.read(
                        int(self.headers["Content-Length"])
                    ).decode()
                    self.send_response(200)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                raw = self.rfile.read(int(self.headers["Content-Length"]))
                data = json.loads(raw)
                llm = self.path.endswith("/chat/completions")
                self.server.counts["llm" if llm else "asr"] += 1
                time.sleep(0.060 if llm else 0.040)
                if llm:
                    assert (
                        data["messages"][0]["role"] == "system"
                        and data["model"] == "mock-llm"
                    )
                    out = {
                        "choices": [
                            {
                                "message": {
                                    "role": "assistant",
                                    "content": self.server.phrase,
                                }
                            }
                        ]
                    }
                else:
                    assert (
                        data["model"] == "qwen-audio-3.0-asr-flash"
                        and "data:audio/wav;base64,"
                        in data["input"]["messages"][-1]["content"][0]["input_audio"][
                            "data"
                        ]
                    )
                    out = {"output": {"text": self.server.phrase}}
                body = json.dumps(out, ensure_ascii=False).encode()
                self.send_response(self.server.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.daemon_threads = True
        server.counts = {"asr": 0, "llm": 0}
        server.phrase = PHRASES[0]
        server.status = 200
        server.received = ""
        threading.Thread(target=server.serve_forever, daemon=True).start()
        endpoint = f"http://127.0.0.1:{server.server_port}"
        p = dict(
            cfg.PRESETS["aliyun"],
            endpoint=endpoint + "/api",
            model="qwen-audio-3.0-asr-flash",
            timeout=2,
        )
        cfg.save_profile({"profile": p, "api_key": "mock-only"}, lambda: None)
        recorder = tmp / "recorder.py"
        recorder.write_text("""#!/usr/bin/python3
import math,struct,signal,sys,time
signal.signal(signal.SIGINT,lambda *_:sys.exit(0))
p=b''.join(struct.pack('<h',int(5000*math.sin(i*2*math.pi*400/16000))) for i in range(1600))
sys.stdout.buffer.write(p*int(sys.argv[sys.argv.index('--rate')+1]));sys.stdout.buffer.flush()
while True:time.sleep(10)
""")
        # Fixed PCM duration set via generated recorder content, actual exec/Stop.
        recorder.chmod(0o700)
        b = m.Bridge("performance-isolated")
        b.emit = lambda *_: (
            b.snapshot()
        )  # include real JSON/YAML snapshot work, suppress stdout
        threading.Thread(target=b.loop.run, daemon=True).start()
        if args.osd:
            b.osd.start()
        process = None
        import coe_output

        initial_window = coe_output.active_window()
        received_file = tmp / "received.txt"
        received_file.write_text("")
        if args.target == "terminal":
            helper = tmp / "receiver.py"
            helper.write_text(
                "import os,sys,tty\ntty.setraw(0)\nwhile True:\n data=os.read(0,65536)\n with open(sys.argv[1],'ab') as f:f.write(data)\n"
            )
            children.append(
                subprocess.Popen(
                    [
                        "foot",
                        "--config=" + str(Path.home() / ".config/foot/foot.ini"),
                        "--title=Coe performance receiver",
                        "python3",
                        str(helper),
                        str(received_file),
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            )
        elif args.target == "gui":
            children.append(
                subprocess.Popen(
                    [
                        "chromium",
                        "--disable-background-networking",
                        "--no-first-run",
                        "--no-default-browser-check",
                        "--user-data-dir=" + str(tmp / "browser"),
                        "--app=" + endpoint,
                        "--class=cc.coe-perf-test",
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            )
        if children:
            expected_class = "foot" if args.target == "terminal" else "cc.coe-perf-test"
            wait(
                lambda: (
                    coe_output.active_window().get("pid") == children[0].pid
                    or coe_output.active_window().get("class") == expected_class
                ),
                15,
            )
            time.sleep(0.5)
        expected = ""
        try:
            for enabled in [False, True]:
                for seconds in [int(x) for x in args.durations.split(",")]:
                    s = cfg.read_store()
                    llm = dict(
                        s["llm"],
                        enabled=enabled,
                        endpoint=endpoint + "/v1",
                        model="mock-llm",
                        timeout=2,
                    )
                    cfg.save_profile(
                        {
                            "id": s["active"],
                            "profile": cfg.active_profile(s),
                            "llm": llm,
                            "llm_key": "mock-llm",
                        },
                        lambda: None,
                    )
                    y, d = cfg.yaml_load()
                    assert (
                        d["asr"]["endpoint"].startswith(endpoint)
                        and d["asr"]["provider"] == "aliyun-asr"
                    )
                    d["audio"] = {
                        "recorder_binary": str(recorder),
                        "sample_rate": 16000,
                        "channels": 1,
                        "format": "s16",
                    }
                    buf = io.StringIO()
                    y.dump(d, buf)
                    cfg.atomic(cfg.CONFIG, buf.getvalue())
                    text = recorder.read_text()
                    import re

                    text = re.sub(
                        r"p\*int\(sys.argv\[sys.argv.index\(\x27--rate\x27\)\+1\]\)",
                        f"p*{seconds * 10}",
                        text,
                    )
                    text = re.sub(r"p\*\d+", f"p*{seconds * 10}", text)
                    recorder.write_text(text)
                    if process:
                        process.terminate()
                        process.wait(5)
                    t = time.perf_counter()
                    process = subprocess.Popen(
                        [args.binary, "serve"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    wait(lambda: b.get_status()[0] == "idle")
                    cold = (time.perf_counter() - t) * 1000
                    time.sleep(0.4)
                    group_start = time.monotonic_ns()
                    a = []
                    starts = []
                    before = proc(process.pid)
                    counts = dict(server.counts)
                    for i in range(args.n):
                        server.phrase = PHRASES[i % 2]
                        t = time.perf_counter()
                        b.trigger("start")
                        starts.append((time.perf_counter() - t) * 1000)
                        # Excluded from post-stop timing; allow fixture to fill real pipe.
                        time.sleep(0.045 if seconds < 60 else 0.070)
                        sid = b.get_status()[1]
                        t = time.perf_counter()
                        b.trigger("stop")
                        if args.target == "clipboard":
                            wait(
                                lambda: (
                                    subprocess.run(
                                        ["wl-paste", "--no-newline"],
                                        capture_output=True,
                                    ).stdout.decode()
                                    == server.phrase
                                )
                            )
                        else:
                            expected += server.phrase
                            try:
                                wait(
                                    lambda: (
                                        (
                                            received_file.read_text()
                                            if args.target == "terminal"
                                            else server.received
                                        )
                                        == expected
                                    )
                                )
                            except AssertionError:
                                print(
                                    json.dumps(
                                        {
                                            "target": args.target,
                                            "received_bytes": len(
                                                received_file.read_bytes()
                                            )
                                            if args.target == "terminal"
                                            else len(server.received),
                                            "expected_bytes": len(expected.encode()),
                                            "notice": b.notice,
                                            "error": b.error,
                                            "panel": b.panel,
                                            "switched": b.switched,
                                            "target_present": bool(b.target),
                                            "active_matches": coe_output.identity(
                                                coe_output.active_window()
                                            )
                                            == coe_output.identity(b.target),
                                        }
                                    ),
                                    flush=True,
                                )
                                raise
                        m.perf.mark(
                            sid,
                            "T8_clipboard_confirmed"
                            if args.target == "clipboard"
                            else "T8_application_confirmed",
                        )
                        a.append((time.perf_counter() - t) * 1000)
                        assert b.get_status()[0] == "idle"
                    after = proc(process.pid)
                    expected_calls = {"asr": args.n, "llm": args.n if enabled else 0}
                    delta = {k: server.counts[k] - counts[k] for k in counts}
                    assert delta == expected_calls, (delta, expected_calls)
                    report["groups"][f"{'llm' if enabled else 'asr'}_{seconds}s"] = {
                        "total_ms": stats(a),
                        "samples_ms": a,
                        "start_command_ms": stats(starts),
                        "cold_ready_ms": cold,
                        "cpu_ms": (after["cpu_ticks"] - before["cpu_ticks"])
                        * 1000
                        / os.sysconf("SC_CLK_TCK"),
                        "resource_before": before,
                        "resource_after": after,
                        "calls": delta,
                        "errors": 0,
                        "range_ns": [group_start, time.monotonic_ns()],
                    }
            process.terminate()
            process.wait(5)
            process = None
        finally:
            if process:
                process.terminate()
                process.wait(5)
            b.alive = False
            b.loop.quit()
            server.shutdown()
            server.server_close()
            b.osd.close()
            for child in children:
                child.terminate()
                try:
                    child.wait(5)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(5)
            if initial_window.get("address"):
                subprocess.run(
                    [
                        "hyprctl",
                        "eval",
                        "hl.dispatch(hl.dsp.focus({window="
                        + json.dumps("address:" + initial_window["address"])
                        + "}))",
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            if old_clip.returncode == 0:
                subprocess.run(
                    ["wl-copy"],
                    input=old_clip.stdout,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
        traces = [json.loads(l) for l in (tmp / "trace.jsonl").read_text().splitlines()]
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps(report, indent=2) + "\n")
        Path(args.output + ".traces.json").write_text(
            json.dumps(traces, indent=2) + "\n"
        )
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
