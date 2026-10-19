#!/usr/bin/env python3
"""Opt-in live desktop tests. Isolated terminal/browser, local Mock ASR, restores config.
Run manually from the plugin checkout; never included in unittest discovery.
"""

import json
import os
import signal
from pathlib import Path
import socket
import shlex
import re
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import dbus
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib
import coe_config as cfg
import coe_output as output

RUNTIME = Path(os.environ["XDG_RUNTIME_DIR"]) / "coe-enhance"
SOCK = RUNTIME / "bridge.sock"
PHRASES = [
    "我正在使用 Omarchy，需要在 VS Code 里面配置 GitHub。",
    "使用 VASP 和 DFT 计算 Cu(111) 表面的结合能。",
    "这是中文语音输入测试。",
]
ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / ".runtime/live"
ART.mkdir(parents=True, exist_ok=True)
CACHE = Path.home() / ".cache/omarchy-coe-enhance-tests"
CACHE.mkdir(parents=True, exist_ok=True)


def rpc(action, **kw):
    with socket.socket(socket.AF_UNIX) as s:
        s.settimeout(30)
        s.connect(str(SOCK))
        s.sendall((json.dumps({"action": action, **kw}) + "\n").encode())
        data = b""
        while b"\n" not in data:
            chunk = s.recv(65536)
            if not chunk:
                raise ConnectionError("Bridge closed before complete response")
            data += chunk
    r = json.loads(data)
    if not r.get("ok"):
        raise RuntimeError(r.get("error"))
    return r


def run(cmd, **kw):
    if cmd[0] == "wl-copy":
        return subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
            timeout=15,
            **kw,
        )
    return subprocess.run(cmd, capture_output=True, check=True, timeout=15, **kw)


def send_key(mods, key):
    run(
        [
            "hyprctl",
            "eval",
            f'hl.dispatch(hl.dsp.send_key_state({{mods="{mods}",key="{key}",state="down"}})); hl.timer(function() hl.dispatch(hl.dsp.send_key_state({{mods="{mods}",key="{key}",state="up"}})) end,{{timeout=50,type="oneshot"}})',
        ]
    )
    time.sleep(0.15)


def send_bound_command():
    # wtype's virtual keyboard does not invoke this machine's global bindings.
    # Exercise the exact compositor dispatcher command; physical F9 is separate.
    command = shlex.join(
        [
            str(Path.home() / ".local/share/omarchy-coe-enhance/venv/bin/python"),
            "-B",
            str(
                Path.home()
                / ".config/omarchy/plugins/cc.coe-enhance/scripts/coe-bridge.py"
            ),
            "request",
            "toggle",
        ]
    )
    run(
        ["hyprctl", "eval", "hl.dispatch(hl.dsp.exec_cmd(" + json.dumps(command) + "))"]
    )


def window_for(pid):
    for _ in range(80):
        ws = json.loads(run(["hyprctl", "-j", "clients"]).stdout)
        for w in ws:
            if w["pid"] == pid:
                return w
        time.sleep(0.1)
    raise RuntimeError("Test window did not map")


def focus(w):
    run(
        [
            "hyprctl",
            "eval",
            "hl.dispatch(hl.dsp.focus({window="
            + json.dumps("address:" + w["address"])
            + "}))",
        ]
    )
    time.sleep(0.2)
    if output.identity(output.active_window()) != output.identity(w):
        raise RuntimeError("Could not safely focus test window")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        page = """<!doctype html><meta charset="utf-8"><title>Coe isolated browser input test</title><style>body{background:#20242c;color:white;padding:40px;font:20px sans-serif}textarea{width:90%;height:300px;font:24px sans-serif}</style><h1>Coe 本机输入测试</h1><textarea autofocus oninput="fetch('/capture',{method:'POST',body:this.value})"></textarea>"""
        self.send_response(200)
        self.end_headers()
        self.wfile.write(page.encode())

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if self.path == "/capture":
            self.server.browser_text = raw.decode()
            payload = b"{}"
        elif self.path.endswith("/chat/completions"):
            self.server.llm_calls += 1
            payload = json.dumps(
                {
                    "choices": [
                        {"message": {"role": "assistant", "content": self.server.text}}
                    ]
                }
            ).encode()
        else:
            self.server.asr_calls += 1
            self.server.upload = raw
            if self.server.delay:
                time.sleep(self.server.delay)
            payload = json.dumps(
                {"text": self.server.text}, ensure_ascii=False
            ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(payload)


def main():
    report = {}
    children = []
    code_data = None
    states = []
    DBusGMainLoop(set_as_default=True)
    bus = dbus.SessionBus(private=True)
    loop = GLib.MainLoop()
    bus.add_signal_receiver(
        lambda state, sid, detail: states.append(str(state)),
        signal_name="StateChanged",
        dbus_interface="com.mistermorph.Coe.Dictation1",
        bus_name="com.mistermorph.Coe",
        path="/com/mistermorph/Coe",
    )
    threading.Thread(target=loop.run, daemon=True).start()
    initial_focus = output.active_window()
    ime = run(["fcitx5-remote"]).stdout.decode().strip()
    paths = [cfg.CONFIG, cfg.ENV, cfg.STORE, cfg.ROOT / "last-good.yaml"]
    tx = cfg.Transaction(paths)
    tx.backup_files()
    report["backup"] = str(tx.backup)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.text = PHRASES[0]
    server.asr_calls = 0
    server.llm_calls = 0
    server.browser_text = ""
    server.delay = 0
    threading.Thread(target=server.serve_forever, daemon=True).start()
    ep = f"http://127.0.0.1:{server.server_port}"
    try:
        run(["omarchy-shell", "shell", "hide", "cc.coe-enhance"])
        rpc("panel", open=False)
        time.sleep(0.3)
        # Prove real PipeWire start/cancel separately; never sends audio to a cloud service.
        p = dict(cfg.PRESETS["compatible"])
        p.update(
            name="LOCAL MOCK TEST",
            model="mock-transcribe",
            timeout=5,
            endpoint=ep + "/v1/audio/transcriptions",
        )
        snap = rpc("save", profile=p, api_key="local-mock-key", output="smart")
        ident = snap["store"]["active"]
        p = next(x for x in snap["store"]["profiles"] if x["id"] == ident)
        rpc("start")
        assert rpc("get")["state"] == "recording"
        time.sleep(0.4)
        rpc("cancel")
        assert rpc("get")["state"] == "idle"
        report["pipewire_record_cancel"] = "PASS (real pw-record)"
        # Deterministic recording fixture, still through the real Coe recorder lifecycle/WAV/ASR/LLM/DBus.
        recorder = ART / "pcm-recorder.py"
        recorder.write_text("""#!/usr/bin/python3
import math,struct,signal,sys,time
alive=True
def stop(*a):
 global alive;alive=False
signal.signal(signal.SIGINT,stop);signal.signal(signal.SIGTERM,stop)
p=b''.join(struct.pack('<h',int(5000*math.sin(i*2*math.pi*400/16000))) for i in range(1600))
while alive:
 sys.stdout.buffer.write(p);sys.stdout.buffer.flush();time.sleep(.1)
""")
        recorder.chmod(0o700)
        y, doc = cfg.yaml_load()
        doc.setdefault("audio", {})["recorder_binary"] = str(recorder)
        import io

        buf = io.StringIO()
        y.dump(doc, buf)
        cfg.atomic(cfg.CONFIG, buf.getvalue())
        rpc("service", verb="restart")
        # Terminal raw input cannot execute recognized text as a shell command.
        capture = ART / "terminal.txt"
        helper = ART / "terminal-capture.py"
        helper.write_text("""import os,sys,termios,tty,select,time
fd=sys.stdin.fileno();old=termios.tcgetattr(fd);tty.setraw(fd)
try:
 while True:
  r,_,_=select.select([fd],[],[],60)
  if not r:break
  data=os.read(fd,65536)
  with open(sys.argv[1],'ab') as f:f.write(data)
finally:termios.tcsetattr(fd,termios.TCSADRAIN,old)
""")
        capture.write_text("")
        terminal = subprocess.Popen(
            [
                "foot",
                "--title=Coe isolated output test",
                "python3",
                str(helper),
                str(capture),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        children.append(terminal)
        w = window_for(terminal.pid)
        focus(w)
        run(["fcitx5-remote", "-s", "rime"])
        run(["fcitx5-remote", "-o"])
        report["rime_enabled_during_paste"] = (
            run(["fcitx5-remote"]).stdout.decode().strip()
        )
        expected = ""
        for index, phrase in enumerate(PHRASES):
            server.text = phrase
            focus(w)
            if index == 0:
                send_bound_command()
                for _ in range(30):
                    if rpc("get")["state"] == "recording":
                        break
                    time.sleep(0.1)
                assert rpc("get")["state"] == "recording"
            else:
                rpc("start")
            time.sleep(0.5)
            if index == 0:
                send_bound_command()
            else:
                rpc("stop")
            expected += phrase
            for _ in range(45):
                if capture.read_text() == expected:
                    break
                time.sleep(0.1)
            assert capture.read_text() == expected, (
                capture.read_text(),
                expected,
                {k: v for k, v in rpc("get").items() if k != "store"},
            )
        report["terminal_chinese_mixed_technical"] = (
            "PASS: exact UTF-8 via Shift+Insert, each result once; Rime active"
        )
        report["hotkey_toggle"] = (
            "PASS: registered F9 command via Hyprland exec dispatcher, start/stop; physical key event NOT TESTED"
        )
        assert server.upload.count(b"RIFF") >= 1
        report["wav_real_provider_mock_http"] = "PASS"
        # Empty response must preserve existing clipboard and terminal bytes.
        before = capture.read_bytes()
        run(["wl-copy"], input=b"OLD-CLIPBOARD-SENTINEL")
        server.text = ""
        focus(w)
        rpc("start")
        time.sleep(0.4)
        try:
            rpc("stop")
        except RuntimeError:
            pass
        time.sleep(0.2)
        assert capture.read_bytes() == before
        assert run(["wl-paste", "--no-newline"]).stdout == b"OLD-CLIPBOARD-SENTINEL"
        report["empty_and_old_clipboard"] = "PASS"
        # Independent LLM real Adapter against local Mock, then stub again.
        llm = dict(cfg.read_store()["llm"])
        llm.update(enabled=True, endpoint=ep + "/v1", model="mock-cleanup", timeout=5)
        rpc("save", id=ident, profile=p, api_key="", llm=llm, llm_key="local-llm-key")
        focus(w)
        server.text = PHRASES[2]
        rpc("start")
        time.sleep(0.4)
        rpc("stop")
        time.sleep(0.2)
        assert server.llm_calls > 0
        report["llm_independent"] = (
            "PASS: Go chat Adapter called; independent key; stub restored"
        )
        llm["enabled"] = False
        rpc("save", id=ident, profile=p, llm=llm)
        # Focus change must copy only, never refocus or paste into another user window.
        focus(w)
        server.text = "焦点变化后只复制。"
        rpc("start")
        time.sleep(0.4)
        run(["omarchy-shell", "shell", "summon", "cc.coe-enhance", "{}"])
        time.sleep(0.2)
        before = capture.read_bytes()
        rpc("stop")
        time.sleep(0.3)
        assert capture.read_bytes() == before
        assert run(["wl-paste", "--no-newline"]).stdout.decode() == server.text
        report["panel_focus_safety"] = "PASS: only clipboard while panel open"
        run(["omarchy-shell", "shell", "hide", "cc.coe-enhance"])
        # Isolated Chromium textarea; no interaction with existing browsing data or sites.
        browser = subprocess.Popen(
            [
                "chromium",
                "--no-first-run",
                "--no-default-browser-check",
                "--user-data-dir=" + str(CACHE / "chromium-profile"),
                "--app=" + ep,
                "--class=cc.coe-browser-test",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        children.append(browser)
        bw = window_for(browser.pid)
        focus(bw)
        time.sleep(0.6)
        server.text = PHRASES[0]
        rpc("start")
        time.sleep(0.5)
        rpc("stop")
        for _ in range(30):
            if server.browser_text == server.text:
                break
            time.sleep(0.1)
        assert server.browser_text == server.text, (
            server.browser_text,
            rpc("get").get("notice"),
        )
        report["chromium_gui_ctrl_v"] = (
            "PASS: isolated native Chromium textarea receives exact Chinese once"
        )
        # User switches to another app during recording: neither target receives text.
        focus(w)
        server.text = "用户切换窗口，仅复制。"
        rpc("start")
        time.sleep(0.3)
        focus(bw)
        before = capture.read_bytes()
        old_browser = server.browser_text
        rpc("stop")
        time.sleep(0.3)
        assert capture.read_bytes() == before
        assert server.browser_text == old_browser
        assert run(["wl-paste", "--no-newline"]).stdout.decode() == server.text
        report["user_window_switch"] = (
            "PASS: no paste into either window, no forced refocus"
        )
        # VS Code in an isolated profile/file, with telemetry/extensions disabled.
        code_data = CACHE / ("vscode-profile-" + str(os.getpid()))
        (code_data / "User").mkdir(parents=True, exist_ok=True)
        (code_data / "User/settings.json").write_text(
            json.dumps(
                {
                    "workbench.startupEditor": "none",
                    "security.workspace.trust.enabled": False,
                    "window.restoreWindows": "none",
                    "telemetry.telemetryLevel": "off",
                    "update.mode": "none",
                }
            )
        )
        code_file = ART / ("coe-output-test-" + str(os.getpid()) + ".txt")
        code_file.write_text("")
        code = subprocess.Popen(
            [
                "code",
                "--user-data-dir=" + str(code_data),
                "--extensions-dir=" + str(CACHE / "vscode-extensions"),
                "--new-window",
                "--disable-extensions",
                "--skip-welcome",
                "--skip-release-notes",
                str(code_file),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        children.append(code)
        cw = None
        for _ in range(120):
            cw = next(
                (
                    x
                    for x in json.loads(run(["hyprctl", "-j", "clients"]).stdout)
                    if code_file.name in x.get("title", "")
                ),
                None,
            )
            if cw:
                break
            time.sleep(0.1)
        assert cw, "VS Code isolated test file not visible"
        focus(cw)
        time.sleep(1.5)
        send_key("CTRL", "1")
        time.sleep(0.3)
        server.text = PHRASES[1]
        rpc("start")
        time.sleep(0.5)
        rpc("stop")
        time.sleep(0.5)
        send_key("CTRL", "S")
        time.sleep(0.4)
        assert code_file.read_text() == server.text, (
            code_file.read_text(),
            rpc("get").get("notice"),
        )
        report["vscode_ctrl_v"] = (
            "PASS: isolated VS Code file saved exact UTF-8 Chinese/technical symbols"
        )
        send_key("CTRL SHIFT", "W")
        report["dbus_events"] = "PASS: " + ",".join(sorted(set(states)))
        assert all(
            x in states
            for x in ["idle", "recording", "processing", "completed", "error"]
        )
        # A genuine service startup failure must restore byte-for-byte previous config.
        old = {p: p.read_bytes() for p in paths}
        bad = dict(cfg.read_store()["llm"])
        bad.update(prompt="{{", enabled=True)
        try:
            rpc("save", id=ident, profile=p, llm=bad)
        except RuntimeError:
            pass
        else:
            raise AssertionError("Invalid Go template should fail startup")
        assert old == {p: p.read_bytes() for p in paths}
        for _ in range(25):
            if rpc("get")["state"] != "offline":
                break
            time.sleep(0.1)
        assert rpc("get")["state"] != "offline"
        report["actual_service_failure_rollback"] = (
            "PASS: invalid Go template, previous files/service restored"
        )
    finally:
        try:
            run(["omarchy-shell", "shell", "hide", "cc.coe-enhance"])
        except Exception:
            pass
        if code_data:
            flag = ("--user-data-dir=" + str(code_data)).encode()
            for path in Path("/proc").glob("[0-9]*/cmdline"):
                try:
                    data = path.read_bytes()
                    if (
                        re.search(re.escape(flag) + rb"(?:\x00| |$)", data)
                        and b"--type=" not in data
                        and (path.parent / "exe").resolve()
                        == Path("/usr/share/code/code")
                    ):
                        os.kill(int(path.parent.name), signal.SIGTERM)
                except (OSError, ValueError):
                    pass
        for child in children:
            try:
                child.terminate()
                child.wait(timeout=5)
            except Exception:
                pass
        tx.rollback()
        run(["systemctl", "--user", "restart", "coe.service"])
        if ime == "1":
            run(["fcitx5-remote", "-c"])
        elif ime == "2":
            run(["fcitx5-remote", "-o"])
        try:
            focus(initial_focus)
        except Exception:
            pass
        loop.quit()
        bus.close()
        server.shutdown()
        server.server_close()
        (ART / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
